from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int


class CorrectionRequest(BaseModel):
    corrected_answer: str = Field(max_length=20_000)
