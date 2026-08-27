"""Read-only RAGFlow contract probe; never prints response data or credentials."""

from __future__ import annotations

import asyncio
import json

from biosafe.config import Settings
from biosafe.integrations.ragflow import RAGFlowClient


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
