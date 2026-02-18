from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from src.core.config import ensure_parent_dir


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
  product_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT,
  image_url TEXT,
  category TEXT,
  rating REAL,
  review_count INTEGER,
  source_keyword TEXT,
  first_seen_kst TEXT NOT NULL,
  last_seen_kst TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_history (
  hist_id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id TEXT NOT NULL,
  ts_kst TEXT NOT NULL,
  price REAL NOT NULL,
  base_price REAL,
  discount_rate REAL,
  availability TEXT,
  source TEXT,
  UNIQUE(product_id, ts_kst)
);

CREATE TABLE IF NOT EXISTS watchlist (
  product_id TEXT PRIMARY KEY,
  priority REAL NOT NULL,
  reason TEXT,
  last_checked_kst TEXT,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS discovery_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_kst TEXT NOT NULL,
  keyword TEXT NOT NULL,
  fetched INTEGER NOT NULL,
  inserted INTEGER NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS tracking_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_kst TEXT NOT NULL,
  checked INTEGER NOT NULL,
  alerted INTEGER NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS deal_snapshots (
  ts_kst TEXT NOT NULL,
  product_id TEXT NOT NULL,
  deal_score REAL NOT NULL,
  drop_prev REAL NOT NULL,
  drop_7d REAL NOT NULL,
  drop_30d REAL NOT NULL,
  near_low INTEGER NOT NULL,
  reliability REAL NOT NULL,
  PRIMARY KEY (ts_kst, product_id)
);

CREATE TABLE IF NOT EXISTS alerts (
  alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_kst TEXT NOT NULL,
  product_id TEXT NOT NULL,
  deal_score REAL NOT NULL,
  reason TEXT NOT NULL,
  payload_json TEXT,
  cooldown_until_kst TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keyword_rules (
  keyword TEXT PRIMARY KEY,
  active INTEGER NOT NULL,
  source TEXT NOT NULL,
  added_ts_kst TEXT NOT NULL,
  removed_ts_kst TEXT
);

CREATE TABLE IF NOT EXISTS bot_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_ts_kst TEXT NOT NULL
);
"""


@contextmanager
def get_conn(sqlite_path: str):
    ensure_parent_dir(sqlite_path)
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def init_db(sqlite_path: str) -> None:
    with get_conn(sqlite_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def execute(sqlite_path: str, query: str, params: Iterable[Any] = ()) -> int:
    with get_conn(sqlite_path) as conn:
        cur = conn.execute(query, tuple(params))
        conn.commit()
        return cur.lastrowid


def executemany(sqlite_path: str, query: str, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    with get_conn(sqlite_path) as conn:
        conn.executemany(query, rows)
        conn.commit()


def fetchone(sqlite_path: str, query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with get_conn(sqlite_path) as conn:
        cur = conn.execute(query, tuple(params))
        return cur.fetchone()


def fetchall(sqlite_path: str, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with get_conn(sqlite_path) as conn:
        cur = conn.execute(query, tuple(params))
        return cur.fetchall()
