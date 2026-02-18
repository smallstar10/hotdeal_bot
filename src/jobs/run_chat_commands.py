from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import db
from src.core.config import load_settings
from src.core.keywords import add_keyword, ensure_default_keywords, list_active_keywords, remove_keyword
from src.core.logger import get_logger
from src.core.timeutil import kst_text, now_kst
from src.notify.telegram_notify import TelegramNotifier

logger = get_logger(__name__)


HELP_TEXT = (
    "사용 가능한 명령어\n"
    "/키워드목록\n"
    "/키워드추가 <단어>\n"
    "/키워드삭제 <단어>\n"
    "/최근\n"
    "/상태\n"
    "/도움말"
)


def _state_get(sqlite_path: str, key: str, default: str = "") -> str:
    row = db.fetchone(sqlite_path, "SELECT value FROM bot_state WHERE key=?", (key,))
    if row is None:
        return default
    return str(row["value"])


def _state_set(sqlite_path: str, key: str, value: str) -> None:
    db.execute(
        sqlite_path,
        """
        INSERT INTO bot_state(key, value, updated_ts_kst)
        VALUES (?,?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts_kst=excluded.updated_ts_kst
        """,
        (key, value, kst_text()),
    )


def _recent_items(sqlite_path: str, n: int = 5) -> list[dict]:
    rows = db.fetchall(
        sqlite_path,
        """
        SELECT p.product_id, p.title, p.url, p.source_keyword,
               h.price, h.ts_kst,
               COALESCE(s.deal_score, 0) AS deal_score
        FROM products p
        JOIN watchlist w ON w.product_id = p.product_id AND w.active=1
        LEFT JOIN price_history h ON h.product_id = p.product_id
        LEFT JOIN deal_snapshots s ON s.product_id = p.product_id
        WHERE h.ts_kst = (
          SELECT MAX(h2.ts_kst) FROM price_history h2 WHERE h2.product_id = p.product_id
        )
        GROUP BY p.product_id
        ORDER BY deal_score DESC, h.ts_kst DESC
        LIMIT ?
        """,
        (int(n),),
    )
    return [dict(r) for r in rows]


def _build_status(sqlite_path: str) -> str:
    kw = db.fetchone(sqlite_path, "SELECT COUNT(*) AS n FROM keyword_rules WHERE active=1")
    tracked = db.fetchone(sqlite_path, "SELECT COUNT(*) AS n FROM watchlist WHERE active=1")
    alerts = db.fetchone(sqlite_path, "SELECT COUNT(*) AS n FROM alerts WHERE ts_kst >= datetime('now', '-1 day')")
    return (
        "[hotdeal_bot 상태]\n"
        f"활성 키워드: {int(kw['n']) if kw else 0}\n"
        f"추적 상품: {int(tracked['n']) if tracked else 0}\n"
        f"최근24h 알림: {int(alerts['n']) if alerts else 0}"
    )


def _parse_keyword_arg(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _handle_message(sqlite_path: str, text: str) -> str | None:
    txt = text.strip()
    if not txt:
        return None

    if txt.startswith("/도움말") or txt.startswith("/help") or txt.startswith("/start"):
        return HELP_TEXT

    if txt.startswith("/키워드목록"):
        kws = list_active_keywords(sqlite_path)
        if not kws:
            return "활성 키워드가 없습니다."
        return "활성 키워드\n- " + "\n- ".join(kws[:40])

    if txt.startswith("/키워드추가") or txt.lower().startswith("키워드 추가"):
        kw = _parse_keyword_arg(txt.replace("키워드 추가", "/키워드추가", 1))
        if not kw:
            return "사용법: /키워드추가 <단어>"
        ok = add_keyword(sqlite_path, kw, source="chat")
        if not ok:
            return "키워드가 비어 있습니다."
        return f"추가 완료: {kw}"

    if txt.startswith("/키워드삭제") or txt.lower().startswith("키워드 삭제"):
        kw = _parse_keyword_arg(txt.replace("키워드 삭제", "/키워드삭제", 1))
        if not kw:
            return "사용법: /키워드삭제 <단어>"
        ok = remove_keyword(sqlite_path, kw)
        if not ok:
            return f"삭제 실패(미등록): {kw}"
        return f"삭제 완료: {kw}"

    if txt.startswith("/최근"):
        items = _recent_items(sqlite_path, n=5)
        if not items:
            return "최근 추적 상품이 없습니다."
        lines = ["최근 추적 상품 TOP 5"]
        for i, it in enumerate(items, start=1):
            price = float(it.get("price") or 0.0)
            lines.append(f"{i}) {str(it.get('title',''))[:42]} | {int(price):,}원 | score {float(it.get('deal_score') or 0.0):.1f}")
        return "\n".join(lines)

    if txt.startswith("/상태"):
        return _build_status(sqlite_path)

    return None


def main() -> int:
    settings = load_settings()
    db.init_db(settings.sqlite_path)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    ensure_default_keywords(settings.sqlite_path, settings.discovery_keywords)

    try:
        offset_txt = _state_get(settings.sqlite_path, "telegram_offset", "0")
        try:
            offset = int(offset_txt)
        except Exception:
            offset = 0

        updates = notifier.get_updates(offset=offset + 1, limit=50, timeout=1)
        if not updates:
            return 0

        max_update_id = offset
        allow_chat = str(settings.telegram_chat_id).strip()
        for u in updates:
            uid = int(u.get("update_id") or 0)
            max_update_id = max(max_update_id, uid)

            msg = u.get("message") or {}
            chat = msg.get("chat") or {}
            chat_id = str(chat.get("id") or "")
            if allow_chat and chat_id != allow_chat:
                continue
            text = str(msg.get("text") or "").strip()
            if not text:
                continue

            reply = _handle_message(settings.sqlite_path, text)
            if reply:
                notifier.send(reply)

        _state_set(settings.sqlite_path, "telegram_offset", str(max_update_id))
        return 0
    except Exception as exc:
        stack = "\n".join(traceback.format_exc().splitlines()[-5:])
        notifier.send(f"[hotdeal_bot] chat-command error\n{type(exc).__name__}: {exc}\n{stack}")
        logger.exception("chat-command failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

