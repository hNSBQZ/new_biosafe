from fastapi import Request

from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.application.query_service import QueryService
from biosafe.storage.admin_repository import AdminRepository, BindingRepository
from biosafe.storage.history_repository import HistoryRepository
from services.audio import AudioPipeline


async def get_history_repository(request: Request) -> HistoryRepository:
    return request.app.state.history_repository


async def get_binding_repository(request: Request) -> BindingRepository:
    return request.app.state.binding_repository


async def get_admin_repository(request: Request) -> AdminRepository:
    return request.app.state.admin_repository


async def get_experiment_prompt_store(request: Request) -> ExperimentPromptStore:
    return request.app.state.experiment_prompt_store


async def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


async def get_audio_pipeline(request: Request) -> AudioPipeline:
    return request.app.state.audio_pipeline
