"""Import local historical Excel data without publishing it to RAGFlow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biosafe.config import Settings  # noqa: E402
from biosafe.storage import Database, HistoryRepository  # noqa: E402
from biosafe.storage.seed_importer import import_excel  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("excel", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.migrate()
    stats = import_excel(args.excel, HistoryRepository(database))
    print(json.dumps({"added": stats.added, "skipped": stats.skipped, "errors": stats.errors}))
    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
