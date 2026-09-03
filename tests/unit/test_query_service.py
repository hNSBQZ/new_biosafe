from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.application.query_service import QueryService
from biosafe.domain.history import ChatHistory
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


class FakeCorrectionDispatcher:
    def __init__(self) -> None:
        self.histories: list[ChatHistory] = []

    def submit(self, history: ChatHistory, *, retry: bool = False):
        self.histories.append(history)
        return None


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
    correction_dispatcher: FakeCorrectionDispatcher | None = None,
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
        correction_dispatcher=correction_dispatcher,
    )
    return service, history_repository


async def _collect(service: QueryService, request: QueryRequest, **kwargs: Any) -> list[dict]:
    return [event.to_dict() async for event in service.answer_text(request, **kwargs)]


@pytest.mark.asyncio
async def test_model_instruction_path_records_whitelisted_func_call(tmp_path: Path) -> None:
    llm = FakeLLM(
        [
            '{"decision":"func_call","func_call":'
            '{"command":"ShowProcedurePanel","confidence":0.97,"params":{}}}'
        ]
    )
    service, history = _service(tmp_path, llm=llm, ragflow=FakeRAGFlow([]))

    events = await _collect(service, QueryRequest(question="现在第几步了", request_id="req-1"))

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "instruction"
    assert events[-1]["data"]["func_call"]["command"] == "ShowProcedurePanel"
    assert len(llm.calls) == 1
    assert '"decision":"func_call"' in llm.calls[0][0]["content"]
    saved = history.get_by_request_id("req-1")
    assert saved is not None
    assert saved.answer_source == "instruction"
    assert "ShowProcedurePanel" in saved.system_answer


@pytest.mark.asyncio
async def test_direct_path_records_answer(tmp_path: Path) -> None:
    correction_dispatcher = FakeCorrectionDispatcher()
    service, history = _service(
        tmp_path,
        llm=FakeLLM(['{"decision":"direct","answer":"根据当前实验，应先检查防护装备。"}']),
        ragflow=FakeRAGFlow([]),
        correction_dispatcher=correction_dispatcher,
    )

    events = await _collect(service, QueryRequest(question="麻醉时注意什么？", request_id="req-2"))

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "direct"
    assert events[-1]["data"]["answer"] == "根据当前实验，应先检查防护装备。"
    saved = history.get_by_request_id("req-2")
    assert saved is not None
    assert saved.answer_source == "direct"
    assert saved.status == "completed"
    assert [item.id for item in correction_dispatcher.histories] == [saved.id]


@pytest.mark.asyncio
async def test_laboratory_protection_question_follows_model_rag_decision(tmp_path: Path) -> None:
    service, _ = _service(
        tmp_path,
        llm=FakeLLM(
            [
                '{"decision":"need_rag"}',
                "进入实验室前应按风险评估选择个人防护装备 [1]。",
            ]
        ),
        ragflow=FakeRAGFlow([_chunk()]),
    )

    events = await _collect(
        service,
        QueryRequest(
            question="进入生物安全实验室时，应当佩戴什么防护？",
            request_id="req-laboratory-ppe",
        ),
    )

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "rag"


@pytest.mark.asyncio
async def test_invalid_model_func_call_falls_back_to_rag(tmp_path: Path) -> None:
    service, _ = _service(
        tmp_path,
        llm=FakeLLM(
            [
                '{"decision":"func_call","func_call":'
                '{"command":"DeleteExperiment","confidence":1,"params":{}}}',
                "只能执行经过授权的实验操作 [1]。",
            ]
        ),
        ragflow=FakeRAGFlow([_chunk()]),
    )

    events = await _collect(
        service,
        QueryRequest(question="删除实验", request_id="req-invalid-func-call"),
    )

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "rag"


@pytest.mark.asyncio
async def test_model_func_call_with_params_falls_back_to_rag(tmp_path: Path) -> None:
    service, _ = _service(
        tmp_path,
        llm=FakeLLM(
            [
                '{"decision":"func_call","func_call":'
                '{"command":"SwitchExperimentScene","confidence":1,'
                '"params":{"experiment_id":"4"}}}',
                "实验切换参数不应由当前协议自动补充 [1]。",
            ]
        ),
        ragflow=FakeRAGFlow([_chunk()]),
    )

    events = await _collect(
        service,
        QueryRequest(question="切换到实验四", request_id="req-func-call-params"),
    )

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer_source"] == "rag"


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
    correction_dispatcher = FakeCorrectionDispatcher()
    service, history = _service(
        tmp_path,
        llm=FakeLLM(['{"decision":"need_rag"}']),
        ragflow=FakeRAGFlow([]),
        correction_dispatcher=correction_dispatcher,
    )

    events = await _collect(service, QueryRequest(question="法规依据是什么？", request_id="req-5"))

    assert events[-1]["event"] == "failed"
    assert events[-1]["data"]["code"] == "ragflow_empty_retrieval"
    saved = history.get_by_request_id("req-5")
    assert saved is not None
    assert saved.answer_source == "rag"
    assert saved.status == "failed"
    assert correction_dispatcher.histories == []


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
async def test_sparse_rag_citations_are_repaired_with_same_chunks(tmp_path: Path) -> None:
    llm = FakeLLM(
        [
            '{"decision":"need_rag"}',
            "活病毒培养应在BSL-3实验室进行 [1]。操作人员还需要遵守设施规程。",
            "活病毒培养应在BSL-3实验室进行 [1]。操作人员还需要遵守设施规程 [1]。",
        ]
    )
    service, _ = _service(tmp_path, llm=llm, ragflow=FakeRAGFlow([_chunk()]))

    events = await _collect(
        service,
        QueryRequest(question="需要什么实验室并遵守什么要求？", request_id="req-citation-repair"),
    )

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer"].count("[1]") == 2
    assert len(llm.calls) == 3
    assert "同一批参考资料" in llm.calls[-1][-1]["content"]


@pytest.mark.asyncio
async def test_incomplete_citation_coverage_logs_warning_and_returns_answer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    initial_draft = "实验室需要采取控制措施 [1]。这里还有一个没有引用的具体操作要求。"
    repaired_draft = "实验室需要采取控制措施 [1]。这个具体操作要求仍然没有引用。"
    llm = FakeLLM(
        [
            '{"decision":"need_rag"}',
            initial_draft,
            repaired_draft,
        ]
    )
    service, history = _service(tmp_path, llm=llm, ragflow=FakeRAGFlow([_chunk()]))
    caplog.set_level(logging.WARNING, logger="biosafe.application.query_service")

    events = await _collect(
        service,
        QueryRequest(question="需要采取什么措施？", request_id="req-citation-log"),
    )

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer"] == repaired_draft
    coverage_log = next(
        record for record in caplog.records if record.message == "RAG citation coverage incomplete"
    )
    assert coverage_log.request_id == "req-citation-log"  # type: ignore[attr-defined]
    assert coverage_log.error_code == (  # type: ignore[attr-defined]
        "rag_citation_coverage_incomplete"
    )
    details = coverage_log.details  # type: ignore[attr-defined]
    assert details["initial"]["draft"] == initial_draft
    assert details["repaired"]["draft"] == repaired_draft
    assert details["initial"]["uncited_segments"] == ["这里还有一个没有引用的具体操作要求。"]
    assert details["repaired"]["uncited_segments"] == ["这个具体操作要求仍然没有引用。"]
    assert details["chunks"][0] == {
        "citation_index": 1,
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "document_name": "fixture.txt",
    }
    saved = history.get_by_request_id("req-citation-log")
    assert saved is not None
    assert saved.status == "completed"
    assert saved.system_answer == repaired_draft
    assert saved.latency["synthesis_ms"] >= 0


@pytest.mark.asyncio
async def test_source_insufficiency_and_heading_do_not_trigger_citation_repair(
    tmp_path: Path,
) -> None:
    answer = (
        "根据提供的参考资料，无法直接给出‘生物安全’的完整定义，因为资料中未包含定义条款。"
        "\n\n参考资料中仅提供了相关要求：\n"
        "实验室应设立生物安全委员会并履行监督职责 [1]。"
        "\n\n由于现有资料缺乏完整定义，因此只能说明相关管理要求。"
    )
    llm = FakeLLM(['{"decision":"need_rag"}', answer])
    service, _ = _service(tmp_path, llm=llm, ragflow=FakeRAGFlow([_chunk()]))

    events = await _collect(
        service,
        QueryRequest(question="什么是生物安全？", request_id="req-source-insufficient"),
    )

    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["answer"] == answer
    assert len(llm.calls) == 2


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
