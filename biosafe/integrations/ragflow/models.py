"""Version-independent RAGFlow domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    chunk_method: str = "naive"
    document_count: int = 0
    embedding_model: str = ""
    permission: str = ""
    status: str = ""
    parser_config: dict[str, Any] = field(default_factory=dict, repr=False)
    raw_metadata: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Document:
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
    created_at: str | None = None
    updated_at: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class DownloadedDocument:
    content: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    dataset_id: str
    dataset_name: str
    document_id: str
    document_name: str
    content: str
    page_numbers: tuple[int, ...] = ()
    positions: tuple[Any, ...] = ()
    image_id: str | None = None
    similarity: float | None = None
    vector_similarity: float | None = None
    term_similarity: float | None = None
    source_url: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict, repr=False)
