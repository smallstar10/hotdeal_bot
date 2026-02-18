from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def kst_iso(dt: datetime | None = None) -> str:
    target = dt or now_kst()
    return target.isoformat(timespec="seconds")


def kst_text(dt: datetime | None = None) -> str:
    target = dt or now_kst()
    return target.strftime("%Y-%m-%d %H:%M:%S")


def kst_add_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(hours=hours)
