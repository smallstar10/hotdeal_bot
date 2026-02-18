from __future__ import annotations

import math
from dataclasses import dataclass


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class DealMetrics:
    current: float
    prev: float
    avg_7d: float
    avg_30d: float
    min_30d: float
    drop_prev: float
    drop_7d: float
    drop_30d: float
    near_low: int
    reliability: float
    deal_score: float


def calc_deal_metrics(
    prices_asc: list[float],
    review_count: int,
    rating: float,
    near_low_band: float = 1.03,
) -> DealMetrics:
    clean = [float(x) for x in prices_asc if x and x > 0]
    if not clean:
        clean = [0.0]

    current = clean[-1]
    prev = clean[-2] if len(clean) >= 2 else current
    recent_7 = clean[-7:] if len(clean) >= 7 else clean
    recent_30 = clean[-30:] if len(clean) >= 30 else clean
    avg_7d = sum(recent_7) / max(1, len(recent_7))
    avg_30d = sum(recent_30) / max(1, len(recent_30))
    min_30d = min(recent_30) if recent_30 else current

    drop_prev = (prev - current) / prev if prev > 0 else 0.0
    drop_7d = (avg_7d - current) / avg_7d if avg_7d > 0 else 0.0
    drop_30d = (avg_30d - current) / avg_30d if avg_30d > 0 else 0.0
    near_low = 1 if (min_30d > 0 and current <= min_30d * near_low_band) else 0

    reliability_reviews = _clip(math.log1p(max(0, int(review_count))) / 8.0, 0.0, 1.0)
    reliability_rating = _clip(float(rating) / 5.0, 0.0, 1.0)
    reliability = 0.6 * reliability_reviews + 0.4 * reliability_rating

    score = 0.0
    score += 0.36 * _clip(drop_prev / 0.25, 0.0, 1.0)
    score += 0.24 * _clip(drop_7d / 0.30, 0.0, 1.0)
    score += 0.20 * _clip(drop_30d / 0.35, 0.0, 1.0)
    score += 0.10 * float(near_low)
    score += 0.10 * reliability
    deal_score = _clip(score, 0.0, 1.0) * 100.0

    return DealMetrics(
        current=current,
        prev=prev,
        avg_7d=avg_7d,
        avg_30d=avg_30d,
        min_30d=min_30d,
        drop_prev=drop_prev,
        drop_7d=drop_7d,
        drop_30d=drop_30d,
        near_low=near_low,
        reliability=reliability,
        deal_score=deal_score,
    )


def calc_watch_priority(discount_rate: float, review_count: int, rating: float) -> float:
    d = _clip(discount_rate, 0.0, 0.8) / 0.8
    r = _clip(math.log1p(max(0, int(review_count))) / 8.0, 0.0, 1.0)
    s = _clip(float(rating) / 5.0, 0.0, 1.0)
    return 100.0 * (0.55 * d + 0.30 * r + 0.15 * s)

