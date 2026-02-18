from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import load_settings
from src.providers import load_provider


def main() -> int:
    settings = load_settings()
    provider = load_provider(settings)
    for kw in settings.discovery_keywords[:2]:
        items = provider.search_products(kw, min(5, settings.discovery_limit_per_keyword))
        print(f"keyword={kw} items={len(items)}")
        for x in items[:3]:
            print(f"- {x.product_id} | {x.title[:50]} | {x.price} | {x.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

