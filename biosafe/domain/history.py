"""History domain models and reference snapshot validation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class AnswerSource(StrEnum):
    INSTRUCTION = "instruction"
    DIRECT = "direct"
    RAG = "rag"
    ERROR = "error"
    SEED = "seed"


@dataclass(frozen=True)
class ReferenceSnapshot:
    chunk_id: str = ""
    dataset_id: str = ""
    dataset_name: str = ""
    document_id: str = ""
    document_name: str = ""
    content: str = ""
    page_numbers: list[int] = field(default_factory=list)
    positions: list[Any] = field(default_factory=list)
    similarity: float | None = None
    vector_similarity: float | None = None
    term_similarity: float | None = None
    source_url: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ReferenceSnapshot:
        known = {field_name for field_name in cls.__dataclass_fields__}
        cleaned = {key: item for key, item in value.items() if key in known}
        cleaned["raw_metadata"] = value.get("raw_metadata", value)
        return cls(**cleaned)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoryCreate:
    request_id: str
    session_id: str
    created_at: str
    experiment_id: str
    input_mode: str
    question: str
    answer_source: str
    system_answer: str
    corrected_answer: str = ""
    references: list[dict[str, Any]] = field(default_factory=list)
    ragflow_request: dict[str, Any] = field(default_factory=dict)
    latency: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    error_code: str = ""
    error_message: str = ""
    seed_fingerprint: str | None = None


@dataclass(frozen=True)
class ChatHistory:
    id: int
    request_id: str
    session_id: str
    created_at: str
    experiment_id: str
    input_mode: str
    question: str
    answer_source: str
    system_answer: str
    corrected_answer: str
    references: list[dict[str, Any]]
    ragflow_request: dict[str, Any]
    latency: dict[str, Any]
    status: str
    error_code: str
    error_message: str
    correction_updated_at: str | None = None


def decode_json_list(raw: str, *, field_name: str = "value") -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def decode_json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
