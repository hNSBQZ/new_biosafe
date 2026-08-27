"""Experiment context listing route."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from biosafe.application.experiment_prompts import ExperimentPromptStore
from services.api.deps import get_experiment_prompt_store
from services.api.schemas import ExperimentItem, ExperimentPage

router = APIRouter(prefix="/api/experiments", tags=["experiments"])
Store = Annotated[ExperimentPromptStore, Depends(get_experiment_prompt_store)]


@router.get("", response_model=ExperimentPage)
async def list_experiments(store: Store) -> ExperimentPage:
    return ExperimentPage(
        items=[
            ExperimentItem(
                id=item.id,
                title=item.title,
                step_count=len(item.steps),
                knowledge_point_count=len(item.knowledge_points),
            )
            for item in store.list_experiments()
        ]
    )
