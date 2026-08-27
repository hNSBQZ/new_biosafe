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
        return httpx.Response(200, json=payload)

    config = RAGFlowConfig(base_url="http://ragflow.test", api_key="test-token")
    async with RAGFlowClient(config, httpx.MockTransport(handler)) as client:
        datasets = await client.list_datasets()

    assert datasets[0].id == "dataset-fixture-id"
    assert datasets[0].chunk_method == "naive"


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
