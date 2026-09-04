import json
from pathlib import Path

import httpx
import pytest

from biosafe.config import RAGFlowConfig
from biosafe.integrations.ragflow import RAGFlowClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_list_datasets_contract() -> None:
    payload = json.loads((FIXTURES / "ragflow_list_datasets.json").read_text())

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.params["name"] == "fixture-dataset"
        assert request.url.params["include_parsing_status"] == "true"
        return httpx.Response(200, json=payload)

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        datasets = await client.list_datasets(name="fixture-dataset", include_parsing_status=True)

    assert datasets[0].id == "dataset-fixture-id"
    assert datasets[0].chunk_method == "naive"


@pytest.mark.asyncio
async def test_list_documents_maps_name_filter_to_keywords() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/datasets/dataset-1/documents"
        assert request.url.params["keywords"] == "1746698296999_79788.pdf"
        assert "name" not in request.url.params
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [
                    {
                        "id": "document-1",
                        "knowledgebase_id": "dataset-1",
                        "name": "1746698296999_79788.pdf",
                        "run": "DONE",
                    }
                ],
            },
        )

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        documents = await client.list_documents(
            "dataset-1",
            name="1746698296999_79788.pdf",
        )

    assert documents[0].name == "1746698296999_79788.pdf"


@pytest.mark.asyncio
async def test_list_documents_prefers_explicit_keywords_filter() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["keywords"] == "explicit search"
        assert "name" not in request.url.params
        return httpx.Response(200, json={"code": 0, "data": []})

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        documents = await client.list_documents(
            "dataset-1",
            keywords="explicit search",
            name="ignored name",
        )

    assert documents == []


@pytest.mark.asyncio
async def test_retrieval_uses_original_question_and_normalizes_chunk() -> None:
    payload = json.loads((FIXTURES / "ragflow_retrieval.json").read_text())

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["question"] == "原始问题？"
        assert body["dataset_ids"] == ["dataset-fixture-id"]
        return httpx.Response(200, json=payload)

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        chunks = await client.retrieve("原始问题？", ["dataset-fixture-id"])

    assert chunks[0].document_name == "fixture.txt"
    assert chunks[0].page_numbers == (1,)
    assert chunks[0].similarity == 0.91


@pytest.mark.asyncio
async def test_retrieval_normalizes_ragflow_document_keyword_alias() -> None:
    payload = {
        "code": 0,
        "data": {
            "chunks": [
                {
                    "id": "chunk-alias",
                    "knowledgebase_id": "dataset-alias",
                    "doc_id": "document-alias",
                    "document_keyword": "生物安全操作规程.pdf",
                    "content_with_weight": "需要使用规定的个人防护装备。",
                    "similarity": 0.88,
                }
            ]
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        chunks = await client.retrieve("需要什么防护？", ["dataset-alias"])

    assert chunks[0].dataset_id == "dataset-alias"
    assert chunks[0].document_name == "生物安全操作规程.pdf"


@pytest.mark.asyncio
async def test_create_upload_parse_and_delete_contract(tmp_path: Path) -> None:
    seen: list[tuple[str, str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/datasets":
            body = json.loads(request.content)
            seen.append(("create_dataset", request.method, body))
            assert body == {
                "name": "biosafe-dev-laws",
                "chunk_method": "laws",
                "parser_config": {"raptor": {"use_raptor": False}},
            }
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "id": "dataset-created",
                        "name": "biosafe-dev-laws",
                        "chunk_method": "laws",
                        "document_count": 0,
                        "embedding_model": "text-embedding-v3@embedding@Tongyi-Qianwen",
                        "parser_config": {"raptor": {"use_raptor": False}},
                    },
                },
            )

        if (
            request.method == "POST"
            and request.url.path == "/api/v1/datasets/dataset-created/documents"
        ):
            seen.append(("upload_document", request.method, {}))
            assert request.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {
                            "id": "document-created",
                            "knowledgebase_id": "dataset-created",
                            "name": "test.html",
                            "location": "test.html",
                            "run": "UNSTART",
                            "chunk_count": 0,
                            "size": 12,
                            "source_type": "local",
                            "type": "doc",
                            "create_time": 1_788_393_600,
                        }
                    ],
                },
            )

        if (
            request.method == "POST"
            and request.url.path == "/api/v1/datasets/dataset-created/chunks"
        ):
            body = json.loads(request.content)
            seen.append(("start_parse", request.method, body))
            assert body == {"document_ids": ["document-created"]}
            return httpx.Response(200, json={"code": 0})

        if request.method == "DELETE" and request.url.path == "/api/v1/datasets":
            body = json.loads(request.content)
            seen.append(("delete_dataset", request.method, body))
            assert body == {"ids": ["dataset-created"]}
            return httpx.Response(200, json={"code": 0})

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    sample = tmp_path / "test.html"
    sample.write_text("<html><body>test</body></html>", encoding="utf-8")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        dataset = await client.create_dataset(
            "biosafe-dev-laws",
            chunk_method="laws",
            parser_config={"raptor": {"use_raptor": False}},
        )
        documents = await client.upload_document(
            dataset.id,
            sample,
            filename="test.html",
        )
        await client.start_parse(dataset.id, [document.id for document in documents])
        await client.delete_owned_dataset(dataset.id)

    assert dataset.id == "dataset-created"
    assert documents[0].dataset_id == "dataset-created"
    assert documents[0].status == "UNSTART"
    assert documents[0].created_at == "2026-09-03T00:00:00+00:00"
    assert [item[0] for item in seen] == [
        "create_dataset",
        "upload_document",
        "start_parse",
        "delete_dataset",
    ]


@pytest.mark.asyncio
async def test_download_document_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/datasets/dataset-1/documents/doc-1"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            content=b"%PDF fixture",
            headers={"Content-Type": "application/pdf"},
        )

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        downloaded = await client.download_document("dataset-1", "doc-1")

    assert downloaded.content == b"%PDF fixture"
    assert downloaded.content_type == "application/pdf"
