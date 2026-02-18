from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import db
from src.core.config import load_settings
from src.core.keywords import ensure_default_keywords, list_active_keywords
from src.core.logger import get_logger
from src.core.timeutil import kst_text, now_kst
from src.jobs.common import dedupe_quotes, insert_price_if_needed, trim_watchlist, upsert_product, upsert_watchlist
from src.notify.formatters import format_discovery_summary_with_items
from src.notify.telegram_notify import TelegramNotifier
from src.providers import load_provider
from src.providers.base import ProductQuote

logger = get_logger(__name__)


def _load_tracked_examples(sqlite_path: str, n: int = 5) -> list[ProductQuote]:
    rows = db.fetchall(
        sqlite_path,
        """
        SELECT p.product_id, p.title, p.url, p.image_url, p.category, p.rating, p.review_count, p.source_keyword,
               COALESCE(h.price, 0) AS price
        FROM products p
        JOIN watchlist w ON w.product_id = p.product_id AND w.active=1
        LEFT JOIN price_history h ON h.product_id = p.product_id
        WHERE h.ts_kst = (
          SELECT MAX(h2.ts_kst) FROM price_history h2 WHERE h2.product_id = p.product_id
        )
        ORDER BY w.priority DESC
        LIMIT ?
        """,
        (int(n),),
    )
    out: list[ProductQuote] = []
    for r in rows:
        out.append(
            ProductQuote(
                product_id=str(r["product_id"]),
                title=str(r["title"]),
                url=str(r["url"] or ""),
                image_url=str(r["image_url"] or ""),
                category=str(r["category"] or ""),
                price=float(r["price"] or 0.0),
                base_price=0.0,
                discount_rate=0.0,
                rating=float(r["rating"] or 0.0),
                review_count=int(r["review_count"] or 0),
                availability="IN_STOCK",
                source="db",
                keyword=str(r["source_keyword"] or ""),
            )
        )
    return out


def main() -> int:
    settings = load_settings()
    db.init_db(settings.sqlite_path)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    ts = now_kst()
    ts_iso = kst_text(ts)

    try:
        ensure_default_keywords(settings.sqlite_path, settings.discovery_keywords)
        keywords = list_active_keywords(settings.sqlite_path)
        if not keywords:
            logger.info("no active keywords configured, skip")
            notifier.send("[hotdeal_bot] 활성 키워드가 없습니다. 텔레그램에서 /키워드추가 <단어> 로 등록하세요.")
            return 0

        provider = load_provider(settings)
        total_fetched = 0
        total_inserted = 0
        inserted_examples: list[ProductQuote] = []

        for kw in keywords:
            quotes = dedupe_quotes(provider.search_products(kw, settings.discovery_limit_per_keyword))
            total_fetched += len(quotes)
            inserted = 0
            for q in quotes:
                if q.price <= 0:
                    continue
                upsert_product(settings.sqlite_path, q, ts_iso)
                upsert_watchlist(settings.sqlite_path, q)
                if insert_price_if_needed(settings.sqlite_path, q, ts_iso, settings.min_record_interval_min):
                    inserted += 1
                    if len(inserted_examples) < 8:
                        inserted_examples.append(q)
            total_inserted += inserted
            db.execute(
                settings.sqlite_path,
                """
                INSERT INTO discovery_runs(ts_kst, keyword, fetched, inserted, note)
                VALUES (?,?,?,?,?)
                """,
                (ts_iso, kw, len(quotes), inserted, "ok"),
            )

        # Algumon keyword match can be sparse. Fallback to top rank once when no priced insert happened.
        if settings.data_provider == "algumon_rank" and total_inserted == 0:
            fallback_quotes = dedupe_quotes(provider.search_products("", settings.discovery_limit_per_keyword))
            inserted = 0
            for q in fallback_quotes:
                if q.price <= 0:
                    continue
                upsert_product(settings.sqlite_path, q, ts_iso)
                upsert_watchlist(settings.sqlite_path, q)
                if insert_price_if_needed(settings.sqlite_path, q, ts_iso, settings.min_record_interval_min):
                    inserted += 1
                    if len(inserted_examples) < 8:
                        inserted_examples.append(q)
            total_fetched += len(fallback_quotes)
            total_inserted += inserted
            db.execute(
                settings.sqlite_path,
                """
                INSERT INTO discovery_runs(ts_kst, keyword, fetched, inserted, note)
                VALUES (?,?,?,?,?)
                """,
                (ts_iso, "__fallback_all__", len(fallback_quotes), inserted, "algumon-fallback"),
            )

        trim_watchlist(settings.sqlite_path, settings.max_tracked_products)
        tracked = db.fetchone(
            settings.sqlite_path,
            "SELECT COUNT(*) AS n FROM watchlist WHERE active=1",
        )
        tracked_n = int(tracked["n"]) if tracked else 0

        display_items = inserted_examples if inserted_examples else _load_tracked_examples(settings.sqlite_path, 5)
        msg = format_discovery_summary_with_items(ts, total_fetched, total_inserted, tracked_n, display_items)
        notifier.send(msg)
        logger.info("discovery done: fetched=%s inserted=%s tracked=%s", total_fetched, total_inserted, tracked_n)
        return 0
    except Exception as exc:
        stack = "\n".join(traceback.format_exc().splitlines()[-5:])
        notifier.send(f"[hotdeal_bot] discovery error\n{type(exc).__name__}: {exc}\n{stack}")
        logger.exception("discovery failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
