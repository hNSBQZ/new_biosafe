from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.application.query_service import QueryService
from biosafe.domain.query import QueryRequest
from biosafe.integrations.llm import LLMError
from biosafe.integrations.ragflow.models import RetrievedChunk
from biosafe.storage.admin_repository import BindingRepository
from biosafe.storage.database import Database
from biosafe.storage.history_repository import HistoryRepository


class FakeLLM:
    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeRAGFlow:
    def __init__(self, chunks: list[RetrievedChunk]):
        self.chunks = chunks
        self.requests: list[dict[str, Any]] = []

    async def retrieve(
        self,
        question: str,
        dataset_ids: list[str],
        *,
        page_size: int = 8,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
    ) -> list[RetrievedChunk]:
        self.requests.append(
            {
                "question": question,
                "dataset_ids": dataset_ids,
                "page_size": page_size,
                "similarity_threshold": similarity_threshold,
                "vector_similarity_weight": vector_similarity_weight,
            }
        )
        return self.chunks


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-1",
        dataset_id="dataset-1",
        dataset_name="法规标准",
        document_id="doc-1",
        document_name="fixture.txt",
        content="新型冠状病毒活病毒培养应在生物安全三级实验室进行。",
        page_numbers=(1,),
        similarity=0.91,
    )


def _service(
    tmp_path: Path,
    *,
    llm: FakeLLM,
    ragflow: FakeRAGFlow,
    default_dataset_ids: tuple[str, ...] = ("dataset-1",),
) -> tuple[QueryService, HistoryRepository]:
    database = Database(tmp_path / "query.db")
    database.migrate()
    history_repository = HistoryRepository(database)
    service = QueryService(
        history_repository=history_repository,
        binding_repository=BindingRepository(database),
        prompt_store=ExperimentPromptStore(tmp_path / "missing-experiments"),
        llm_client=llm,
        ragflow_client=ragflow,  # type: ignore[arg-type]
        default_dataset_ids=default_dataset_ids,
    )
    return service, history_repository


async def _collect(service: QueryService, request: QueryRequest, **kwargs: Any) -> list[dict]:
    return [event.to_dict() async for event in service.answer_text(request, **kwargs)]


@pytest.mark.asyncio
async def test_instruction_path_records_func_call_without_llm(tmp_path: Path) -> None:
    llm = FakeLLM([])
    service, history = _service(tmp_path, llm=llm, ragflow=FakeRAGFlow([]))

    events = await _collect(service, QueryRequest(question="现在第几步了", request_id="req-1"))

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "instruction"
    assert events[-1]["data"]["func_call"]["command"] == "ShowProcedurePanel"
    assert llm.calls == []
    saved = history.get_by_request_id("req-1")
    assert saved is not None
    assert saved.answer_source == "instruction"
    assert "ShowProcedurePanel" in saved.system_answer


@pytest.mark.asyncio
async def test_direct_path_records_answer(tmp_path: Path) -> None:
    service, history = _service(
        tmp_path,
        llm=FakeLLM(['{"decision":"direct","answer":"根据当前实验，应先检查防护装备。"}']),
        ragflow=FakeRAGFlow([]),
    )

    events = await _collect(service, QueryRequest(question="麻醉时注意什么？", request_id="req-2"))

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "direct"
    assert events[-1]["data"]["answer"] == "根据当前实验，应先检查防护装备。"
    saved = history.get_by_request_id("req-2")
    assert saved is not None
    assert saved.answer_source == "direct"
    assert saved.status == "completed"


@pytest.mark.asyncio
async def test_rag_path_uses_original_question_and_records_cited_chunk(tmp_path: Path) -> None:
    ragflow = FakeRAGFlow([_chunk()])
    service, history = _service(
        tmp_path,
        llm=FakeLLM(['{"decision":"need_rag"}', "活病毒培养应在BSL-3实验室进行 [1]。"]),
        ragflow=ragflow,
    )

    events = await _collect(
        service,
        QueryRequest(question="新冠活病毒培养需要什么实验室？", request_id="req-3"),
    )

    assert ragflow.requests[0]["question"] == "新冠活病毒培养需要什么实验室？"
    assert ragflow.requests[0]["dataset_ids"] == ["dataset-1"]
    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "rag"
    assert events[-1]["data"]["references"][0]["chunk_id"] == "chunk-1"
    assert events[-1]["data"]["references"][0]["citation_index"] == 1
    saved = history.get_by_request_id("req-3")
    assert saved is not None
    assert saved.ragflow_request["question"] == "新冠活病毒培养需要什么实验室？"
    assert saved.references[0]["document_name"] == "fixture.txt"


@pytest.mark.asyncio
async def test_direct_decision_parse_failure_defaults_to_rag(tmp_path: Path) -> None:
    ragflow = FakeRAGFlow([_chunk()])
    service, _ = _service(
        tmp_path,
        llm=FakeLLM(["not-json", "应在BSL-3实验室进行 [1]。"]),
        ragflow=ragflow,
    )

    events = await _collect(service, QueryRequest(question="需要什么实验室？", request_id="req-4"))

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "rag"
    assert ragflow.requests[0]["question"] == "需要什么实验室？"


@pytest.mark.asyncio
async def test_empty_ragflow_retrieval_is_failed_history(tmp_path: Path) -> None:
    service, history = _service(
        tmp_path,
        llm=FakeLLM(['{"decision":"need_rag"}']),
        ragflow=FakeRAGFlow([]),
    )

    events = await _collect(service, QueryRequest(question="法规依据是什么？", request_id="req-5"))

    assert events[-1]["event"] == "failed"
    assert events[-1]["data"]["code"] == "ragflow_empty_retrieval"
    saved = history.get_by_request_id("req-5")
    assert saved is not None
    assert saved.answer_source == "rag"
    assert saved.status == "failed"


@pytest.mark.asyncio
async def test_synthesis_without_valid_citation_fails(tmp_path: Path) -> None:
    service, history = _service(
        tmp_path,
        llm=FakeLLM(['{"decision":"need_rag"}', "资料显示需要三级实验室。"]),
        ragflow=FakeRAGFlow([_chunk()]),
    )

    events = await _collect(service, QueryRequest(question="需要什么实验室？", request_id="req-6"))

    assert events[-1]["event"] == "failed"
    assert events[-1]["data"]["code"] == "rag_citation_missing"
    saved = history.get_by_request_id("req-6")
    assert saved is not None
    assert saved.status == "failed"


@pytest.mark.asyncio
async def test_llm_direct_timeout_falls_back_to_rag(tmp_path: Path) -> None:
    service, _ = _service(
        tmp_path,
        llm=FakeLLM(
            [
                LLMError("llm_timeout", "timeout"),
                "RAGFlow 片段支持该结论 [1]。",
            ]
        ),
        ragflow=FakeRAGFlow([_chunk()]),
    )

    events = await _collect(service, QueryRequest(question="需要什么实验室？", request_id="req-7"))

    decision_event = next(
        event
        for event in events
        if event["stage"] == "direct_decision" and event["event"] == "stage_result"
    )
    assert decision_event["data"]["fallback_reason"] == "llm_timeout"
    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "rag"


@pytest.mark.asyncio
async def test_cancelled_request_is_persisted(tmp_path: Path) -> None:
    service, history = _service(
        tmp_path,
        llm=FakeLLM(['{"decision":"direct","answer":"不会执行到这里"}']),
        ragflow=FakeRAGFlow([]),
    )
    checks = 0

    async def cancel_after_first_check() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    events = await _collect(
        service,
        QueryRequest(question="普通问题", request_id="req-8"),
        cancel_requested=cancel_after_first_check,
    )

    assert events[-1]["event"] == "cancelled"
    saved = history.get_by_request_id("req-8")
    assert saved is not None
    assert saved.status == "cancelled"
    assert saved.error_code == "cancelled"
