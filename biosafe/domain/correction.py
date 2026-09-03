"""Asynchronous answer correction domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CorrectionResult:
    can_answer: bool
    answer: str = ""
    cannot_answer_reason: str = ""
    citations: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerCorrection:
    id: int
    history_id: int
    question: str
    original_answer: str
    status: str
    model: str
    can_answer: bool | None
    answer: str
    cannot_answer_reason: str
    citations: list[dict[str, Any]]
    error: str
    enqueued_at: str
    started_at: str | None
    finished_at: str | None
