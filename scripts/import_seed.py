"""Import local historical Excel data without publishing it to RAGFlow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from biosafe.config import Settings
from biosafe.storage import Database, HistoryRepository
from biosafe.storage.seed_importer import import_excel


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
