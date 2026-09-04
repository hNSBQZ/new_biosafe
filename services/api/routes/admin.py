"""Admin login and RAGFlow knowledge management routes."""

from __future__ import annotations

import asyncio
import mimetypes
import tempfile
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, cast
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

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
    KnowledgeFileItem,
    KnowledgeFilePage,
    KnowledgeRetrievalPreviewRequest,
    KnowledgeRetrievalPreviewResponse,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
AdminRepo = Annotated[AdminRepository, Depends(get_admin_repository)]
DEV_DATASET_PREFIX = "biosafe-dev-"
KnowledgeCategory = Literal["laws", "manual", "table", "paper", "naive"]
CATEGORY_LABELS: dict[str, str] = {
    "laws": "法规标准",
    "manual": "SOP 与设备手册",
    "table": "名录与表格",
    "paper": "论文与报告",
    "naive": "通用资料",
}
STATUS_LABELS = {
    "uploaded": "已上传",
    "parsing": "解析中",
    "completed": "已完成",
    "failed": "失败",
}


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


@router.get("/knowledge/files", response_model=KnowledgeFilePage)
async def list_knowledge_files(
    request: Request,
    _: str = Depends(_require_admin),
    name: str | None = None,
    category: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> KnowledgeFilePage:
    if category:
        _require_category(category)
    if status_filter and status_filter not in STATUS_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_knowledge_status"},
        )
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        datasets = await _managed_datasets(client, category)
        groups = await asyncio.gather(
            *(client.list_documents(dataset.id, page_size=100, name=name) for dataset in datasets)
        )
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    items = [
        _file_item(document, dataset.chunk_method)
        for dataset, documents in zip(datasets, groups, strict=True)
        for document in documents
        if _matches_file_filters(document, name, status_filter, date_from, date_to)
    ]
    items.sort(key=lambda item: (item.created_at or "", item.name.casefold()), reverse=True)
    return KnowledgeFilePage(items=items, total=len(items))


@router.post("/knowledge/files", response_model=KnowledgeFilePage)
async def upload_knowledge_file(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    category: Annotated[str, Form(...)],
    _: str = Depends(_require_admin),
) -> KnowledgeFilePage:
    method = _require_category(category)
    client: RAGFlowClient = request.app.state.ragflow_client
    temp_path: Path | None = None
    try:
        datasets = await _managed_datasets(client, method)
        dataset = _select_upload_dataset(datasets, method)
        if dataset is None:
            dataset = await client.create_dataset(
                f"{DEV_DATASET_PREFIX}{method}",
                chunk_method=method,
                parser_config=_default_parser_config(method),
            )
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=Path(file.filename or "upload").suffix,
        ) as tmp:
            tmp.write(await file.read())
            temp_path = Path(tmp.name)
        documents = await client.upload_document(
            dataset.id,
            temp_path,
            filename=file.filename or temp_path.name,
            content_type=file.content_type,
        )
        if documents:
            await client.start_parse(dataset.id, [document.id for document in documents])
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    items = [_file_item(document, method) for document in documents]
    return KnowledgeFilePage(items=items, total=len(items))


@router.get("/knowledge/files/{document_id}/content")
async def get_knowledge_file_content(
    document_id: str,
    request: Request,
    download: bool = False,
    _: str = Depends(_require_admin),
) -> Response:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        dataset, document = await _resolve_managed_document(client, document_id)
        downloaded = await client.download_document(dataset.id, document.id)
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    disposition = "attachment" if download else "inline"
    content_type = downloaded.content_type
    if content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(document.name)[0] or content_type
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(document.name)}",
        "X-Content-Type-Options": "nosniff",
    }
    if content_type == "text/html":
        headers["Content-Security-Policy"] = "sandbox"
    return Response(content=downloaded.content, media_type=content_type, headers=headers)


@router.post("/knowledge/files/{document_id}/retry", response_model=KnowledgeFileItem)
async def retry_knowledge_file(
    document_id: str,
    request: Request,
    _: str = Depends(_require_admin),
) -> KnowledgeFileItem:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        dataset, document = await _resolve_managed_document(client, document_id)
        await client.start_parse(dataset.id, [document.id])
        documents = await client.list_documents(dataset.id, document_id=document.id, page_size=1)
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    current = documents[0] if documents else document
    return _file_item(current, dataset.chunk_method)


@router.delete("/knowledge/files/{document_id}")
async def delete_knowledge_file(
    document_id: str,
    request: Request,
    _: str = Depends(_require_admin),
) -> dict[str, bool]:
    client: RAGFlowClient = request.app.state.ragflow_client
    try:
        dataset, document = await _resolve_managed_document(client, document_id)
        await client.delete_owned_document(dataset.id, document.id)
    except RAGFlowError as exc:
        _raise_ragflow_error(exc)
    return {"ok": True}


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
        items=[_dataset_item(dataset) for dataset in datasets if _is_dev_namespace(dataset.name)]
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


async def _managed_datasets(
    client: RAGFlowClient,
    category: str | None = None,
) -> list[Dataset]:
    datasets = await client.list_datasets(include_parsing_status=True, page_size=100)
    return [
        dataset
        for dataset in datasets
        if _is_dev_namespace(dataset.name)
        and dataset.chunk_method in CATEGORY_LABELS
        and (not category or dataset.chunk_method == category)
    ]


async def _resolve_managed_document(
    client: RAGFlowClient,
    document_id: str,
) -> tuple[Dataset, Document]:
    datasets = await _managed_datasets(client)
    groups = await asyncio.gather(
        *(
            client.list_documents(dataset.id, document_id=document_id, page_size=1)
            for dataset in datasets
        )
    )
    for dataset, documents in zip(datasets, groups, strict=True):
        document = next((item for item in documents if item.id == document_id), None)
        if document is not None:
            return dataset, document
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "document_not_found"},
    )


def _select_upload_dataset(datasets: list[Dataset], category: str) -> Dataset | None:
    expected_name = f"{DEV_DATASET_PREFIX}{category}"
    return next(
        (dataset for dataset in datasets if dataset.name.casefold() == expected_name.casefold()),
        min(datasets, key=lambda item: item.name.casefold()) if datasets else None,
    )


def _file_item(document: Document, category: str) -> KnowledgeFileItem:
    safe_category = category if category in CATEGORY_LABELS else "naive"
    file_status = _file_status(document.status)
    return KnowledgeFileItem(
        id=document.id,
        name=document.name,
        category=cast(KnowledgeCategory, safe_category),
        category_label=CATEGORY_LABELS[safe_category],
        status=file_status,
        status_label=STATUS_LABELS[file_status],
        progress=document.progress,
        status_message=document.progress_message,
        size=document.size,
        created_at=document.created_at,
        updated_at=document.updated_at,
        preview_kind=_preview_kind(document.name, document.document_type),
    )


def _file_status(raw_status: str) -> Literal["uploaded", "parsing", "completed", "failed"]:
    normalized = raw_status.strip().upper()
    if normalized in {"DONE", "SUCCESS", "SUCCEEDED", "COMPLETED", "3"}:
        return "completed"
    if normalized in {"RUNNING", "PARSING", "PROCESSING", "1"}:
        return "parsing"
    if normalized in {"FAIL", "FAILED", "ERROR", "CANCEL", "CANCELED", "CANCELLED", "2", "4"}:
        return "failed"
    return "uploaded"


def _preview_kind(
    filename: str,
    document_type: str,
) -> Literal["pdf", "image", "text", "download"]:
    suffix = Path(filename).suffix.lower()
    content_type = document_type.lower()
    if suffix == ".pdf" or content_type == "pdf" or content_type == "application/pdf":
        return "pdf"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}:
        return "image"
    if suffix in {".txt", ".md", ".rst", ".html", ".htm", ".csv", ".json", ".xml"}:
        return "text"
    return "download"


def _matches_file_filters(
    document: Document,
    name: str | None,
    status_filter: str | None,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    if name and name.casefold() not in document.name.casefold():
        return False
    if status_filter and _file_status(document.status) != status_filter:
        return False
    if not date_from and not date_to:
        return True
    created_date = _parse_document_date(document.created_at)
    if created_date is None:
        return False
    return not ((date_from and created_date < date_from) or (date_to and created_date > date_to))


def _parse_document_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _require_category(category: str) -> KnowledgeCategory:
    if category not in CATEGORY_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_knowledge_category"},
        )
    return cast(KnowledgeCategory, category)


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
