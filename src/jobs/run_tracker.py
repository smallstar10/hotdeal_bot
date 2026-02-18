from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import db
from src.core.config import load_settings
from src.core.keywords import ensure_default_keywords, list_active_keywords
from src.core.logger import get_logger
from src.core.timeutil import kst_add_hours, kst_text, now_kst
from src.jobs.common import dedupe_quotes, in_cooldown, insert_price_if_needed, product_price_series, upsert_product, upsert_watchlist
from src.notify.formatters import format_alert
from src.notify.telegram_notify import TelegramNotifier
from src.providers import load_provider
from src.providers.base import ProductQuote
from src.scoring.deal_score import DealMetrics, calc_deal_metrics

logger = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")


@dataclass
class AlertCandidate:
    q: ProductQuote
    metrics: object
    final_score: float
    preference_bonus: float
    preference_tags: list[str]
    preference_reason: str
    preferred: bool


def _parse_kst_text(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except Exception:
        try:
            return datetime.fromisoformat(value).astimezone(KST)
        except Exception:
            return None


def _match_keywords(text: str, keywords: list[str]) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    out: list[str] = []
    for kw in keywords:
        k = (kw or "").strip().lower()
        if k and k in lower:
            out.append(kw.strip())
    return out


def _evaluate_preference(settings, q: ProductQuote) -> tuple[float, list[str], str, bool]:
    target = " ".join([q.title or "", q.category or "", q.keyword or ""]).lower()
    food_hits = _match_keywords(target, settings.preferred_food_keywords)
    event_hits = _match_keywords(target, settings.preferred_event_keywords)
    bonus = len(food_hits) * float(settings.food_bonus_per_hit) + len(event_hits) * float(settings.event_bonus_per_hit)
    bonus = max(0.0, min(float(settings.preference_bonus_cap), bonus))

    tags: list[str] = []
    reasons: list[str] = []
    if food_hits:
        tags.append("식품")
        reasons.append(f"식품키워드({', '.join(food_hits[:3])})")
    if event_hits:
        tags.append("이벤트/적립")
        reasons.append(f"혜택키워드({', '.join(event_hits[:3])})")
    preferred = bool(food_hits or event_hits)
    return bonus, tags, ", ".join(reasons), preferred


def _get_state(sqlite_path: str, key: str) -> str:
    row = db.fetchone(sqlite_path, "SELECT value FROM bot_state WHERE key=?", (key,))
    return str(row["value"]) if row and row["value"] is not None else ""


def _set_state(sqlite_path: str, key: str, value: str, ts_iso: str) -> None:
    db.execute(
        sqlite_path,
        """
        INSERT INTO bot_state(key, value, updated_ts_kst)
        VALUES (?,?,?)
        ON CONFLICT(key) DO UPDATE SET
          value=excluded.value,
          updated_ts_kst=excluded.updated_ts_kst
        """,
        (key, value, ts_iso),
    )


def _should_send_digest(sqlite_path: str, now_ts: datetime, min_interval_min: int) -> bool:
    if min_interval_min <= 0:
        return True
    raw = _get_state(sqlite_path, "tracker_digest_last_sent_kst")
    if not raw:
        return True
    prev = _parse_kst_text(raw)
    if prev is None:
        return True
    return (now_ts - prev) >= timedelta(minutes=int(min_interval_min))


def _format_near_digest(ts: datetime, cands: list[AlertCandidate], limit: int = 5) -> str:
    lines = [
        f"[KST {ts.strftime('%Y-%m-%d %H:%M')}] 핫딜 근접 후보 요약",
        f"알림 조건엔 조금 모자라지만 살펴볼 만한 상품 {min(limit, len(cands))}개",
        "",
    ]
    for i, c in enumerate(cands[:limit], start=1):
        price = int(c.metrics.current) if c.metrics.current > 0 else 0
        tag = f" [{'/'.join(c.preference_tags)}]" if c.preference_tags else ""
        lines.append(
            f"{i}) {c.q.title[:46]}{tag}\n"
            f"점수 {c.final_score:.1f} (기본 {c.metrics.deal_score:.1f} + 선호 {c.preference_bonus:.1f}), "
            f"가격 {price:,}원, 직전대비 {c.metrics.drop_prev:+.1%}\n"
            f"{c.q.url}"
        )
    return "\n".join(lines)


def _augment_prices_for_scoring(q: ProductQuote, prices: list[float]) -> list[float]:
    clean = [float(x) for x in prices if x and float(x) > 0]
    if len(clean) >= 2:
        return clean
    if q.price <= 0:
        return clean

    if q.base_price > q.price > 0:
        return [float(q.base_price), float(q.price)]

    if q.discount_rate > 0 and q.price > 0:
        denom = max(0.05, 1.0 - float(q.discount_rate))
        estimated_base = float(q.price) / denom
        if estimated_base > q.price:
            return [estimated_base, float(q.price)]
    return clean


def _estimate_metrics_without_history(q: ProductQuote) -> DealMetrics:
    current = float(q.price) if q.price > 0 else 0.0
    prev = float(q.base_price) if q.base_price > current > 0 else current
    discount = max(0.0, min(0.95, float(q.discount_rate)))
    drop_prev = discount if prev > 0 else 0.0
    drop_7d = discount
    drop_30d = discount
    near_low = 1 if discount >= 0.08 else 0
    reliability = 0.2
    if q.review_count > 0 or q.rating > 0:
        reliability = min(1.0, 0.35 + max(0.0, float(q.rating) / 10.0))
    deal_score = min(100.0, 18.0 + 72.0 * discount + 8.0 * near_low + 8.0 * reliability)
    return DealMetrics(
        current=current,
        prev=prev,
        avg_7d=prev if prev > 0 else current,
        avg_30d=prev if prev > 0 else current,
        min_30d=min(current, prev) if current > 0 and prev > 0 else current,
        drop_prev=drop_prev,
        drop_7d=drop_7d,
        drop_30d=drop_30d,
        near_low=near_low,
        reliability=reliability,
        deal_score=deal_score,
    )


def _load_tracking_targets(sqlite_path: str, n: int) -> list[dict]:
    rows = db.fetchall(
        sqlite_path,
        """
        SELECT w.product_id, w.priority, p.source_keyword
        FROM watchlist w
        JOIN products p ON p.product_id = w.product_id
        WHERE w.active=1
        ORDER BY w.priority DESC
        LIMIT ?
        """,
        (int(n),),
    )
    return [dict(r) for r in rows]


def _fetch_observed(provider, keywords: list[str], limit_per_keyword: int) -> dict[str, ProductQuote]:
    observed: dict[str, ProductQuote] = {}
    for kw in keywords:
        quotes = dedupe_quotes(provider.search_products(kw, limit_per_keyword))
        for q in quotes:
            prev = observed.get(q.product_id)
            if prev is None or (q.price > 0 and q.price < prev.price):
                observed[q.product_id] = q
    return observed


def main() -> int:
    settings = load_settings()
    db.init_db(settings.sqlite_path)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    ts = now_kst()
    ts_iso = kst_text(ts)

    try:
        ensure_default_keywords(settings.sqlite_path, settings.discovery_keywords)
        active_keywords = list_active_keywords(settings.sqlite_path)
        targets = _load_tracking_targets(settings.sqlite_path, settings.track_batch_size)
        if not targets:
            logger.info("no tracking targets, skip")
            return 0
        provider = load_provider(settings)

        keywords = [str(t.get("source_keyword") or "").strip() for t in targets if str(t.get("source_keyword") or "").strip()]
        keywords = sorted(set(keywords + active_keywords))
        if settings.data_provider == "algumon_rank":
            keywords = [""] + keywords
        observed = _fetch_observed(provider, keywords, settings.track_limit_per_keyword)

        alerted = 0
        checked = 0
        last_checked_rows: list[tuple[str, str]] = []
        snapshot_rows: list[tuple[str, str, float, float, float, float, int, float]] = []
        alert_candidates: list[AlertCandidate] = []
        near_candidates: list[AlertCandidate] = []
        evaluated_pids: set[str] = set()

        for t in targets:
            pid = str(t["product_id"])
            q = observed.get(pid)
            last_checked_rows.append((ts_iso, pid))
            if q is None:
                continue
            if q.price <= 0:
                continue

            evaluated_pids.add(pid)
            checked += 1
            upsert_product(settings.sqlite_path, q, ts_iso)
            upsert_watchlist(settings.sqlite_path, q)
            insert_price_if_needed(settings.sqlite_path, q, ts_iso, settings.min_record_interval_min)

            prices = product_price_series(settings.sqlite_path, pid, days=30)
            prices = _augment_prices_for_scoring(q, prices)
            metrics = (
                calc_deal_metrics(
                    prices_asc=prices,
                    review_count=q.review_count,
                    rating=q.rating,
                    near_low_band=settings.near_low_band,
                )
                if len(prices) >= 2
                else _estimate_metrics_without_history(q)
            )
            snapshot_rows.append(
                (
                    ts_iso,
                    pid,
                    float(metrics.deal_score),
                    float(metrics.drop_prev),
                    float(metrics.drop_7d),
                    float(metrics.drop_30d),
                    int(metrics.near_low),
                    float(metrics.reliability),
                )
            )

            trigger = (
                metrics.deal_score >= settings.alert_score_min
                and (metrics.drop_prev >= settings.min_drop_prev or metrics.drop_7d >= settings.min_drop_7d or metrics.near_low == 1)
            )
            pref_bonus, pref_tags, pref_reason, preferred = _evaluate_preference(settings, q)
            final_score = min(100.0, float(metrics.deal_score) + pref_bonus)
            dynamic_min = float(settings.alert_score_min) - (float(settings.alert_preference_relax) if preferred else 0.0)
            dynamic_min = max(35.0, dynamic_min)
            gate_reviews = int(q.review_count) >= int(settings.alert_min_reviews) or settings.data_provider == "algumon_rank"
            gate_reliability = float(metrics.reliability) >= float(settings.min_reliability) or settings.data_provider == "algumon_rank"
            gate_drop = (
                metrics.drop_prev >= settings.min_drop_prev
                or metrics.drop_7d >= settings.min_drop_7d
                or metrics.near_low == 1
                or (preferred and metrics.drop_30d >= float(settings.min_drop_30d_preferred))
            )

            near_cut = max(20.0, float(settings.alert_score_min) - float(settings.tracker_digest_score_margin))
            near_gate = final_score >= near_cut and (metrics.deal_score >= 40.0 or preferred)
            if gate_reviews and gate_reliability and near_gate and not in_cooldown(settings.sqlite_path, pid, ts_iso):
                near_candidates.append(
                    AlertCandidate(
                        q=q,
                        metrics=metrics,
                        final_score=final_score,
                        preference_bonus=pref_bonus,
                        preference_tags=pref_tags,
                        preference_reason=pref_reason,
                        preferred=preferred,
                    )
                )

            if not (gate_reviews and gate_reliability and gate_drop and final_score >= dynamic_min):
                continue
            if in_cooldown(settings.sqlite_path, pid, ts_iso):
                continue
            if not trigger and not preferred:
                # Non-preferred items still need classic trigger.
                continue

            alert_candidates.append(
                AlertCandidate(
                    q=q,
                    metrics=metrics,
                    final_score=final_score,
                    preference_bonus=pref_bonus,
                    preference_tags=pref_tags,
                    preference_reason=pref_reason,
                    preferred=preferred,
                )
            )

        # Fallback: when watched IDs are stale/mismatched, directly evaluate top observed items too.
        observed_scan_limit = max(0, int(settings.tracker_observed_scan_limit))
        if observed_scan_limit > 0:
            observed_items = sorted(
                observed.values(),
                key=lambda x: (x.discount_rate, x.review_count, x.rating),
                reverse=True,
            )[:observed_scan_limit]
            for q in observed_items:
                pid = str(q.product_id)
                if pid in evaluated_pids:
                    continue
                if q.price <= 0:
                    continue
                evaluated_pids.add(pid)

                upsert_product(settings.sqlite_path, q, ts_iso)
                upsert_watchlist(settings.sqlite_path, q)
                insert_price_if_needed(settings.sqlite_path, q, ts_iso, settings.min_record_interval_min)
                prices = product_price_series(settings.sqlite_path, pid, days=30)
                prices = _augment_prices_for_scoring(q, prices)
                checked += 1
                metrics = (
                    calc_deal_metrics(
                        prices_asc=prices,
                        review_count=q.review_count,
                        rating=q.rating,
                        near_low_band=settings.near_low_band,
                    )
                    if len(prices) >= 2
                    else _estimate_metrics_without_history(q)
                )

                pref_bonus, pref_tags, pref_reason, preferred = _evaluate_preference(settings, q)
                final_score = min(100.0, float(metrics.deal_score) + pref_bonus)
                dynamic_min = float(settings.alert_score_min) - (float(settings.alert_preference_relax) if preferred else 0.0)
                dynamic_min = max(35.0, dynamic_min)
                gate_reviews = int(q.review_count) >= int(settings.alert_min_reviews) or settings.data_provider == "algumon_rank"
                gate_reliability = float(metrics.reliability) >= float(settings.min_reliability) or settings.data_provider == "algumon_rank"
                gate_drop = (
                    metrics.drop_prev >= settings.min_drop_prev
                    or metrics.drop_7d >= settings.min_drop_7d
                    or metrics.near_low == 1
                    or (preferred and metrics.drop_30d >= float(settings.min_drop_30d_preferred))
                )

                near_cut = max(20.0, float(settings.alert_score_min) - float(settings.tracker_digest_score_margin))
                near_gate = final_score >= near_cut and (metrics.deal_score >= 40.0 or preferred)
                if gate_reviews and gate_reliability and near_gate and not in_cooldown(settings.sqlite_path, pid, ts_iso):
                    near_candidates.append(
                        AlertCandidate(
                            q=q,
                            metrics=metrics,
                            final_score=final_score,
                            preference_bonus=pref_bonus,
                            preference_tags=pref_tags,
                            preference_reason=pref_reason,
                            preferred=preferred,
                        )
                    )

                if not (gate_reviews and gate_reliability and gate_drop and final_score >= dynamic_min):
                    continue
                if in_cooldown(settings.sqlite_path, pid, ts_iso):
                    continue
                alert_candidates.append(
                    AlertCandidate(
                        q=q,
                        metrics=metrics,
                        final_score=final_score,
                        preference_bonus=pref_bonus,
                        preference_tags=pref_tags,
                        preference_reason=pref_reason,
                        preferred=preferred,
                    )
                )

        alert_candidates.sort(
            key=lambda c: (c.final_score, c.metrics.drop_prev, c.metrics.drop_7d, c.q.review_count),
            reverse=True,
        )
        selected = alert_candidates[: max(1, int(settings.alert_max_per_run))]
        for c in selected:
            msg = format_alert(
                ts,
                c.q,
                c.metrics,
                final_score=c.final_score,
                preference_tags=c.preference_tags,
                preference_reason=c.preference_reason,
            )
            notifier.send(msg)
            cooldown_until = kst_text(kst_add_hours(ts, settings.alert_cooldown_hours))
            payload = json.dumps(
                {
                    "title": c.q.title,
                    "url": c.q.url,
                    "price": c.q.price,
                    "drop_prev": c.metrics.drop_prev,
                    "drop_7d": c.metrics.drop_7d,
                    "drop_30d": c.metrics.drop_30d,
                    "final_score": c.final_score,
                    "preference_tags": c.preference_tags,
                },
                ensure_ascii=True,
            )
            reason = (
                f"score={c.metrics.deal_score:.1f}, final={c.final_score:.1f}, prev={c.metrics.drop_prev:.1%}, "
                f"7d={c.metrics.drop_7d:.1%}, 30d={c.metrics.drop_30d:.1%}, near_low={c.metrics.near_low}, "
                f"pref={c.preference_reason or '-'}"
            )
            db.execute(
                settings.sqlite_path,
                """
                INSERT INTO alerts(ts_kst, product_id, deal_score, reason, payload_json, cooldown_until_kst)
                VALUES (?,?,?,?,?,?)
                """,
                (ts_iso, c.q.product_id, float(c.final_score), reason, payload, cooldown_until),
            )
            alerted += 1

        if (
            alerted == 0
            and settings.tracker_digest_enabled
            and near_candidates
            and _should_send_digest(settings.sqlite_path, ts, settings.tracker_digest_min_interval_min)
        ):
            near_candidates.sort(
                key=lambda c: (c.final_score, c.metrics.drop_prev, c.metrics.drop_7d, c.q.review_count),
                reverse=True,
            )
            notifier.send(_format_near_digest(ts, near_candidates, limit=5))
            _set_state(settings.sqlite_path, "tracker_digest_last_sent_kst", ts_iso, ts_iso)

        db.executemany(
            settings.sqlite_path,
            "UPDATE watchlist SET last_checked_kst=? WHERE product_id=?",
            last_checked_rows,
        )
        db.executemany(
            settings.sqlite_path,
            """
            INSERT OR REPLACE INTO deal_snapshots(
              ts_kst, product_id, deal_score, drop_prev, drop_7d, drop_30d, near_low, reliability
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            snapshot_rows,
        )
        db.execute(
            settings.sqlite_path,
            "INSERT INTO tracking_runs(ts_kst, checked, alerted, note) VALUES (?,?,?,?)",
            (
                ts_iso,
                checked,
                alerted,
                f"targets={len(targets)}, observed={len(observed)}, cand={len(alert_candidates)}, near={len(near_candidates)}",
            ),
        )

        logger.info("tracker done: targets=%s checked=%s alerts=%s observed=%s", len(targets), checked, alerted, len(observed))
        return 0
    except Exception as exc:
        stack = "\n".join(traceback.format_exc().splitlines()[-5:])
        notifier.send(f"[hotdeal_bot] tracker error\n{type(exc).__name__}: {exc}\n{stack}")
        logger.exception("tracker failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
