from __future__ import annotations

from typing import Any, Literal

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


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    experiment_id: str = Field(default="generic", max_length=128)
    session_id: str = Field(default="", max_length=128)
    input_mode: Literal["text"] = "text"


class ExperimentItem(BaseModel):
    id: str
    title: str
    step_count: int
    knowledge_point_count: int


class ExperimentPage(BaseModel):
    items: list[ExperimentItem]
