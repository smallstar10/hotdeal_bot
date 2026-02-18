from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import db
from src.core.config import load_settings


def main() -> int:
    settings = load_settings()
    db.init_db(settings.sqlite_path)
    print(f"initialized db: {settings.sqlite_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

