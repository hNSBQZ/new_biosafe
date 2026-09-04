from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
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


@pytest.mark.asyncio
async def test_admin_file_center_hides_datasets_and_proxies_original_file(tmp_path: Path) -> None:
    seen: list[str] = []
    app = _app(tmp_path, _ragflow_handler(seen))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        token = str(login.json()["access_token"])
        headers = {"Authorization": f"Bearer {token}"}

        listed = await client.get(
            "/api/admin/knowledge/files",
            headers=headers,
            params={
                "category": "laws",
                "status": "completed",
                "date_from": "2026-09-01",
                "date_to": "2026-09-04",
            },
        )
        content = await client.get(
            "/api/admin/knowledge/files/doc-1/content",
            headers=headers,
        )
        uploaded = await client.post(
            "/api/admin/knowledge/files",
            headers=headers,
            data={"category": "laws"},
            files={"file": ("new.html", b"<html>new</html>", "text/html")},
        )
        retried = await client.post(
            "/api/admin/knowledge/files/doc-1/retry",
            headers=headers,
        )
        deleted = await client.delete(
            "/api/admin/knowledge/files/doc-1",
            headers=headers,
        )

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    item = listed.json()["items"][0]
    assert item == {
        "id": "doc-1",
        "name": "test.html",
        "category": "laws",
        "category_label": "法规标准",
        "status": "completed",
        "status_label": "已完成",
        "progress": 1.0,
        "status_message": "",
        "size": 128,
        "created_at": "2026-09-03T00:00:00+00:00",
        "updated_at": "2026-09-03T01:00:00+00:00",
        "preview_kind": "text",
    }
    assert "dataset" not in str(item).lower()
    assert content.status_code == 200
    assert content.content == b"<html><body>preview</body></html>"
    assert content.headers["content-security-policy"] == "sandbox"
    assert content.headers["content-disposition"].startswith("inline;")
    assert uploaded.status_code == 200
    assert uploaded.json()["items"][0]["category_label"] == "法规标准"
    assert retried.status_code == 200
    assert deleted.json() == {"ok": True}
    assert "download_document" in seen
    assert seen.count("start_parse") == 2


@pytest.mark.asyncio
async def test_file_center_name_filter_uses_ragflow_keywords(tmp_path: Path) -> None:
    filename = "1746698296999_79788.pdf"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/datasets":
            return httpx.Response(200, json={"code": 0, "data": [_dataset_payload()]})
        if request.method == "GET" and request.url.path.endswith("/documents"):
            assert request.url.params["keywords"] == filename
            assert "name" not in request.url.params
            document = _document_payload()
            document["name"] = filename
            return httpx.Response(200, json={"code": 0, "data": [document]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    app = _app(tmp_path, handler)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "secret"},
        )
        response = await client.get(
            "/api/admin/knowledge/files",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            params={"name": filename},
        )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["name"] == filename


@pytest.mark.asyncio
async def test_retrieval_match_uses_online_default_configuration(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/datasets":
            return httpx.Response(200, json={"code": 0, "data": [_dataset_payload()]})
        if request.method == "POST" and request.url.path == "/api/v1/retrieval":
            body = json.loads(request.content)
            assert body == {
                "question": "办公区是指什么？",
                "dataset_ids": ["dataset-1"],
                "page": 1,
                "page_size": 8,
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
            }
            chunk = {
                "id": "chunk-office",
                "dataset_id": "dataset-1",
                "document_id": "doc-office",
                "document_name": "术语标准.pdf",
                "content": "办公区是实验工作区域之外，与实验室区域有效隔离的区域。",
                "similarity": 0.92,
                "vector_similarity": 0.88,
                "term_similarity": 0.95,
            }
            return httpx.Response(200, json={"code": 0, "data": {"chunks": [chunk]}})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    app = _app(tmp_path, handler, default_dataset_ids=("dataset-1",))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "secret"},
        )
        response = await client.post(
            "/api/admin/knowledge/retrieval-match",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={"question": "办公区是指什么？"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["datasets"] == [
        {"id": "dataset-1", "name": "biosafe-dev-laws", "chunk_method": "laws"}
    ]
    assert payload["page_size"] == 8
    assert payload["similarity_threshold"] == 0.2
    assert payload["vector_similarity_weight"] == 0.3
    assert payload["chunks"][0]["content"].startswith("办公区是实验工作区域之外")


@pytest.mark.asyncio
async def test_file_upload_creates_internal_category_dataset_and_starts_parse(
    tmp_path: Path,
) -> None:
    created = False
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal created
        if request.method == "GET" and request.url.path == "/api/v1/datasets":
            return httpx.Response(
                200,
                json={"code": 0, "data": [_dataset_payload()] if created else []},
            )
        if request.method == "POST" and request.url.path == "/api/v1/datasets":
            body = json.loads(request.content)
            assert body["name"] == "biosafe-dev-laws"
            assert body["chunk_method"] == "laws"
            created = True
            seen.append("create_dataset")
            return httpx.Response(200, json={"code": 0, "data": _dataset_payload()})
        if request.method == "POST" and request.url.path.endswith("/documents"):
            seen.append("upload_document")
            return httpx.Response(200, json={"code": 0, "data": [_document_payload()]})
        if request.method == "POST" and request.url.path.endswith("/chunks"):
            assert json.loads(request.content) == {"document_ids": ["doc-1"]}
            seen.append("start_parse")
            return httpx.Response(200, json={"code": 0})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    app = _app(tmp_path, handler)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "secret"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await client.post(
            "/api/admin/knowledge/files",
            headers=headers,
            data={"category": "laws"},
            files={"file": ("rule.html", b"<html>rule</html>", "text/html")},
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["category"] == "laws"
    assert seen == ["create_dataset", "upload_document", "start_parse"]


@pytest.mark.asyncio
async def test_file_upload_rejects_same_name_across_categories(tmp_path: Path) -> None:
    writes: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/datasets":
            dataset = _dataset_payload(dataset_name="biosafe-dev-naive", dataset_id="naive-1")
            dataset["chunk_method"] = "naive"
            return httpx.Response(200, json={"code": 0, "data": [dataset]})
        if request.method == "GET" and request.url.path.endswith("/documents"):
            document = _document_payload()
            document["knowledgebase_id"] = "naive-1"
            document["name"] = "GB_19489-2007.pdf"
            return httpx.Response(200, json={"code": 0, "data": [document]})
        if request.method == "POST":
            writes.append(request.url.path)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    app = _app(tmp_path, handler)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "secret"},
        )
        response = await client.post(
            "/api/admin/knowledge/files",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            data={"category": "laws"},
            files={"file": ("gb_19489-2007.PDF", b"duplicate", "application/pdf")},
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "duplicate_knowledge_file"
    assert detail["existing"]["name"] == "GB_19489-2007.pdf"
    assert detail["existing"]["category_label"] == "通用资料"
    assert "dataset" not in str(detail["existing"]).lower()
    assert writes == []


def _app(
    tmp_path: Path,
    handler,
    *,
    default_dataset_ids: tuple[str, ...] = (),
) -> object:
    settings = Settings(
        database_path=tmp_path / "api.db",
        ragflow=RAGFlowConfig(
            base_url="http://ragflow.test",
            api_key="rag-token",
            dataset_ids=default_dataset_ids,
        ),
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

        if request.method == "GET" and request.url.path == f"{documents_path}/doc-1":
            seen.append("download_document")
            return httpx.Response(
                200,
                content=b"<html><body>preview</body></html>",
                headers={"Content-Type": "text/html; charset=utf-8"},
            )

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
        "type": "html",
        "create_date": "2026-09-03T00:00:00Z",
        "update_date": "2026-09-03T01:00:00Z",
    }
