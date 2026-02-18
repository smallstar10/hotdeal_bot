from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProductQuote:
    product_id: str
    title: str
    url: str
    image_url: str
    category: str
    price: float
    base_price: float
    discount_rate: float
    rating: float
    review_count: int
    availability: str
    source: str
    keyword: str


class DealProvider(ABC):
    @abstractmethod
    def search_products(self, keyword: str, limit: int) -> list[ProductQuote]:
        raise NotImplementedError

