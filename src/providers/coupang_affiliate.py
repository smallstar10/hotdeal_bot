from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from src.core.config import Settings
from src.providers.base import DealProvider, ProductQuote


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


class CoupangAffiliateProvider(DealProvider):
    """
    Provider using Coupang affiliate open API.
    Notes:
      - Requires Access Key / Secret Key.
      - Endpoint path is configurable via COUPANG_SEARCH_PATH for compatibility.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.coupang_base_url.rstrip("/")
        self.search_path = settings.coupang_search_path
        self.access_key = settings.coupang_access_key
        self.secret_key = settings.coupang_secret_key
        if not self.access_key or not self.secret_key:
            raise ValueError("COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY are required for coupang_affiliate provider")
        self.session = requests.Session()

    @staticmethod
    def _signed_date() -> str:
        return datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")

    def _auth_header(self, method: str, path: str, query: str, signed_date: str) -> str:
        msg = f"{signed_date}{method}{path}{query}"
        sig = hmac.new(self.secret_key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"CEA algorithm=HmacSHA256, access-key={self.access_key}, signed-date={signed_date}, signature={sig}"

    def _request_json(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode(params, doseq=True)
        signed_date = self._signed_date()
        headers = {
            "Authorization": self._auth_header(method, path, query, signed_date),
            "Content-Type": "application/json;charset=UTF-8",
        }
        url = f"{self.base_url}{path}"
        last_err: Exception | None = None
        for i in range(3):
            try:
                resp = self.session.request(method, url, params=params, headers=headers, timeout=12)
                resp.raise_for_status()
                return resp.json() if resp.text else {}
            except Exception as exc:
                last_err = exc
                time.sleep(0.6 * (i + 1))
        raise RuntimeError(f"coupang api failed: {last_err}")

    def _extract_items(self, obj: Any) -> list[dict[str, Any]]:
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        if isinstance(obj, dict):
            # Common response envelopes.
            for key in ("data", "products", "productData", "items"):
                if key in obj and isinstance(obj[key], list):
                    return [x for x in obj[key] if isinstance(x, dict)]
            for key in ("data", "result"):
                if key in obj and isinstance(obj[key], dict):
                    nested = self._extract_items(obj[key])
                    if nested:
                        return nested
        return []

    @staticmethod
    def _fallback_id(item: dict[str, Any], title: str, url: str) -> str:
        raw = f"{title}|{url}|{item.get('productId','')}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

    def _parse_quote(self, item: dict[str, Any], keyword: str) -> ProductQuote | None:
        title = str(item.get("productName") or item.get("title") or item.get("name") or "").strip()
        url = str(item.get("productUrl") or item.get("url") or item.get("productLink") or "").strip()
        if not title:
            return None
        pid_raw = item.get("productId") or item.get("product_id") or item.get("id")
        product_id = str(pid_raw).strip() if pid_raw else self._fallback_id(item, title, url)
        price = _to_float(item.get("price") or item.get("salePrice") or item.get("finalPrice"), 0.0)
        base_price = _to_float(item.get("originalPrice") or item.get("basePrice") or item.get("listPrice"), 0.0)
        discount_rate = _to_float(item.get("discountRate"), 0.0)
        if discount_rate <= 0.0 and base_price > 0 and price > 0:
            discount_rate = (base_price - price) / base_price
        rating = _to_float(item.get("rating") or item.get("starRating"), 0.0)
        review_count = _to_int(item.get("reviewCount") or item.get("ratingCount") or item.get("reviewCnt"), 0)
        image_url = str(item.get("productImage") or item.get("imageUrl") or "").strip()
        category = str(item.get("categoryName") or item.get("category") or "").strip()

        is_out = str(item.get("isOutOfStock") or "").lower() in ("true", "1", "y")
        availability = "OUT_OF_STOCK" if is_out else "IN_STOCK"
        return ProductQuote(
            product_id=product_id,
            title=title,
            url=url,
            image_url=image_url,
            category=category,
            price=price,
            base_price=base_price,
            discount_rate=discount_rate,
            rating=rating,
            review_count=review_count,
            availability=availability,
            source="coupang_affiliate_api",
            keyword=keyword,
        )

    def search_products(self, keyword: str, limit: int) -> list[ProductQuote]:
        params = {"keyword": keyword, "limit": max(1, min(limit, 100))}
        payload = self._request_json("GET", self.search_path, params)
        items = self._extract_items(payload)
        out: list[ProductQuote] = []
        for item in items:
            q = self._parse_quote(item, keyword)
            if q is None:
                continue
            if q.price <= 0:
                continue
            out.append(q)
        return out

