"""RAGFlow REST adapter with normalized responses and stable failures."""

from __future__ import annotations

from pathlib import Path
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
        self._client: httpx.AsyncClient | None = None
        if config.ready:
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
        if self._client is not None:
            await self._client.aclose()

    async def health(self) -> bool:
        try:
            await self.list_datasets(page_size=1)
            return True
        except RAGFlowError:
            return False

    async def list_datasets(
        self,
        page: int = 1,
        page_size: int = 100,
        *,
        name: str | None = None,
        dataset_id: str | None = None,
        include_parsing_status: bool | None = None,
    ) -> list[Dataset]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if name is not None:
            params["name"] = name
        if dataset_id is not None:
            params["id"] = dataset_id
        if include_parsing_status is not None:
            params["include_parsing_status"] = "true" if include_parsing_status else "false"
        data = await self._request(
            "GET",
            "/api/v1/datasets",
            params=params,
        )
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("datasets", items.get("items", []))
        return [self._dataset(item) for item in items or []]

    async def create_dataset(
        self,
        name: str,
        *,
        chunk_method: str | None = None,
        parser_config: dict[str, Any] | None = None,
        embedding_model: str | None = None,
        permission: str | None = None,
        avatar: str | None = None,
        description: str | None = None,
        parse_type: int | None = None,
        pipeline_id: str | None = None,
    ) -> Dataset:
        payload: dict[str, Any] = {"name": name}
        if chunk_method is not None:
            payload["chunk_method"] = chunk_method
        if parser_config is not None:
            payload["parser_config"] = parser_config
        if embedding_model is not None:
            payload["embedding_model"] = embedding_model
        if permission is not None:
            payload["permission"] = permission
        if avatar is not None:
            payload["avatar"] = avatar
        if description is not None:
            payload["description"] = description
        if parse_type is not None:
            payload["parse_type"] = parse_type
        if pipeline_id is not None:
            payload["pipeline_id"] = pipeline_id
        data = await self._request("POST", "/api/v1/datasets", json=payload)
        body = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(body, dict):
            raise RAGFlowError("ragflow_api_error", "RAGFlow dataset response was invalid")
        return self._dataset(body)

    async def delete_owned_dataset(self, dataset_id: str) -> None:
        await self._request("DELETE", "/api/v1/datasets", json={"ids": [dataset_id]})

    async def list_documents(
        self,
        dataset_id: str,
        page: int = 1,
        page_size: int = 100,
        *,
        keywords: str | None = None,
        document_id: str | None = None,
        name: str | None = None,
        run: str | None = None,
        suffix: str | None = None,
    ) -> list[Document]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if keywords is not None:
            params["keywords"] = keywords
        if document_id is not None:
            params["id"] = document_id
        if name is not None:
            params["name"] = name
        if run is not None:
            params["run"] = run
        if suffix is not None:
            params["suffix"] = suffix
        data = await self._request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/documents",
            params=params,
        )
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("docs", items.get("documents", items.get("items", [])))
        return [self._document(dataset_id, item) for item in items or []]

    async def upload_document(
        self,
        dataset_id: str,
        file_path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> list[Document]:
        path = Path(file_path)
        guessed_name = filename or path.name
        guessed_type = content_type or _guess_content_type(path)
        data = path.read_bytes()
        files = [("file", (guessed_name, data, guessed_type))]
        response = await self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/documents",
            files=files,
        )
        items = response.get("data", response) if isinstance(response, dict) else response
        return [self._document(dataset_id, item) for item in items or []]

    async def delete_owned_document(self, dataset_id: str, document_id: str) -> None:
        await self._request(
            "DELETE",
            f"/api/v1/datasets/{dataset_id}/documents",
            json={"ids": [document_id]},
        )

    async def start_parse(self, dataset_id: str, document_ids: list[str] | tuple[str, ...]) -> None:
        await self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json={"document_ids": list(document_ids)},
        )

    async def cancel_parse(
        self, dataset_id: str, document_ids: list[str] | tuple[str, ...]
    ) -> None:
        await self._request(
            "DELETE",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json={"document_ids": list(document_ids)},
        )

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
        if self._client is None:
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
            embedding_model=str(item.get("embedding_model") or ""),
            permission=str(item.get("permission") or ""),
            status=str(item.get("status") or item.get("run") or ""),
            parser_config=(
                item["parser_config"]
                if isinstance(item.get("parser_config"), dict)
                else {}
            ),
            raw_metadata=dict(item),
        )

    @staticmethod
    def _document(dataset_id: str, item: dict[str, Any]) -> Document:
        return Document(
            id=str(item.get("id", "")),
            dataset_id=str(item.get("dataset_id") or item.get("knowledgebase_id") or dataset_id),
            name=str(item.get("name", "")),
            status=str(item.get("run") or item.get("status") or "unknown"),
            chunk_count=int(item.get("chunk_count") or item.get("chunk_num") or 0),
            progress=float(item["progress"]) if item.get("progress") is not None else None,
            progress_message=str(item.get("progress_msg") or item.get("progress_message") or ""),
            location=str(item.get("location") or ""),
            size=int(item.get("size") or 0),
            source_type=str(item.get("source_type") or ""),
            document_type=str(item.get("type") or ""),
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
            dataset_id=_first_text(
                item, metadata, "dataset_id", "knowledgebase_id", "kb_id"
            ),
            dataset_name=_first_text(item, metadata, "dataset_name", "knowledgebase_name"),
            document_id=str(item.get("document_id") or item.get("doc_id") or ""),
            document_name=_first_text(
                item,
                metadata,
                "document_name",
                "doc_name",
                "document_keyword",
                "docnm_kw",
            ),
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


def _first_text(item: dict[str, Any], metadata: dict[str, Any], *keys: str) -> str:
    for source in (item, metadata):
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix in {".txt", ".md", ".rst"}:
        return "text/plain"
    if suffix in {".docx"}:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"
