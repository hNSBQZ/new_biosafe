"""Admin login and RAGFlow knowledge management routes."""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from biosafe.auth import decode_admin_token, issue_admin_token, verify_password
from biosafe.integrations.ragflow import RAGFlowClient, RAGFlowError
from biosafe.integrations.ragflow.models import Dataset, Document, RetrievedChunk
from biosafe.storage.admin_repository import AdminRepository
from services.api.deps import get_admin_repository
from services.api.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    KnowledgeChunkItem,
    KnowledgeDatasetCreateRequest,
    KnowledgeDatasetItem,
    KnowledgeDatasetPage,
    KnowledgeDocumentItem,
    KnowledgeDocumentPage,
    KnowledgeRetrievalPreviewRequest,
    KnowledgeRetrievalPreviewResponse,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
AdminRepo = Annotated[AdminRepository, Depends(get_admin_repository)]
DEV_DATASET_PREFIX = "biosafe-dev-"


async def _require_admin(request: Request, repository: AdminRepo) -> str:
    settings = request.app.state.settings
    if not settings.admin.token_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "admin_auth_not_configured"},
        )
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "admin_unauthorized"},
        )
    payload = decode_admin_token(authorization[7:].strip(), settings.admin.token_secret)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "admin_unauthorized"},
        )
    row = repository.get(payload.username)
    if row is None or not int(row.get("enabled", 0)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "admin_unauthorized"},
        )
    return payload.username


@router.post("/login", response_model=AdminLoginResponse)
async def login(
    payload: AdminLoginRequest,
    request: Request,
    repository: AdminRepo,
) -> AdminLoginResponse:
    settings = request.app.state.settings
    if not settings.admin.password or not settings.admin.token_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "admin_auth_not_configured"},
        )
    row = repository.get(payload.username)
    if row is None or not int(row.get("enabled", 0)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "admin_login_failed"},
        )
    if not verify_password(payload.password, str(row.get("password_hash") or "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "admin_login_failed"},
        )
    token = issue_admin_token(
        payload.username,
        settings.admin.token_secret,
        settings.admin.token_ttl_seconds,
    )
    expires_at = datetime.now(UTC) + timedelta(
        seconds=settings.admin.token_ttl_seconds,
    )
    return AdminLoginResponse(
        access_token=token,
        username=payload.username,
        expires_at=expires_at.isoformat(),
    )


@router.get("/knowledge/datasets", response_model=KnowledgeDatasetPage)
async def list_datasets(
    request: Request,
    _: str = Depends(_require_admin),
    include_parsing_status: bool = True,
    name: str | None = None,
    dataset_id: str | None = None,
) -> KnowledgeDatasetPage:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        datasets = await client.list_datasets(
            name=name,
            dataset_id=dataset_id,
            include_parsing_status=include_parsing_status,
        )
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return KnowledgeDatasetPage(
        items=[
            _dataset_item(dataset)
            for dataset in datasets
            if _is_dev_namespace(dataset.name)
        ]
    )


@router.post("/knowledge/datasets", response_model=KnowledgeDatasetItem)
async def create_dataset(
    payload: KnowledgeDatasetCreateRequest,
    request: Request,
    _: str = Depends(_require_admin),
) -> KnowledgeDatasetItem:
    if not _is_dev_namespace(payload.name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ragflow_forbidden",
                "message": "Dataset name must start with biosafe-dev-",
            },
        )
    client: RAGFlowClient = request.app.state.ragflow_client
    parser_config = payload.parser_config or _default_parser_config(payload.chunk_method)
    try:
        dataset = await client.create_dataset(
            payload.name,
            chunk_method=payload.chunk_method,
            parser_config=parser_config,
            embedding_model=payload.embedding_model or None,
            permission=payload.permission or None,
            avatar=payload.avatar or None,
            description=payload.description or None,
            parse_type=payload.parse_type,
            pipeline_id=payload.pipeline_id or None,
        )
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return _dataset_item(dataset)


@router.delete("/knowledge/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    request: Request,
    _: str = Depends(_require_admin),
) -> dict[str, bool]:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        await _require_owned_dataset(client, dataset_id)
        await client.delete_owned_dataset(dataset_id)
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return {"ok": True}


@router.get("/knowledge/datasets/{dataset_id}/documents", response_model=KnowledgeDocumentPage)
async def list_documents(
    dataset_id: str,
    request: Request,
    _: str = Depends(_require_admin),
    page: int = 1,
    page_size: int = 100,
    run: str | None = None,
    name: str | None = None,
) -> KnowledgeDocumentPage:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        await _require_owned_dataset(client, dataset_id)
        documents = await client.list_documents(
            dataset_id,
            page=page,
            page_size=page_size,
            run=run,
            name=name,
        )
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return KnowledgeDocumentPage(items=[_document_item(document) for document in documents])


@router.post("/knowledge/datasets/{dataset_id}/documents", response_model=KnowledgeDocumentPage)
async def upload_document(
    dataset_id: str,
    file: Annotated[UploadFile, File(...)],
    request: Request,
    _: str = Depends(_require_admin),
) -> KnowledgeDocumentPage:
    client: RAGFlowClient = request.app.state.ragflow_client
    temp_path: Path | None = None
    try:
        await _require_owned_dataset(client, dataset_id)
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=Path(file.filename or "upload").suffix,
        ) as tmp:
            tmp.write(await file.read())
            temp_path = Path(tmp.name)
        try:
            documents = await client.upload_document(
                dataset_id,
                temp_path,
                filename=file.filename or temp_path.name,
                content_type=file.content_type,
            )
        except RAGFlowError as exc:
            _raise_ragflow_error(exc)
        return KnowledgeDocumentPage(items=[_document_item(document) for document in documents])
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.post(
    "/knowledge/datasets/{dataset_id}/documents/{document_id}/parse",
    response_model=KnowledgeDocumentItem,
)
async def parse_document(
    dataset_id: str,
    document_id: str,
    request: Request,
    _: str = Depends(_require_admin),
) -> KnowledgeDocumentItem:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        await _require_owned_dataset(client, dataset_id)
        await client.start_parse(dataset_id, [document_id])
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return await _load_document(dataset_id, document_id, request)


@router.post(
    "/knowledge/datasets/{dataset_id}/documents/{document_id}/retry",
    response_model=KnowledgeDocumentItem,
)
async def retry_document(
    dataset_id: str,
    document_id: str,
    request: Request,
    _: str = Depends(_require_admin),
) -> KnowledgeDocumentItem:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        await _require_owned_dataset(client, dataset_id)
        await client.start_parse(dataset_id, [document_id])
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return await _load_document(dataset_id, document_id, request)


@router.post(
    "/knowledge/datasets/{dataset_id}/documents/{document_id}/cancel",
    response_model=KnowledgeDocumentItem,
)
async def cancel_document(
    dataset_id: str,
    document_id: str,
    request: Request,
    _: str = Depends(_require_admin),
) -> KnowledgeDocumentItem:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        await _require_owned_dataset(client, dataset_id)
        await client.cancel_parse(dataset_id, [document_id])
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return await _load_document(dataset_id, document_id, request)


@router.delete("/knowledge/datasets/{dataset_id}/documents/{document_id}")
async def delete_document(
    dataset_id: str,
    document_id: str,
    request: Request,
    _: str = Depends(_require_admin),
) -> dict[str, bool]:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        await _require_owned_dataset(client, dataset_id)
        await client.delete_owned_document(dataset_id, document_id)
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return {"ok": True}


@router.post("/knowledge/retrieval-preview", response_model=KnowledgeRetrievalPreviewResponse)
async def retrieval_preview(
    payload: KnowledgeRetrievalPreviewRequest,
    request: Request,
    _: str = Depends(_require_admin),
) -> KnowledgeRetrievalPreviewResponse:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        for dataset_id in payload.dataset_ids:
            await _require_owned_dataset(client, dataset_id)
        chunks = await client.retrieve(
            payload.question,
            payload.dataset_ids,
            page_size=payload.page_size,
            similarity_threshold=payload.similarity_threshold,
            vector_similarity_weight=payload.vector_similarity_weight,
        )
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return KnowledgeRetrievalPreviewResponse(
        question=payload.question,
        dataset_ids=list(payload.dataset_ids),
        chunks=[_chunk_item(chunk, index) for index, chunk in enumerate(chunks, start=1)],
    )


async def _load_document(
    dataset_id: str,
    document_id: str,
    request: Request,
) -> KnowledgeDocumentItem:
    client: RAGFlowClient = request.app.state.ragflow_client
    documents = await client.list_documents(dataset_id, document_id=document_id, page_size=1)
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "document_not_found"},
        )
    return _document_item(documents[0])


def _dataset_item(dataset: Dataset) -> KnowledgeDatasetItem:
    return KnowledgeDatasetItem.model_validate(
        {
            **asdict(dataset),
            "raw_metadata": dict(dataset.raw_metadata),
            "parser_config": dict(dataset.parser_config),
        }
    )


def _document_item(document: Document) -> KnowledgeDocumentItem:
    return KnowledgeDocumentItem.model_validate(
        {
            **asdict(document),
            "raw_metadata": dict(document.raw_metadata),
        }
    )


def _chunk_item(chunk: RetrievedChunk, citation_index: int) -> KnowledgeChunkItem:
    return KnowledgeChunkItem.model_validate(
        {
            "citation_index": citation_index,
            "chunk_id": chunk.chunk_id,
            "dataset_id": chunk.dataset_id,
            "dataset_name": chunk.dataset_name,
            "document_id": chunk.document_id,
            "document_name": chunk.document_name,
            "content": chunk.content,
            "page_numbers": list(chunk.page_numbers),
            "positions": list(chunk.positions),
            "image_id": chunk.image_id,
            "similarity": chunk.similarity,
            "vector_similarity": chunk.vector_similarity,
            "term_similarity": chunk.term_similarity,
            "source_url": chunk.source_url,
            "raw_metadata": dict(chunk.raw_metadata),
        }
    )


async def _require_owned_dataset(client: RAGFlowClient, dataset_id: str) -> Dataset:
    datasets = await client.list_datasets(
        dataset_id=dataset_id,
        include_parsing_status=True,
        page_size=1,
    )
    dataset = next((item for item in datasets if item.id == dataset_id), None)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "dataset_not_found"},
        )
    if not _is_dev_namespace(dataset.name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ragflow_forbidden",
                "message": "Dataset is outside biosafe-dev namespace",
            },
        )
    return dataset


def _is_dev_namespace(name: str) -> bool:
    return name.lower().startswith(DEV_DATASET_PREFIX)


def _default_parser_config(chunk_method: str) -> dict[str, object] | None:
    if chunk_method == "naive":
        return None
    if chunk_method in {"laws", "manual", "paper", "book", "qa", "presentation", "table"}:
        return {"raptor": {"use_raptor": False}}
    return {}


def _raise_ragflow_error(exc: RAGFlowError) -> None:
    raise HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc
