from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from biosafe.application.correction_dispatcher import AnswerCorrectionDispatcher
from biosafe.storage.correction_repository import AnswerCorrectionRepository
from biosafe.storage.history_repository import HistoryRepository
from services.api.deps import (
    get_correction_dispatcher,
    get_correction_repository,
    get_history_repository,
)
from services.api.schemas import AutoCorrectionItem, CorrectionRequest, HistoryItem, HistoryPage

router = APIRouter(prefix="/api/history", tags=["history"])
Repository = Annotated[HistoryRepository, Depends(get_history_repository)]
CorrectionRepository = Annotated[
    AnswerCorrectionRepository, Depends(get_correction_repository)
]
CorrectionDispatcher = Annotated[
    AnswerCorrectionDispatcher, Depends(get_correction_dispatcher)
]


@router.get("", response_model=HistoryPage)
async def list_history(
    repository: Repository,
    correction_repository: CorrectionRepository,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    experiment_id: str | None = None,
    status: str | None = None,
) -> HistoryPage:
    items, total = repository.list(
        page=page, page_size=page_size, experiment_id=experiment_id, status=status
    )
    corrections = correction_repository.get_for_history_ids([item.id for item in items])
    return HistoryPage(
        items=[_history_item(item, corrections.get(item.id)) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{history_id}", response_model=HistoryItem)
async def get_history(
    history_id: int,
    repository: Repository,
    correction_repository: CorrectionRepository,
) -> HistoryItem:
    item = repository.get(history_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "history_not_found"})
    return _history_item(item, correction_repository.get_by_history_id(history_id))


@router.patch("/{history_id}/correction", response_model=HistoryItem)
async def update_correction(
    history_id: int,
    payload: CorrectionRequest,
    repository: Repository,
    correction_repository: CorrectionRepository,
) -> HistoryItem:
    item = repository.update_correction(history_id, payload.corrected_answer)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "history_not_found"})
    return _history_item(item, correction_repository.get_by_history_id(history_id))


@router.post("/{history_id}/auto-correction", response_model=AutoCorrectionItem)
async def enqueue_auto_correction(
    history_id: int,
    repository: Repository,
    dispatcher: CorrectionDispatcher,
) -> AutoCorrectionItem:
    item = repository.get(history_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "history_not_found"})
    if (
        item.status != "completed"
        or item.answer_source not in {"direct", "rag"}
        or not item.system_answer.strip()
    ):
        raise HTTPException(status_code=409, detail={"code": "history_not_correctable"})
    if not dispatcher.is_running:
        raise HTTPException(status_code=503, detail={"code": "correction_not_configured"})
    task = dispatcher.submit(item, retry=True)
    if task is None:
        raise HTTPException(status_code=503, detail={"code": "correction_unavailable"})
    return AutoCorrectionItem.model_validate(task)


def _history_item(item: object, correction: object | None) -> HistoryItem:
    history_item = HistoryItem.model_validate(item)
    if correction is None:
        return history_item
    return history_item.model_copy(
        update={"auto_correction": AutoCorrectionItem.model_validate(correction)}
    )
