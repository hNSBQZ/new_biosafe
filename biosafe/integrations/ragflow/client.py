"""RAGFlow REST adapter with normalized responses and stable failures."""

from __future__ import annotations

from typing import Any

import httpx

from biosafe.config import RAGFlowConfig
from biosafe.integrations.ragflow.models import Dataset, Document, RetrievedChunk


class RAGFlowError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class RAGFlowClient:
    def __init__(self, config: RAGFlowConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=config.timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> RAGFlowClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            await self.list_datasets(page_size=1)
            return True
        except RAGFlowError:
            return False

    async def list_datasets(self, page: int = 1, page_size: int = 100) -> list[Dataset]:
        data = await self._request(
            "GET", "/api/v1/datasets", params={"page": page, "page_size": page_size}
        )
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("datasets", items.get("items", []))
        return [self._dataset(item) for item in items or []]

    async def list_documents(
        self, dataset_id: str, page: int = 1, page_size: int = 100
    ) -> list[Document]:
        data = await self._request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/documents",
            params={"page": page, "page_size": page_size},
        )
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("docs", items.get("documents", items.get("items", [])))
        return [self._document(dataset_id, item) for item in items or []]

    async def retrieve(
        self,
        question: str,
        dataset_ids: list[str] | tuple[str, ...],
        *,
        page_size: int = 8,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
    ) -> list[RetrievedChunk]:
        payload = {
            "question": question,
            "dataset_ids": list(dataset_ids),
            "page": 1,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
        }
        data = await self._request("POST", "/api/v1/retrieval", json=payload)
        body = data.get("data", data) if isinstance(data, dict) else {}
        chunks = body.get("chunks", body.get("items", [])) if isinstance(body, dict) else body
        return [self._chunk(item) for item in chunks or []]

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.config.ready:
            raise RAGFlowError("ragflow_not_configured", "RAGFlow is not configured")
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise RAGFlowError("ragflow_timeout", "RAGFlow request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise RAGFlowError(
                "ragflow_http_error", "RAGFlow request failed", exc.response.status_code
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RAGFlowError("ragflow_unavailable", "RAGFlow response was unavailable") from exc
        if isinstance(payload, dict) and payload.get("code") not in (None, 0, 200):
            message = str(payload.get("message") or "RAGFlow API error")
            raise RAGFlowError("ragflow_api_error", message)
        return payload

    @staticmethod
    def _dataset(item: dict[str, Any]) -> Dataset:
        return Dataset(
            id=str(item.get("id", "")),
            name=str(item.get("name", "")),
            chunk_method=str(item.get("chunk_method") or item.get("parser_id") or "naive"),
            document_count=int(item.get("document_count") or item.get("doc_num") or 0),
            raw_metadata=dict(item),
        )

    @staticmethod
    def _document(dataset_id: str, item: dict[str, Any]) -> Document:
        return Document(
            id=str(item.get("id", "")),
            dataset_id=dataset_id,
            name=str(item.get("name", "")),
            status=str(item.get("status") or item.get("run") or "unknown"),
            chunk_count=int(item.get("chunk_count") or item.get("chunk_num") or 0),
            progress=float(item["progress"]) if item.get("progress") is not None else None,
            progress_message=str(item.get("progress_msg") or item.get("progress_message") or ""),
            raw_metadata=dict(item),
        )

    @staticmethod
    def _chunk(item: dict[str, Any]) -> RetrievedChunk:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        positions = (
            item.get("positions") or item.get("position_int") or metadata.get("positions") or []
        )
        pages = item.get("page_numbers") or metadata.get("page_numbers") or []
        if isinstance(pages, int):
            pages = [pages]
        return RetrievedChunk(
            chunk_id=str(item.get("id") or item.get("chunk_id") or ""),
            dataset_id=str(item.get("dataset_id") or ""),
            dataset_name=str(item.get("dataset_name") or ""),
            document_id=str(item.get("document_id") or item.get("doc_id") or ""),
            document_name=str(item.get("document_name") or item.get("doc_name") or ""),
            content=str(item.get("content") or item.get("content_with_weight") or ""),
            page_numbers=tuple(int(page) for page in pages if str(page).isdigit()),
            positions=tuple(positions if isinstance(positions, list) else [positions]),
            image_id=item.get("image_id"),
            similarity=_optional_float(item.get("similarity")),
            vector_similarity=_optional_float(item.get("vector_similarity")),
            term_similarity=_optional_float(item.get("term_similarity")),
            source_url=item.get("source_url") or metadata.get("source_url"),
            raw_metadata=dict(item),
        )


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None
