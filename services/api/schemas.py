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


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    username: str
    expires_at: str


class KnowledgeDatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    chunk_method: str = Field(default="naive", max_length=32)
    parser_config: dict[str, Any] = Field(default_factory=dict)
    embedding_model: str = Field(default="", max_length=255)
    permission: str = Field(default="", max_length=64)
    avatar: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=2000)
    parse_type: int | None = None
    pipeline_id: str = Field(default="", max_length=255)


class KnowledgeDatasetItem(BaseModel):
    id: str
    name: str
    chunk_method: str = "naive"
    document_count: int = 0
    embedding_model: str = ""
    permission: str = ""
    status: str = ""
    parser_config: dict[str, Any] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDatasetPage(BaseModel):
    items: list[KnowledgeDatasetItem]


class KnowledgeDocumentItem(BaseModel):
    id: str
    dataset_id: str
    name: str
    status: str = "unknown"
    chunk_count: int = 0
    progress: float | None = None
    progress_message: str = ""
    location: str = ""
    size: int = 0
    source_type: str = ""
    document_type: str = ""
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocumentPage(BaseModel):
    items: list[KnowledgeDocumentItem]


class KnowledgeChunkItem(BaseModel):
    citation_index: int | None = None
    chunk_id: str
    dataset_id: str
    dataset_name: str
    document_id: str
    document_name: str
    content: str
    page_numbers: list[int] = Field(default_factory=list)
    positions: list[Any] = Field(default_factory=list)
    image_id: str | None = None
    similarity: float | None = None
    vector_similarity: float | None = None
    term_similarity: float | None = None
    source_url: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRetrievalPreviewRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    dataset_ids: list[str] = Field(min_length=1)
    page_size: int = Field(default=8, ge=1, le=50)
    similarity_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    vector_similarity_weight: float = Field(default=0.3, ge=0.0, le=1.0)


class KnowledgeRetrievalPreviewResponse(BaseModel):
    question: str
    dataset_ids: list[str]
    chunks: list[KnowledgeChunkItem]
