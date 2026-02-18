from __future__ import annotations

from src.core import db
from src.core.timeutil import kst_text


def ensure_default_keywords(sqlite_path: str, defaults: list[str]) -> None:
    ts = kst_text()
    rows = []
    for kw in defaults:
        kw = kw.strip()
        if not kw:
            continue
        rows.append((kw, 1, "env", ts, None))
    if not rows:
        return
    db.executemany(
        sqlite_path,
        """
        INSERT OR IGNORE INTO keyword_rules(keyword, active, source, added_ts_kst, removed_ts_kst)
        VALUES (?,?,?,?,?)
        """,
        rows,
    )


def list_active_keywords(sqlite_path: str) -> list[str]:
    rows = db.fetchall(
        sqlite_path,
        """
        SELECT keyword
        FROM keyword_rules
        WHERE active=1
        ORDER BY keyword ASC
        """,
    )
    return [str(r["keyword"]) for r in rows]


def add_keyword(sqlite_path: str, keyword: str, source: str = "chat") -> bool:
    kw = keyword.strip()
    if not kw:
        return False
    ts = kst_text()
    db.execute(
        sqlite_path,
        """
        INSERT INTO keyword_rules(keyword, active, source, added_ts_kst, removed_ts_kst)
        VALUES (?,?,?,?,NULL)
        ON CONFLICT(keyword) DO UPDATE SET
          active=1,
          source=excluded.source,
          removed_ts_kst=NULL
        """,
        (kw, 1, source, ts),
    )
    return True


def remove_keyword(sqlite_path: str, keyword: str) -> bool:
    kw = keyword.strip()
    if not kw:
        return False
    ts = kst_text()
    row = db.fetchone(sqlite_path, "SELECT keyword FROM keyword_rules WHERE keyword=?", (kw,))
    if row is None:
        return False
    db.execute(
        sqlite_path,
        "UPDATE keyword_rules SET active=0, removed_ts_kst=? WHERE keyword=?",
        (ts, kw),
    )
    return True

