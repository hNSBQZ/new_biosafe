"""Create or reuse a biosafe-dev dataset, upload sources, parse, and smoke retrieval."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biosafe.config import Settings  # noqa: E402
from biosafe.integrations.ragflow import RAGFlowClient, RAGFlowError  # noqa: E402


@dataclass(frozen=True)
class SourceSpec:
    title: str
    url: str
    filename: str


DEFAULT_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        title="病原微生物实验室生物安全管理条例",
        url="https://www.mee.gov.cn/ywgz/fgbz/xzfg/202303/t20230316_1019776.shtml",
        filename="病原微生物实验室生物安全管理条例.html",
    ),
    SourceSpec(
        title="中国首个P4实验室正式运行！可研究世界上最危险的病原体！",
        url="https://wjw.hubei.gov.cn/bmdt/ztzl/wqzl/hbswsjkkjxtcxzt/sysswaq/201910/t20191030_151998.shtml",
        filename="中国首个P4实验室正式运行.html",
    ),
    SourceSpec(
        title="GB 19489—2007（公开转载文本）",
        url="https://sysb.shou.edu.cn/_upload/article/files/24/4d/b2dca8294ff18bc9703e79b3dcb0/1dea7a48-74bd-47e8-b4d5-721f0ff3fd0d.pdf",
        filename="GB_19489-2007.pdf",
    ),
)


def _parser_config(chunk_method: str) -> dict[str, Any] | None:
    if chunk_method == "naive":
        return None
    if chunk_method in {"laws", "manual", "paper", "book", "qa", "presentation"}:
        return {"raptor": {"use_raptor": False}}
    return {}


def _default_dataset_name() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"biosafe-dev-p4-ppe-{stamp}"


async def _download_sources(temp_dir: Path) -> list[Path]:
    paths: list[Path] = []
    async with httpx.AsyncClient(timeout=60) as client:
        for index, spec in enumerate(DEFAULT_SOURCES, start=1):
            response = await client.get(spec.url)
            response.raise_for_status()
            path = temp_dir / f"source_{index}{Path(spec.filename).suffix}"
            path.write_bytes(response.content)
            paths.append(path)
    return paths


async def _ensure_dataset(
    client: RAGFlowClient,
    *,
    dataset_name: str,
    chunk_method: str,
) -> tuple[str, bool]:
    datasets = await client.list_datasets()
    for dataset in datasets:
        if dataset.name.lower() == dataset_name.lower():
            return dataset.id, False
    created = await client.create_dataset(
        dataset_name,
        chunk_method=chunk_method,
        parser_config=_parser_config(chunk_method),
    )
    return created.id, True


async def _ensure_documents(
    client: RAGFlowClient,
    *,
    dataset_id: str,
    temp_paths: list[Path],
) -> list[dict[str, Any]]:
    existing = await client.list_documents(dataset_id, page_size=100)
    by_name = {document.name: document for document in existing}
    documents: list[dict[str, Any]] = []
    for spec, path in zip(DEFAULT_SOURCES, temp_paths, strict=True):
        document = by_name.get(spec.filename)
        created = False
        if document is None:
            uploaded = await client.upload_document(dataset_id, path, filename=spec.filename)
            if len(uploaded) != 1:
                raise RAGFlowError(
                    "ragflow_upload_invalid",
                    f"Unexpected upload response for {spec.filename}",
                )
            document = uploaded[0]
            created = True
        documents.append(
            {
                "title": spec.title,
                "name": document.name,
                "id": document.id,
                "status": document.status,
                "created": created,
            }
        )
    pending_ids = [
        item["id"]
        for item in documents
        if str(item["status"]).upper() in {"UNSTART", "FAIL", "CANCEL", "SCHEDULE"}
    ]
    if pending_ids:
        await client.start_parse(dataset_id, pending_ids)
    return documents


async def _wait_for_parse(
    client: RAGFlowClient,
    *,
    dataset_id: str,
    names: set[str],
    timeout_seconds: float = 900.0,
    poll_interval: float = 5.0,
) -> list[dict[str, Any]]:
    deadline = perf_counter() + timeout_seconds
    while True:
        documents = await client.list_documents(dataset_id, page_size=100)
        selected = [document for document in documents if document.name in names]
        if len(selected) != len(names):
            if perf_counter() > deadline:
                raise TimeoutError("Timed out waiting for dataset documents to appear")
            await asyncio.sleep(poll_interval)
            continue

        statuses = {document.name: str(document.status).upper() for document in selected}
        if any(status in {"FAIL", "CANCEL"} for status in statuses.values()):
            raise RuntimeError(json.dumps(statuses, ensure_ascii=False))
        if all(status == "DONE" for status in statuses.values()):
            return [
                {
                    "name": document.name,
                    "id": document.id,
                    "status": document.status,
                    "chunk_count": document.chunk_count,
                    "progress": document.progress,
                }
                for document in selected
            ]
        if perf_counter() > deadline:
            raise TimeoutError(json.dumps(statuses, ensure_ascii=False))
        await asyncio.sleep(poll_interval)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-name",
        default=os.environ.get("RAGFLOW_DEV_DATASET_NAME") or _default_dataset_name(),
    )
    parser.add_argument(
        "--chunk-method",
        default=os.environ.get("RAGFLOW_DEV_CHUNK_METHOD", "naive"),
    )
    parser.add_argument(
        "--question",
        default=os.environ.get("RAGFLOW_DEV_QUESTION", "P4实验室穿什么防护服，需要戴口罩吗"),
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.ragflow.ready:
        print(json.dumps({"ok": False, "reason": "RAGFlow is not configured"}, ensure_ascii=False))
        return 2

    dataset_name = args.dataset_name
    question = args.question
    chunk_method = args.chunk_method

    with tempfile.TemporaryDirectory(prefix="ragflow-dev-") as temp_root:
        temp_dir = Path(temp_root)
        source_paths = await _download_sources(temp_dir)

        async with RAGFlowClient(settings.ragflow) as client:
            dataset_id, created = await _ensure_dataset(
                client, dataset_name=dataset_name, chunk_method=chunk_method
            )
            documents = await _ensure_documents(
                client, dataset_id=dataset_id, temp_paths=source_paths
            )
            finished = await _wait_for_parse(
                client,
                dataset_id=dataset_id,
                names={item["name"] for item in documents},
            )
            chunks = await client.retrieve(question, [dataset_id])

    print(
        json.dumps(
            {
                "ok": True,
                "dataset": {
                    "id": dataset_id,
                    "name": dataset_name,
                    "created": created,
                    "chunk_method": chunk_method,
                },
                "documents": finished,
                "retrieval": {
                    "chunk_count": len(chunks),
                    "dataset_ids": [dataset_id],
                    "question": question,
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
