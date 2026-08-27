from fastapi import Request

from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.application.query_service import QueryService
from biosafe.storage.admin_repository import BindingRepository
from biosafe.storage.history_repository import HistoryRepository


async def get_history_repository(request: Request) -> HistoryRepository:
    return request.app.state.history_repository


async def get_binding_repository(request: Request) -> BindingRepository:
    return request.app.state.binding_repository


async def get_experiment_prompt_store(request: Request) -> ExperimentPromptStore:
    return request.app.state.experiment_prompt_store


async def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service
