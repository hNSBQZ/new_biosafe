"""Read-only RAGFlow contract probe; never prints response data or credentials."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biosafe.config import Settings  # noqa: E402
from biosafe.integrations.ragflow import RAGFlowClient  # noqa: E402


async def main() -> int:
    settings = Settings.from_env()
    if not settings.ragflow.ready:
        print(json.dumps({"ok": False, "reason": "RAGFlow is not configured"}))
        return 2
    async with RAGFlowClient(settings.ragflow) as client:
        datasets = await client.list_datasets()
    methods = sorted({dataset.chunk_method for dataset in datasets})
    print(json.dumps({"ok": True, "dataset_count": len(datasets), "chunk_methods": methods}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
