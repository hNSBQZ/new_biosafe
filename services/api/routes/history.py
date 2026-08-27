from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from biosafe.storage.history_repository import HistoryRepository
from services.api.deps import get_history_repository
from services.api.schemas import CorrectionRequest, HistoryItem, HistoryPage

router = APIRouter(prefix="/api/history", tags=["history"])
Repository = Annotated[HistoryRepository, Depends(get_history_repository)]


@router.get("", response_model=HistoryPage)
async def list_history(
    repository: Repository,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    experiment_id: str | None = None,
    status: str | None = None,
) -> HistoryPage:
    items, total = repository.list(
        page=page, page_size=page_size, experiment_id=experiment_id, status=status
    )
    return HistoryPage(
        items=[HistoryItem.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{history_id}", response_model=HistoryItem)
async def get_history(history_id: int, repository: Repository) -> HistoryItem:
    item = repository.get(history_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "history_not_found"})
    return HistoryItem.model_validate(item)


@router.patch("/{history_id}/correction", response_model=HistoryItem)
async def update_correction(
    history_id: int, payload: CorrectionRequest, repository: Repository
) -> HistoryItem:
    item = repository.update_correction(history_id, payload.corrected_answer)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "history_not_found"})
    return HistoryItem.model_validate(item)
