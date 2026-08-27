"""Domain models for text query orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class QueryStage(StrEnum):
    RECEIVED = "received"
    INSTRUCTION = "instruction"
    DIRECT_DECISION = "direct_decision"
    RETRIEVING = "retrieving"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class QueryRequest:
    question: str
    experiment_id: str = "generic"
    session_id: str = ""
    input_mode: str = "text"
    request_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class QueryEvent:
    event: str
    request_id: str
    sequence: int
    stage: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DirectDecision:
    decision: str
    answer: str = ""
    raw_response: str = ""


@dataclass(frozen=True)
class FuncCallResult:
    command: str
    confidence: float
    params: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QueryFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, answer_source: str = "error"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.answer_source = answer_source


class QueryCancelled(RuntimeError):
    pass
