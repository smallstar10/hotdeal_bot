from __future__ import annotations

from src.core.config import Settings
from src.providers.algumon_rank import AlgumonRankProvider
from src.providers.base import DealProvider
from src.providers.coupang_affiliate import CoupangAffiliateProvider


def load_provider(settings: Settings) -> DealProvider:
    if settings.data_provider == "algumon_rank":
        return AlgumonRankProvider(settings)
    if settings.data_provider == "coupang_affiliate":
        return CoupangAffiliateProvider(settings)
    raise ValueError(f"unsupported provider: {settings.data_provider}")
