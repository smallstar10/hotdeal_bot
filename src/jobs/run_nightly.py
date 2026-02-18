from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import db
from src.core.config import load_settings
from src.core.logger import get_logger
from src.core.timeutil import kst_text, now_kst
from src.notify.formatters import format_nightly_summary
from src.notify.telegram_notify import TelegramNotifier

logger = get_logger(__name__)


def main() -> int:
    settings = load_settings()
    db.init_db(settings.sqlite_path)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    ts = now_kst()
    ts_iso = kst_text(ts)

    try:
        db.execute(
            settings.sqlite_path,
            """
            DELETE FROM price_history
            WHERE ts_kst < datetime('now', ?)
            """,
            (f"-{int(settings.history_retention_days)} day",),
        )
        db.execute(
            settings.sqlite_path,
            """
            UPDATE watchlist
            SET active=0
            WHERE product_id IN (
              SELECT w.product_id
              FROM watchlist w
              JOIN products p ON p.product_id = w.product_id
              WHERE p.last_seen_kst < datetime('now', '-45 day')
            )
            """,
        )
        db.execute(
            settings.sqlite_path,
            """
            INSERT INTO tracking_runs(ts_kst, checked, alerted, note)
            VALUES (?,?,?,?)
            """,
            (ts_iso, 0, 0, "nightly-maintenance"),
        )

        tracked = db.fetchone(settings.sqlite_path, "SELECT COUNT(*) AS n FROM watchlist WHERE active=1")
        hist = db.fetchone(settings.sqlite_path, "SELECT COUNT(*) AS n FROM price_history")
        alerts = db.fetchone(
            settings.sqlite_path,
            "SELECT COUNT(*) AS n FROM alerts WHERE ts_kst >= datetime('now', '-1 day')",
        )
        msg = format_nightly_summary(
            ts,
            tracked=int(tracked["n"]) if tracked else 0,
            history_rows=int(hist["n"]) if hist else 0,
            alerts_24h=int(alerts["n"]) if alerts else 0,
        )
        notifier.send(msg)
        logger.info("nightly done")
        return 0
    except Exception as exc:
        stack = "\n".join(traceback.format_exc().splitlines()[-5:])
        notifier.send(f"[hotdeal_bot] nightly error\n{type(exc).__name__}: {exc}\n{stack}")
        logger.exception("nightly failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
