"""Text query state machine for instruction, direct and RAGFlow paths."""

from __future__ import annotations

import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from biosafe.application.correction_dispatcher import CorrectionDispatcherProtocol
from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.domain.history import AnswerSource, HistoryCreate
from biosafe.domain.query import (
    DirectDecision,
    FuncCallResult,
    QueryCancelled,
    QueryEvent,
    QueryFailure,
    QueryStage,
)
from biosafe.domain.query import QueryRequest as DomainQueryRequest
from biosafe.integrations.llm import ChatLLMProtocol, LLMError
from biosafe.integrations.ragflow import RAGFlowClient, RAGFlowError
from biosafe.integrations.ragflow.models import RetrievedChunk
from biosafe.storage.admin_repository import BindingRepository
from biosafe.storage.history_repository import HistoryRepository

logger = logging.getLogger(__name__)

CancelChecker = Callable[[], bool | Awaitable[bool]]

_CITATION_PATTERN = re.compile(r"\[(\d{1,3})\]")
_ANSWER_SEGMENT_PATTERN = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?|\n")
_FUNCALL_COMMANDS = frozenset(
    {
        "ShowProcedurePanel",
        "CurrentExperimentOperation",
        "ShowEquipmentName",
        "SwitchExperimentScene",
    }
)
_MIN_FUNCALL_CONFIDENCE = 0.8

_RAG_SYSTEM_PROMPT = (
    "你是一名生物安全领域的专业助手。请严格根据参考资料回答用户问题。\n\n"
    "规则：\n"
    "1. 只能使用参考资料中的信息，不要编造来源或事实。\n"
    "2. 每个可核查的事实、数字、操作要求、风险和结论都必须在该句末尾立即使用 "
    "[n] 引用，n 对应参考资料编号。\n"
    "3. 不要只在段落末尾放一个总引用；同一资料支持多个句子时，每个句子都重复标注。"
    "多个资料共同支持时写成 [1][2]。\n"
    "4. 如果资料不足以回答，请说明资料不足，并引用能支持该判断的资料。\n"
    "5. 回答使用中文自然句，避免 Markdown 标题、项目符号和链接；"
    "不得输出参考资料中不存在的文档名。\n"
)


class QueryService:
    def __init__(
        self,
        *,
        history_repository: HistoryRepository,
        binding_repository: BindingRepository,
        prompt_store: ExperimentPromptStore,
        llm_client: ChatLLMProtocol,
        ragflow_client: RAGFlowClient,
        default_dataset_ids: tuple[str, ...] = (),
        retrieval_page_size: int = 8,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        correction_dispatcher: CorrectionDispatcherProtocol | None = None,
    ):
        self._history_repository = history_repository
        self._binding_repository = binding_repository
        self._prompt_store = prompt_store
        self._llm = llm_client
        self._ragflow = ragflow_client
        self._default_dataset_ids = tuple(default_dataset_ids)
        self._retrieval_page_size = retrieval_page_size
        self._similarity_threshold = similarity_threshold
        self._vector_similarity_weight = vector_similarity_weight
        self._correction_dispatcher = correction_dispatcher

    async def answer_text(
        self,
        request: DomainQueryRequest,
        *,
        cancel_requested: CancelChecker | None = None,
    ):
        sequence = 0
        started_at = perf_counter()
        latency: dict[str, Any] = {}
        answer_source = AnswerSource.ERROR.value
        system_answer = ""
        references: list[dict[str, Any]] = []
        ragflow_request: dict[str, Any] = {}
        current_stage = QueryStage.RECEIVED.value

        def make_event(event: str, stage: QueryStage | str, data: dict[str, Any]) -> QueryEvent:
            nonlocal sequence, current_stage
            sequence += 1
            current_stage = stage.value if isinstance(stage, QueryStage) else stage
            return QueryEvent(
                event=event,
                request_id=request.request_id,
                sequence=sequence,
                stage=current_stage,
                data=data,
            )

        async def check_cancelled() -> None:
            if cancel_requested is None:
                return
            value = cancel_requested()
            if inspect.isawaitable(value):
                value = await value
            if value:
                raise QueryCancelled()

        try:
            if not request.question.strip():
                raise QueryFailure("question_empty", "Question is empty")

            yield make_event(
                "stage",
                QueryStage.RECEIVED,
                {
                    "question": request.question,
                    "experiment_id": request.experiment_id,
                    "input_mode": request.input_mode,
                },
            )
            await check_cancelled()

            yield make_event("stage", QueryStage.DIRECT_DECISION, {})
            decision_started = perf_counter()
            decision, fallback_reason = await self._direct_decision(request)
            latency["direct_decision_ms"] = _elapsed_ms(decision_started)
            yield make_event(
                "stage_result",
                QueryStage.DIRECT_DECISION,
                {
                    "decision": decision.decision,
                    "fallback_reason": fallback_reason or "",
                },
            )
            await check_cancelled()

            if decision.decision == "func_call" and decision.func_call is not None:
                yield make_event("stage", QueryStage.INSTRUCTION, {})
                funcall = decision.func_call
                answer_source = AnswerSource.INSTRUCTION.value
                system_answer = json.dumps(
                    {"type": "FuncCall", **funcall.to_dict()},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                history = self._write_history(
                    request=request,
                    answer_source=answer_source,
                    system_answer=system_answer,
                    references=references,
                    ragflow_request=ragflow_request,
                    latency=latency,
                    status="completed",
                )
                yield make_event(
                    "completed",
                    QueryStage.COMPLETED,
                    {
                        "answer_source": answer_source,
                        "func_call": funcall.to_dict(),
                        "history_id": history.id,
                    },
                )
                return

            if decision.decision == "direct":
                answer_source = AnswerSource.DIRECT.value
                system_answer = decision.answer
                latency["total_ms"] = _elapsed_ms(started_at)
                history = self._write_history(
                    request=request,
                    answer_source=answer_source,
                    system_answer=system_answer,
                    references=references,
                    ragflow_request=ragflow_request,
                    latency=latency,
                    status="completed",
                )
                yield make_event(
                    "completed",
                    QueryStage.COMPLETED,
                    {
                        "answer_source": answer_source,
                        "answer": system_answer,
                        "references": references,
                        "history_id": history.id,
                    },
                )
                return

            answer_source = AnswerSource.RAG.value
            dataset_ids = self._dataset_ids_for_experiment(request.experiment_id)
            ragflow_request = self._retrieval_request(request.question, dataset_ids)
            if not dataset_ids:
                raise QueryFailure(
                    "ragflow_dataset_not_configured",
                    "No RAGFlow dataset is configured for this experiment",
                    answer_source=answer_source,
                )

            yield make_event("stage", QueryStage.RETRIEVING, {"dataset_ids": dataset_ids})
            retrieval_started = perf_counter()
            chunks = await self._retrieve(request.question, dataset_ids)
            latency["retrieval_ms"] = _elapsed_ms(retrieval_started)
            yield make_event(
                "stage_result",
                QueryStage.RETRIEVING,
                {"chunk_count": len(chunks)},
            )
            await check_cancelled()
            if not chunks:
                raise QueryFailure(
                    "ragflow_empty_retrieval",
                    "RAGFlow returned no chunks for the original question",
                    answer_source=answer_source,
                )

            yield make_event("stage", QueryStage.SYNTHESIZING, {"chunk_count": len(chunks)})
            synthesis_started = perf_counter()
            try:
                system_answer = await self._synthesize(
                    request.question,
                    chunks,
                    request_id=request.request_id,
                )
            finally:
                latency["synthesis_ms"] = _elapsed_ms(synthesis_started)
            citation_numbers = _citation_numbers(system_answer)
            references = _references_for_citations(chunks, citation_numbers)
            latency["total_ms"] = _elapsed_ms(started_at)
            history = self._write_history(
                request=request,
                answer_source=answer_source,
                system_answer=system_answer,
                references=references,
                ragflow_request=ragflow_request,
                latency=latency,
                status="completed",
            )
            yield make_event(
                "completed",
                QueryStage.COMPLETED,
                {
                    "answer_source": answer_source,
                    "answer": system_answer,
                    "references": references,
                    "history_id": history.id,
                },
            )
        except QueryCancelled:
            latency["total_ms"] = _elapsed_ms(started_at)
            history = self._write_history(
                request=request,
                answer_source=answer_source,
                system_answer=system_answer,
                references=references,
                ragflow_request=ragflow_request,
                latency=latency,
                status="cancelled",
                error_code="cancelled",
                error_message="Request was cancelled",
            )
            yield make_event(
                "cancelled",
                QueryStage.CANCELLED,
                {
                    "answer_source": answer_source,
                    "history_id": history.id,
                    "stage": current_stage,
                },
            )
        except QueryFailure as exc:
            latency["total_ms"] = _elapsed_ms(started_at)
            history = self._write_history(
                request=request,
                answer_source=exc.answer_source,
                system_answer=system_answer,
                references=references,
                ragflow_request=ragflow_request,
                latency=latency,
                status="failed",
                error_code=exc.code,
                error_message=exc.message,
            )
            logger.warning(
                "query failed",
                extra={
                    "request_id": request.request_id,
                    "stage": current_stage,
                    "error_code": exc.code,
                    "details": {
                        "history_id": history.id,
                        "answer_source": exc.answer_source,
                        "input_mode": request.input_mode,
                        "experiment_id": request.experiment_id,
                        "question": request.question,
                        "latency": latency,
                        "ragflow_request": ragflow_request,
                    },
                },
            )
            yield make_event(
                "failed",
                QueryStage.FAILED,
                {
                    "answer_source": exc.answer_source,
                    "code": exc.code,
                    "message": exc.message,
                    "history_id": history.id,
                },
            )
        except Exception:
            logger.exception("query service failed unexpectedly")
            latency["total_ms"] = _elapsed_ms(started_at)
            history = self._write_history(
                request=request,
                answer_source=AnswerSource.ERROR.value,
                system_answer=system_answer,
                references=references,
                ragflow_request=ragflow_request,
                latency=latency,
                status="failed",
                error_code="query_internal_error",
                error_message="Query service failed unexpectedly",
            )
            yield make_event(
                "failed",
                QueryStage.FAILED,
                {
                    "answer_source": AnswerSource.ERROR.value,
                    "code": "query_internal_error",
                    "message": "Query service failed unexpectedly",
                    "history_id": history.id,
                },
            )

    async def _direct_decision(
        self, request: DomainQueryRequest
    ) -> tuple[DirectDecision, str | None]:
        messages = self._prompt_store.build_messages(request.experiment_id, request.question)
        try:
            raw_response = await self._llm.complete(
                messages,
                max_tokens=256,
                temperature=0.0,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except LLMError as exc:
            logger.info("direct decision fell back to RAG: %s", exc.code)
            return DirectDecision(decision="need_rag"), exc.code
        return _parse_direct_decision(raw_response), None

    async def _retrieve(self, question: str, dataset_ids: list[str]) -> list[RetrievedChunk]:
        try:
            return await self._ragflow.retrieve(
                question,
                dataset_ids,
                page_size=self._retrieval_page_size,
                similarity_threshold=self._similarity_threshold,
                vector_similarity_weight=self._vector_similarity_weight,
            )
        except RAGFlowError as exc:
            raise QueryFailure(exc.code, str(exc), answer_source=AnswerSource.RAG.value) from exc

    async def _synthesize(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        request_id: str,
    ) -> str:
        try:
            answer = await self._llm.complete(
                _build_rag_messages(question, chunks),
                max_tokens=1024,
                temperature=0.0,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except LLMError as exc:
            raise QueryFailure(exc.code, exc.message, answer_source=AnswerSource.RAG.value) from exc

        citation_numbers = _citation_numbers(answer)
        if not citation_numbers:
            self._log_citation_issue(
                message="RAG citation validation failed",
                request_id=request_id,
                question=question,
                code="rag_citation_missing",
                chunks=chunks,
                initial_draft=answer,
            )
            raise QueryFailure(
                "rag_citation_missing",
                "Synthesized answer did not include a verifiable citation",
                answer_source=AnswerSource.RAG.value,
            )
        invalid = [number for number in citation_numbers if number < 1 or number > len(chunks)]
        if invalid:
            self._log_citation_issue(
                message="RAG citation validation failed",
                request_id=request_id,
                question=question,
                code="rag_citation_invalid",
                chunks=chunks,
                initial_draft=answer,
            )
            raise QueryFailure(
                "rag_citation_invalid",
                "Synthesized answer cited a chunk that was not retrieved",
                answer_source=AnswerSource.RAG.value,
            )
        uncited_segments = _uncited_answer_segments(answer)
        if uncited_segments:
            initial_draft = answer
            answer = await self._repair_citations(question, chunks, answer)
            citation_numbers = _citation_numbers(answer)
            invalid = [number for number in citation_numbers if number < 1 or number > len(chunks)]
            if not citation_numbers:
                self._log_citation_issue(
                    message="RAG citation validation failed",
                    request_id=request_id,
                    question=question,
                    code="rag_citation_missing",
                    chunks=chunks,
                    initial_draft=initial_draft,
                    repaired_draft=answer,
                )
                raise QueryFailure(
                    "rag_citation_missing",
                    "Synthesized answer did not include a verifiable citation",
                    answer_source=AnswerSource.RAG.value,
                )
            if invalid:
                self._log_citation_issue(
                    message="RAG citation validation failed",
                    request_id=request_id,
                    question=question,
                    code="rag_citation_invalid",
                    chunks=chunks,
                    initial_draft=initial_draft,
                    repaired_draft=answer,
                )
                raise QueryFailure(
                    "rag_citation_invalid",
                    "Synthesized answer cited a chunk that was not retrieved",
                    answer_source=AnswerSource.RAG.value,
                )
            if _uncited_answer_segments(answer):
                self._log_citation_issue(
                    message="RAG citation coverage incomplete",
                    request_id=request_id,
                    question=question,
                    code="rag_citation_coverage_incomplete",
                    chunks=chunks,
                    initial_draft=initial_draft,
                    repaired_draft=answer,
                )
        return answer

    def _log_citation_issue(
        self,
        *,
        message: str,
        request_id: str,
        question: str,
        code: str,
        chunks: list[RetrievedChunk],
        initial_draft: str,
        repaired_draft: str | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "question": question,
            "initial": _citation_diagnostics(initial_draft, chunks),
            "chunks": [
                {
                    "citation_index": index,
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "document_name": chunk.document_name,
                }
                for index, chunk in enumerate(chunks, start=1)
            ],
        }
        if repaired_draft is not None:
            details["repaired"] = _citation_diagnostics(repaired_draft, chunks)
        logger.warning(
            message,
            extra={
                "request_id": request_id,
                "stage": QueryStage.SYNTHESIZING.value,
                "error_code": code,
                "details": details,
            },
        )

    async def _repair_citations(
        self, question: str, chunks: list[RetrievedChunk], draft: str
    ) -> str:
        messages = _build_rag_messages(question, chunks)
        messages.extend(
            [
                {"role": "assistant", "content": draft},
                {
                    "role": "user",
                    "content": (
                        "上面的草稿有可核查句子缺少就近引用。请只依据同一批参考资料重写，"
                        "让每个事实、数字、操作要求、风险和结论所在句都以有效 [n] 结尾。"
                        "不要增加新事实，也不要输出解释过程。"
                    ),
                },
            ]
        )
        try:
            return await self._llm.complete(
                messages,
                max_tokens=1024,
                temperature=0.0,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except LLMError as exc:
            raise QueryFailure(exc.code, exc.message, answer_source=AnswerSource.RAG.value) from exc

    def _dataset_ids_for_experiment(self, experiment_id: str) -> list[str]:
        bindings = self._binding_repository.list_for_experiment(experiment_id)
        if bindings:
            return [str(row["dataset_id"]) for row in bindings if row.get("dataset_id")]
        return list(self._default_dataset_ids)

    def default_retrieval_request(self, question: str) -> dict[str, Any]:
        return self._retrieval_request(question, list(self._default_dataset_ids))

    def _retrieval_request(self, question: str, dataset_ids: list[str]) -> dict[str, Any]:
        return {
            "question": question,
            "dataset_ids": dataset_ids,
            "page_size": self._retrieval_page_size,
            "similarity_threshold": self._similarity_threshold,
            "vector_similarity_weight": self._vector_similarity_weight,
        }

    def _write_history(
        self,
        *,
        request: DomainQueryRequest,
        answer_source: str,
        system_answer: str,
        references: list[dict[str, Any]],
        ragflow_request: dict[str, Any],
        latency: dict[str, Any],
        status: str,
        error_code: str = "",
        error_message: str = "",
    ):
        history = self._history_repository.create(
            HistoryCreate(
                request_id=request.request_id,
                session_id=request.session_id,
                created_at=datetime.now(UTC).isoformat(),
                experiment_id=request.experiment_id,
                input_mode=request.input_mode,
                question=request.question,
                answer_source=answer_source,
                system_answer=system_answer,
                references=references,
                ragflow_request=ragflow_request,
                latency=latency,
                status=status,
                error_code=error_code,
                error_message=error_message,
            )
        )
        if (
            self._correction_dispatcher is not None
            and status == "completed"
            and answer_source in {AnswerSource.DIRECT.value, AnswerSource.RAG.value}
            and system_answer.strip()
        ):
            try:
                self._correction_dispatcher.submit(history)
            except Exception:
                logger.exception(
                    "answer correction submission failed",
                    extra={"request_id": request.request_id, "details": {"history_id": history.id}},
                )
        return history


def _parse_direct_decision(raw_response: str) -> DirectDecision:
    try:
        payload = json.loads(raw_response.strip())
    except (json.JSONDecodeError, AttributeError):
        return DirectDecision(decision="need_rag", raw_response=raw_response)

    if not isinstance(payload, dict):
        return DirectDecision(decision="need_rag", raw_response=raw_response)
    if payload.get("decision") == "direct" and str(payload.get("answer") or "").strip():
        return DirectDecision(
            decision="direct",
            answer=str(payload["answer"]).strip(),
            raw_response=raw_response,
        )
    if payload.get("decision") == "func_call":
        func_call = _parse_func_call(payload.get("func_call"))
        if func_call is not None:
            return DirectDecision(
                decision="func_call",
                func_call=func_call,
                raw_response=raw_response,
            )
    return DirectDecision(decision="need_rag", raw_response=raw_response)


def _parse_func_call(value: Any) -> FuncCallResult | None:
    if not isinstance(value, dict):
        return None
    command = value.get("command")
    confidence = value.get("confidence")
    params = value.get("params")
    if not isinstance(command, str) or command not in _FUNCALL_COMMANDS:
        return None
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not _MIN_FUNCALL_CONFIDENCE <= float(confidence) <= 1.0
    ):
        return None
    if params != {}:
        return None
    return FuncCallResult(
        command=str(command),
        confidence=float(confidence),
        params={},
    )


def _build_rag_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context_parts = []
    for index, chunk in enumerate(chunks, start=1):
        location = ""
        if chunk.page_numbers:
            location = f" 页码:{','.join(str(page) for page in chunk.page_numbers)}"
        header = f"[{index}] 文档:{chunk.document_name or chunk.document_id}{location}"
        content = chunk.content[:4000]
        context_parts.append(f"{header}\n{content}")
    return [
        {"role": "system", "content": _RAG_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "参考资料：\n"
            + "\n\n".join(context_parts)
            + f"\n\n用户原始问题：{question}",
        },
    ]


def _citation_numbers(answer: str) -> list[int]:
    return [int(match) for match in _CITATION_PATTERN.findall(answer or "")]


def _uncited_answer_segments(answer: str) -> list[str]:
    uncited: list[str] = []
    for match in _ANSWER_SEGMENT_PATTERN.finditer(answer or ""):
        segment = match.group(0).strip()
        if not segment or _CITATION_PATTERN.search(segment):
            continue
        plain = _CITATION_PATTERN.sub("", segment)
        if _is_citation_exempt_segment(plain):
            continue
        substantive_chars = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", plain)
        if len(substantive_chars) >= 8:
            uncited.append(segment)
    return uncited


def _is_citation_exempt_segment(segment: str) -> bool:
    normalized = re.sub(r"[\s*_#]+", "", segment).strip()
    if normalized.endswith(("：", ":")):
        return True
    source_terms = ("参考资料", "现有资料", "检索资料", "提供的资料", "资料中")
    insufficiency_terms = ("不足", "缺乏", "未包含", "未提供", "没有", "无法")
    return any(term in normalized for term in source_terms) and any(
        term in normalized for term in insufficiency_terms
    )


def _citation_diagnostics(answer: str, chunks: list[RetrievedChunk]) -> dict[str, Any]:
    citation_numbers = _citation_numbers(answer)
    return {
        "draft": answer,
        "citation_numbers": citation_numbers,
        "invalid_citation_numbers": [
            number for number in citation_numbers if number < 1 or number > len(chunks)
        ],
        "uncited_segments": _uncited_answer_segments(answer),
    }


def _references_for_citations(
    chunks: list[RetrievedChunk], citation_numbers: list[int]
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[int] = set()
    for number in citation_numbers:
        if number in seen:
            continue
        seen.add(number)
        chunk = chunks[number - 1]
        snapshot = asdict(chunk)
        snapshot["page_numbers"] = list(chunk.page_numbers)
        snapshot["positions"] = list(chunk.positions)
        snapshot["citation_index"] = number
        references.append(snapshot)
    return references


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)
