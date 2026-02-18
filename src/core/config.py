from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    data_provider: str
    coupang_access_key: str
    coupang_secret_key: str
    coupang_base_url: str
    coupang_search_path: str
    algumon_rank_url: str
    discovery_keywords: list[str]
    discovery_limit_per_keyword: int
    track_batch_size: int
    track_limit_per_keyword: int
    max_tracked_products: int
    min_record_interval_min: int
    alert_score_min: float
    alert_cooldown_hours: int
    min_drop_prev: float
    min_drop_7d: float
    near_low_band: float
    sqlite_path: str
    history_retention_days: int
    preferred_food_keywords: list[str]
    preferred_event_keywords: list[str]
    food_bonus_per_hit: float
    event_bonus_per_hit: float
    preference_bonus_cap: float
    alert_preference_relax: float
    min_drop_30d_preferred: float
    alert_min_reviews: int
    min_reliability: float
    alert_max_per_run: int
    tracker_digest_enabled: bool
    tracker_digest_min_interval_min: int
    tracker_digest_score_margin: float
    tracker_observed_scan_limit: int


def _parse_csv(value: str) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _parse_bool(value: str, default: bool) -> bool:
    raw = (value or "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def load_settings() -> Settings:
    load_dotenv()
    keywords = _parse_csv(os.getenv("DISCOVERY_KEYWORDS", ""))
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        data_provider=os.getenv("DATA_PROVIDER", "coupang_affiliate").strip().lower(),
        coupang_access_key=os.getenv("COUPANG_ACCESS_KEY", ""),
        coupang_secret_key=os.getenv("COUPANG_SECRET_KEY", ""),
        coupang_base_url=os.getenv("COUPANG_BASE_URL", "https://api-gateway.coupang.com").rstrip("/"),
        coupang_search_path=os.getenv("COUPANG_SEARCH_PATH", "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"),
        algumon_rank_url=os.getenv("ALGUMON_RANK_URL", "https://www.algumon.com/deal/rank"),
        discovery_keywords=keywords,
        discovery_limit_per_keyword=int(os.getenv("DISCOVERY_LIMIT_PER_KEYWORD", "40")),
        track_batch_size=int(os.getenv("TRACK_BATCH_SIZE", "180")),
        track_limit_per_keyword=int(os.getenv("TRACK_LIMIT_PER_KEYWORD", "50")),
        max_tracked_products=int(os.getenv("MAX_TRACKED_PRODUCTS", "2000")),
        min_record_interval_min=int(os.getenv("MIN_RECORD_INTERVAL_MIN", "30")),
        alert_score_min=float(os.getenv("ALERT_SCORE_MIN", "72")),
        alert_cooldown_hours=int(os.getenv("ALERT_COOLDOWN_HOURS", "12")),
        min_drop_prev=float(os.getenv("MIN_DROP_PREV", "0.12")),
        min_drop_7d=float(os.getenv("MIN_DROP_7D", "0.18")),
        near_low_band=float(os.getenv("NEAR_LOW_BAND", "1.03")),
        sqlite_path=os.getenv("SQLITE_PATH", "data/hotdeal.db"),
        history_retention_days=int(os.getenv("HISTORY_RETENTION_DAYS", "120")),
        preferred_food_keywords=_parse_csv(
            os.getenv(
                "PREFERRED_FOOD_KEYWORDS",
                "식품,먹거리,라면,커피,생수,음료,쌀,과자,간식,닭가슴살,유제품,냉동,반찬,돈까스,아이스크림,만두,곰탕,오징어,펩시,제로,밥,컵밥,치즈",
            )
        ),
        preferred_event_keywords=_parse_csv(
            os.getenv(
                "PREFERRED_EVENT_KEYWORDS",
                "쿠폰,적립,캐시,캐시백,페이백,이벤트,1+1,사은품,증정,할인전,프로모션,카드할인",
            )
        ),
        food_bonus_per_hit=float(os.getenv("FOOD_BONUS_PER_HIT", "2.4")),
        event_bonus_per_hit=float(os.getenv("EVENT_BONUS_PER_HIT", "2.2")),
        preference_bonus_cap=float(os.getenv("PREFERENCE_BONUS_CAP", "12")),
        alert_preference_relax=float(os.getenv("ALERT_PREFERENCE_RELAX", "6")),
        min_drop_30d_preferred=float(os.getenv("MIN_DROP_30D_PREFERRED", "0.08")),
        alert_min_reviews=int(os.getenv("ALERT_MIN_REVIEWS", "8")),
        min_reliability=float(os.getenv("MIN_RELIABILITY", "0.18")),
        alert_max_per_run=int(os.getenv("ALERT_MAX_PER_RUN", "3")),
        tracker_digest_enabled=_parse_bool(os.getenv("TRACKER_DIGEST_ENABLED", "true"), True),
        tracker_digest_min_interval_min=int(os.getenv("TRACKER_DIGEST_MIN_INTERVAL_MIN", "60")),
        tracker_digest_score_margin=float(os.getenv("TRACKER_DIGEST_SCORE_MARGIN", "10")),
        tracker_observed_scan_limit=int(os.getenv("TRACKER_OBSERVED_SCAN_LIMIT", "30")),
    )


def ensure_parent_dir(path_str: str) -> None:
    Path(path_str).parent.mkdir(parents=True, exist_ok=True)
