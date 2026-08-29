from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from biosafe.config import AdminConfig, RAGFlowConfig, Settings
from biosafe.integrations.ragflow import RAGFlowClient
from services.api.app import create_app


def test_admin_routes_require_authentication(tmp_path: Path) -> None:
    app = _app(tmp_path, _ragflow_handler([]))

    with TestClient(app) as client:
        unauthorized = client.get("/api/admin/knowledge/datasets")
        failed_login = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "wrong"},
        )

    assert unauthorized.status_code == 401
    assert failed_login.status_code == 401


def test_admin_knowledge_management_routes(tmp_path: Path) -> None:
    seen: list[str] = []
    app = _app(tmp_path, _ragflow_handler(seen))

    with TestClient(app) as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            "/api/admin/knowledge/datasets",
            headers=headers,
            json={"name": "biosafe-dev-laws", "chunk_method": "laws"},
        )
        listed = client.get("/api/admin/knowledge/datasets", headers=headers)
        documents = client.get(
            "/api/admin/knowledge/datasets/dataset-1/documents",
            headers=headers,
        )
        uploaded = client.post(
            "/api/admin/knowledge/datasets/dataset-1/documents",
            headers=headers,
            files={"file": ("test.html", b"<html>test</html>", "text/html")},
        )
        parsed = client.post(
            "/api/admin/knowledge/datasets/dataset-1/documents/doc-1/parse",
            headers=headers,
        )
        retried = client.post(
            "/api/admin/knowledge/datasets/dataset-1/documents/doc-1/retry",
            headers=headers,
        )
        cancelled = client.post(
            "/api/admin/knowledge/datasets/dataset-1/documents/doc-1/cancel",
            headers=headers,
        )
        preview = client.post(
            "/api/admin/knowledge/retrieval-preview",
            headers=headers,
            json={"question": "问题？", "dataset_ids": ["dataset-1"]},
        )
        deleted_document = client.delete(
            "/api/admin/knowledge/datasets/dataset-1/documents/doc-1",
            headers=headers,
        )
        deleted_dataset = client.delete(
            "/api/admin/knowledge/datasets/dataset-1",
            headers=headers,
        )

    assert created.status_code == 200
    assert created.json()["chunk_method"] == "laws"
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == "dataset-1"
    assert documents.status_code == 200
    assert documents.json()["items"][0]["status"] == "DONE"
    assert uploaded.status_code == 200
    assert uploaded.json()["items"][0]["name"] == "test.html"
    assert parsed.status_code == 200
    assert retried.status_code == 200
    assert cancelled.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["chunks"][0]["citation_index"] == 1
    assert deleted_document.json() == {"ok": True}
    assert deleted_dataset.json() == {"ok": True}
    assert seen == [
        "create_dataset",
        "list_datasets",
        "list_datasets",
        "list_documents",
        "list_datasets",
        "upload_document",
        "list_datasets",
        "start_parse",
        "list_documents",
        "list_datasets",
        "start_parse",
        "list_documents",
        "list_datasets",
        "cancel_parse",
        "list_documents",
        "list_datasets",
        "retrieve",
        "list_datasets",
        "delete_document",
        "list_datasets",
        "delete_dataset",
    ]


def test_admin_rejects_non_dev_namespace_writes(tmp_path: Path) -> None:
    seen: list[str] = []
    app = _app(
        tmp_path,
        _ragflow_handler(
            seen,
            dataset_name="public-dataset",
            dataset_id="dataset-public",
        ),
    )

    with TestClient(app) as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            "/api/admin/knowledge/datasets",
            headers=headers,
            json={"name": "public-dataset", "chunk_method": "laws"},
        )
        deleted = client.delete(
            "/api/admin/knowledge/datasets/dataset-public",
            headers=headers,
        )

    assert created.status_code == 403
    assert deleted.status_code == 403
    assert seen == ["list_datasets"]


def _app(tmp_path: Path, handler) -> object:
    settings = Settings(
        database_path=tmp_path / "api.db",
        ragflow=RAGFlowConfig(base_url="http://ragflow.test", api_key="rag-token"),
        admin=AdminConfig(
            username="admin",
            password="secret",
            token_secret="token-secret",
            token_ttl_seconds=3600,
        ),
    )
    app = create_app(settings)
    app.state.ragflow_client = RAGFlowClient(
        settings.ragflow,
        transport=httpx.MockTransport(handler),
    )
    return app


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "secret"},
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _ragflow_handler(
    seen: list[str],
    *,
    dataset_name: str = "biosafe-dev-laws",
    dataset_id: str = "dataset-1",
):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer rag-token"
        if request.method == "POST" and request.url.path == "/api/v1/datasets":
            seen.append("create_dataset")
            body = json.loads(request.content)
            assert body["parser_config"] == {"raptor": {"use_raptor": False}}
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": _dataset_payload(
                        dataset_name=dataset_name,
                        dataset_id=dataset_id,
                    ),
                },
            )

        if request.method == "GET" and request.url.path == "/api/v1/datasets":
            seen.append("list_datasets")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        _dataset_payload(
                            dataset_name=dataset_name,
                            dataset_id=dataset_id,
                        )
                    ],
                },
            )

        documents_path = f"/api/v1/datasets/{dataset_id}/documents"
        chunks_path = f"/api/v1/datasets/{dataset_id}/chunks"

        if request.method == "GET" and request.url.path == documents_path:
            seen.append("list_documents")
            return httpx.Response(200, json={"code": 0, "data": [_document_payload()]})

        if request.method == "POST" and request.url.path == documents_path:
            seen.append("upload_document")
            assert request.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(200, json={"code": 0, "data": [_document_payload()]})

        if request.method == "POST" and request.url.path == chunks_path:
            seen.append("start_parse")
            assert json.loads(request.content) == {"document_ids": ["doc-1"]}
            return httpx.Response(200, json={"code": 0})

        if request.method == "DELETE" and request.url.path == chunks_path:
            seen.append("cancel_parse")
            assert json.loads(request.content) == {"document_ids": ["doc-1"]}
            return httpx.Response(200, json={"code": 0})

        if request.method == "POST" and request.url.path == "/api/v1/retrieval":
            seen.append("retrieve")
            body = json.loads(request.content)
            assert body["question"] == "问题？"
            assert body["dataset_ids"] == [dataset_id]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "chunks": [
                            {
                                "id": "chunk-1",
                                "dataset_id": dataset_id,
                                "document_id": "doc-1",
                                "document_name": "test.html",
                                "content": "片段",
                                "similarity": 0.9,
                            }
                        ]
                    },
                },
            )

        if (
            request.method == "DELETE"
            and request.url.path == f"/api/v1/datasets/{dataset_id}/documents"
        ):
            seen.append("delete_document")
            assert json.loads(request.content) == {"ids": ["doc-1"]}
            return httpx.Response(200, json={"code": 0})

        if request.method == "DELETE" and request.url.path == "/api/v1/datasets":
            seen.append("delete_dataset")
            assert json.loads(request.content) == {"ids": [dataset_id]}
            return httpx.Response(200, json={"code": 0})

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return handler


def _dataset_payload(
    *,
    dataset_name: str = "biosafe-dev-laws",
    dataset_id: str = "dataset-1",
) -> dict[str, object]:
    return {
        "id": dataset_id,
        "name": dataset_name,
        "chunk_method": "laws",
        "document_count": 1,
        "embedding_model": "embedding",
        "permission": "me",
        "status": "DONE",
        "parser_config": {"raptor": {"use_raptor": False}},
    }


def _document_payload() -> dict[str, object]:
    return {
        "id": "doc-1",
        "knowledgebase_id": "dataset-1",
        "name": "test.html",
        "run": "DONE",
        "chunk_count": 2,
        "progress": 1.0,
        "progress_msg": "",
        "size": 128,
    }
