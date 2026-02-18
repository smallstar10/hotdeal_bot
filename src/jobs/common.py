from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.core import db
from src.providers.base import ProductQuote
from src.scoring.deal_score import calc_watch_priority

KST = ZoneInfo("Asia/Seoul")


def _parse_kst_text(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except Exception:
        try:
            return datetime.fromisoformat(value).astimezone(KST)
        except Exception:
            return None


def dedupe_quotes(quotes: list[ProductQuote]) -> list[ProductQuote]:
    seen: dict[str, ProductQuote] = {}
    for q in quotes:
        prev = seen.get(q.product_id)
        if prev is None:
            seen[q.product_id] = q
            continue
        if q.price > 0 and (prev.price <= 0 or q.price < prev.price):
            seen[q.product_id] = q
    return list(seen.values())


def upsert_product(sqlite_path: str, q: ProductQuote, ts_iso: str) -> None:
    db.execute(
        sqlite_path,
        """
        INSERT INTO products(
            product_id, title, url, image_url, category, rating, review_count,
            source_keyword, first_seen_kst, last_seen_kst, active
        ) VALUES (?,?,?,?,?,?,?,?,?,?,1)
        ON CONFLICT(product_id) DO UPDATE SET
            title=excluded.title,
            url=excluded.url,
            image_url=excluded.image_url,
            category=excluded.category,
            rating=excluded.rating,
            review_count=excluded.review_count,
            source_keyword=excluded.source_keyword,
            last_seen_kst=excluded.last_seen_kst,
            active=1
        """,
        (
            q.product_id,
            q.title,
            q.url,
            q.image_url,
            q.category,
            float(q.rating),
            int(q.review_count),
            q.keyword,
            ts_iso,
            ts_iso,
        ),
    )


def upsert_watchlist(sqlite_path: str, q: ProductQuote) -> None:
    priority = calc_watch_priority(q.discount_rate, q.review_count, q.rating)
    reason = f"discount={q.discount_rate:.2%}, reviews={q.review_count}, rating={q.rating:.2f}"
    db.execute(
        sqlite_path,
        """
        INSERT INTO watchlist(product_id, priority, reason, last_checked_kst, active)
        VALUES (?,?,?,?,1)
        ON CONFLICT(product_id) DO UPDATE SET
            priority=excluded.priority,
            reason=excluded.reason,
            active=1
        """,
        (q.product_id, float(priority), reason, None),
    )


def trim_watchlist(sqlite_path: str, max_tracked_products: int) -> None:
    db.execute(
        sqlite_path,
        """
        UPDATE watchlist
        SET active=0
        WHERE product_id IN (
          SELECT product_id
          FROM watchlist
          WHERE active=1
          ORDER BY priority DESC, product_id ASC
          LIMIT -1 OFFSET ?
        )
        """,
        (int(max_tracked_products),),
    )


def insert_price_if_needed(sqlite_path: str, q: ProductQuote, ts_iso: str, min_record_interval_min: int) -> bool:
    row = db.fetchone(
        sqlite_path,
        """
        SELECT ts_kst, price
        FROM price_history
        WHERE product_id=?
        ORDER BY ts_kst DESC
        LIMIT 1
        """,
        (q.product_id,),
    )
    if row is not None:
        prev_ts = _parse_kst_text(str(row["ts_kst"]))
        if prev_ts is not None:
            now_ts = _parse_kst_text(ts_iso)
            if now_ts is None:
                now_ts = prev_ts
            if now_ts - prev_ts < timedelta(minutes=int(min_record_interval_min)):
                if abs(float(row["price"]) - float(q.price)) < 0.5:
                    return False

    db.execute(
        sqlite_path,
        """
        INSERT OR IGNORE INTO price_history(
            product_id, ts_kst, price, base_price, discount_rate, availability, source
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            q.product_id,
            ts_iso,
            float(q.price),
            float(q.base_price),
            float(q.discount_rate),
            q.availability,
            q.source,
        ),
    )
    return True


def product_price_series(sqlite_path: str, product_id: str, days: int = 30) -> list[float]:
    rows = db.fetchall(
        sqlite_path,
        """
        SELECT price
        FROM price_history
        WHERE product_id=?
          AND ts_kst >= datetime('now', ?)
        ORDER BY ts_kst ASC
        """,
        (product_id, f"-{int(days)} day"),
    )
    return [float(r["price"]) for r in rows]


def in_cooldown(sqlite_path: str, product_id: str, now_iso: str) -> bool:
    row = db.fetchone(
        sqlite_path,
        """
        SELECT 1 AS hit
        FROM alerts
        WHERE product_id=?
          AND cooldown_until_kst > ?
        ORDER BY alert_id DESC
        LIMIT 1
        """,
        (product_id, now_iso),
    )
    return row is not None
