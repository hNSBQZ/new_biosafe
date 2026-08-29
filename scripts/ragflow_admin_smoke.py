"""Live admin API smoke for RAGFlow knowledge management."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biosafe.config import Settings  # noqa: E402
from biosafe.integrations.ragflow.client import _guess_content_type  # noqa: E402
from scripts.ragflow_dev_smoke import (  # noqa: E402
    DEFAULT_SOURCES,
    _download_sources,
)
from services.api.app import create_app  # noqa: E402

DEFAULT_DATASET_NAME = "biosafe-dev-admin"
DEFAULT_QUESTION = "P4实验室穿什么防护服，需要戴口罩吗"


def _load_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    path = Path(".env")
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _merged_env() -> dict[str, str]:
    env = _load_env_file()
    env.update(os.environ)
    return env


def _default_dataset_name() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{DEFAULT_DATASET_NAME}-{stamp}"


async def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/admin/login",
        json={"username": username, "password": password},
    )
    if response.status_code != 200:
        raise RuntimeError(response.text)
    return response.json()


async def _wait_for_document_status(
    client: TestClient,
    *,
    headers: dict[str, str],
    dataset_id: str,
    document_id: str,
    expected_status: str = "DONE",
    timeout_seconds: float = 900.0,
    poll_interval: float = 5.0,
) -> dict[str, object]:
    deadline = perf_counter() + timeout_seconds
    while True:
        response = client.get(
            f"/api/admin/knowledge/datasets/{dataset_id}/documents",
            headers=headers,
        )
        if response.status_code != 200:
            raise RuntimeError(response.text)
        documents = response.json().get("items", [])
        match = next((item for item in documents if item.get("id") == document_id), None)
        if match is None:
            raise RuntimeError(f"Document {document_id} was not found")
        status = str(match.get("status") or "").upper()
        if status == expected_status:
            return match
        if status in {"FAIL", "FAILED", "CANCEL", "CANCELED"}:
            raise RuntimeError(json.dumps(match, ensure_ascii=False))
        if perf_counter() > deadline:
            raise TimeoutError(json.dumps(match, ensure_ascii=False))
        await asyncio.sleep(poll_interval)


async def main() -> int:
    settings = Settings.from_env(_merged_env())
    if not (settings.ragflow.ready and settings.admin.password and settings.admin.token_secret):
        print(
            json.dumps(
                {"ok": False, "reason": "Required admin or RAGFlow services are not configured"},
                ensure_ascii=False,
            )
        )
        return 2

    dataset_name = _default_dataset_name()
    with tempfile.TemporaryDirectory(prefix="biosafe-admin-smoke-") as temp_root:
        smoke_settings = replace(settings, database_path=Path(temp_root) / "admin-smoke.db")
        source_dir = Path(temp_root) / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        source_paths = await _download_sources(source_dir)
        cancel_path = source_dir / "cancel_fixture.html"
        cancel_path.write_text(
            "<html><body>" + ("P4实验室防护要求。 " * 50_000) + "</body></html>",
            encoding="utf-8",
        )
        app = create_app(smoke_settings)

        with TestClient(app) as client:
            login = await _login(client, settings.admin.username, settings.admin.password)
            token = str(login["access_token"])
            headers = {"Authorization": f"Bearer {token}"}

            created = client.post(
                "/api/admin/knowledge/datasets",
                headers=headers,
                json={"name": dataset_name, "chunk_method": "laws"},
            )
            if created.status_code != 200:
                raise RuntimeError(created.text)
            dataset = created.json()
            dataset_id = str(dataset["id"])

            listed = client.get("/api/admin/knowledge/datasets", headers=headers)
            if listed.status_code != 200:
                raise RuntimeError(listed.text)
            listed_payload = listed.json()
            if not any(item.get("id") == dataset_id for item in listed_payload.get("items", [])):
                raise RuntimeError("Created dataset did not appear in list response")

            uploaded_docs: list[dict[str, object]] = []
            upload_targets = [
                (source_paths[0], DEFAULT_SOURCES[0].filename),
                (source_paths[1], DEFAULT_SOURCES[1].filename),
                (cancel_path, cancel_path.name),
            ]
            for path, filename in upload_targets:
                with path.open("rb") as handle:
                    response = client.post(
                        f"/api/admin/knowledge/datasets/{dataset_id}/documents",
                        headers=headers,
                        files={
                            "file": (filename, handle, _guess_content_type(path)),
                        },
                    )
                if response.status_code != 200:
                    raise RuntimeError(response.text)
                item = response.json()["items"][0]
                uploaded_docs.append(item)

            for document in uploaded_docs[:2]:
                parse_response = client.post(
                    f"/api/admin/knowledge/datasets/{dataset_id}/documents/{document['id']}/parse",
                    headers=headers,
                )
                if parse_response.status_code != 200:
                    raise RuntimeError(parse_response.text)

            cancel_parse_response = client.post(
                f"/api/admin/knowledge/datasets/{dataset_id}/documents/{uploaded_docs[2]['id']}/parse",
                headers=headers,
            )
            if cancel_parse_response.status_code != 200:
                raise RuntimeError(cancel_parse_response.text)
            await asyncio.sleep(0.5)
            cancel_response = client.post(
                f"/api/admin/knowledge/datasets/{dataset_id}/documents/{uploaded_docs[2]['id']}/cancel",
                headers=headers,
            )
            if cancel_response.status_code != 200:
                raise RuntimeError(cancel_response.text)
            cancelled = cancel_response.json()

            parsed_primary = await _wait_for_document_status(
                client,
                headers=headers,
                dataset_id=dataset_id,
                document_id=str(uploaded_docs[0]["id"]),
            )

            parsed_secondary = await _wait_for_document_status(
                client,
                headers=headers,
                dataset_id=dataset_id,
                document_id=str(uploaded_docs[1]["id"]),
            )

            preview_response = client.post(
                "/api/admin/knowledge/retrieval-preview",
                headers=headers,
                json={
                    "question": DEFAULT_QUESTION,
                    "dataset_ids": [dataset_id],
                    "page_size": 8,
                },
            )
            if preview_response.status_code != 200:
                raise RuntimeError(preview_response.text)
            preview = preview_response.json()

            deleted_documents = []
            for document in uploaded_docs:
                delete_response = client.delete(
                    f"/api/admin/knowledge/datasets/{dataset_id}/documents/{document['id']}",
                    headers=headers,
                )
                if delete_response.status_code != 200:
                    raise RuntimeError(delete_response.text)
                deleted_documents.append(document["id"])

            delete_dataset = client.delete(
                f"/api/admin/knowledge/datasets/{dataset_id}",
                headers=headers,
            )
            if delete_dataset.status_code != 200:
                raise RuntimeError(delete_dataset.text)

        print(
            json.dumps(
                {
                    "ok": True,
                    "dataset": {
                        "id": dataset_id,
                        "name": dataset_name,
                        "chunk_method": "laws",
                    },
                    "documents": [
                        {
                            "id": str(item["id"]),
                            "name": str(item["name"]),
                            "status": str(item["status"]),
                            "chunk_count": int(item.get("chunk_count") or 0),
                        }
                        for item in (parsed_primary, parsed_secondary, cancelled)
                    ],
                    "retrieval": {
                        "chunk_count": len(preview.get("chunks", [])),
                        "question": DEFAULT_QUESTION,
                    },
                    "deleted_documents": deleted_documents,
                },
                ensure_ascii=False,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
