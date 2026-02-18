from __future__ import annotations

import hashlib
import re
import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.core.config import Settings
from src.providers.base import DealProvider, ProductQuote


def _to_price_krw(price_text: str) -> float:
    # Prefer KRW pattern: "70,022원"
    m = re.findall(r"([0-9][0-9,]{2,})\s*원", price_text)
    if m:
        return float(m[-1].replace(",", ""))
    # Fallback numeric extraction (e.g. "$47.99", "129.9", "12,500").
    m2 = re.findall(r"[0-9][0-9,]*(?:\\.[0-9]+)?", price_text)
    if m2:
        try:
            return float(m2[-1].replace(",", ""))
        except Exception:
            return 0.0
    return 0.0


def _price_from_title(title: str) -> float:
    # e.g. "... 79,900원 ..."
    m = re.findall(r"([0-9][0-9,]{2,})\s*원", title)
    if m:
        return float(m[-1].replace(",", ""))
    return 0.0


class AlgumonRankProvider(DealProvider):
    """
    Public web ranking provider (non-official API).
    - Pulls latest ranked deals from algumon rank page.
    - Filters by keyword on title.
    """

    def __init__(self, settings: Settings):
        self.rank_url = settings.algumon_rank_url
        self.session = requests.Session()
        self._cache_ts: float = 0.0
        self._cache_quotes: list[ProductQuote] = []

    @staticmethod
    def _fallback_id(title: str, url: str) -> str:
        return hashlib.sha1(f"{title}|{url}".encode("utf-8")).hexdigest()[:20]

    def _fetch_rank_quotes(self) -> list[ProductQuote]:
        # Cache for a short time to avoid repeated fetch in multi-keyword discovery loops.
        now = time.time()
        if now - self._cache_ts < 45 and self._cache_quotes:
            return self._cache_quotes

        resp = self.session.get(
            self.rank_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=12,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        out: list[ProductQuote] = []
        for a in soup.select("p.deal-title a.product-link"):
            title = a.get_text(strip=True)
            if not title:
                continue
            href = str(a.get("href") or "").strip()
            url = urljoin(self.rank_url, href) if href else self.rank_url
            pid = str(a.get("data-product") or "").strip()
            if not pid:
                pid = self._fallback_id(title, url)

            site = str(a.get("data-site") or "").strip()
            host = "algumon"
            if site:
                host = f"algumon:{site}"

            title_p = a.find_parent("p", class_="deal-title")
            price_text = ""
            meta_text = ""
            body = title_p.find_parent("div", class_="product-body") if title_p is not None else None
            if body is not None:
                price_p = body.select_one("p.deal-price-info")
                if price_p is not None:
                    price_text = price_p.get_text(" ", strip=True)
                meta_p = body.select_one("small.deal-price-meta-info")
                if meta_p is not None:
                    meta_text = meta_p.get_text(" ", strip=True)

            price = _to_price_krw(price_text)
            if price <= 0.0:
                price = _price_from_title(title)
            discount_rate = 0.0
            # Optional parse like "xx%".
            disc_match = re.search(r"([0-9]{1,2})\s*%", price_text)
            if disc_match:
                discount_rate = max(0.0, min(0.95, float(disc_match.group(1)) / 100.0))

            availability = "OUT_OF_STOCK" if ("품절" in title or "품절" in meta_text) else "IN_STOCK"
            out.append(
                ProductQuote(
                    product_id=pid,
                    title=title,
                    url=url,
                    image_url="",
                    category=site,
                    price=price,
                    base_price=0.0,
                    discount_rate=discount_rate,
                    rating=0.0,
                    review_count=0,
                    availability=availability,
                    source=host,
                    keyword="",
                )
            )

        self._cache_quotes = out
        self._cache_ts = now
        return out

    def search_products(self, keyword: str, limit: int) -> list[ProductQuote]:
        quotes = self._fetch_rank_quotes()
        keyword_norm = keyword.strip().lower()
        if keyword_norm:
            quotes = [q for q in quotes if keyword_norm in q.title.lower()]
        max_n = max(1, min(int(limit), 200))
        clipped = quotes[:max_n]
        return [ProductQuote(**(q.__dict__ | {"keyword": keyword_norm})) for q in clipped]
