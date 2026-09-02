"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from biosafe import __version__
from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.application.query_service import QueryService
from biosafe.auth import hash_password
from biosafe.config import Settings
from biosafe.integrations.asr import ASRClient
from biosafe.integrations.llm import OpenAIChatClient
from biosafe.integrations.ragflow import RAGFlowClient
from biosafe.integrations.tts import TTSClient
from biosafe.logging import configure_logging
from biosafe.storage import AdminRepository, BindingRepository, Database, HistoryRepository
from services.api.routes import admin, audio, chat, experiments, history
from services.audio import AudioPipeline


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await app.state.ragflow_client.close()
    await app.state.tts_client.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    configure_logging(resolved.log_level, resolved.log_file)
    database = Database(resolved.database_path)
    database.migrate()
    app = FastAPI(title="Biosafe Assistant API", version=__version__, lifespan=_lifespan)
    app.state.settings = resolved
    app.state.database = database
    app.state.admin_repository = AdminRepository(database)
    app.state.history_repository = HistoryRepository(database)
    app.state.binding_repository = BindingRepository(database)
    app.state.experiment_prompt_store = ExperimentPromptStore(resolved.experiments_dir)
    app.state.llm_client = OpenAIChatClient(resolved.llm)
    app.state.ragflow_client = RAGFlowClient(resolved.ragflow)
    app.state.asr_client = ASRClient(resolved.asr)
    app.state.tts_client = TTSClient(resolved.tts)
    app.state.query_service = QueryService(
        history_repository=app.state.history_repository,
        binding_repository=app.state.binding_repository,
        prompt_store=app.state.experiment_prompt_store,
        llm_client=app.state.llm_client,
        ragflow_client=app.state.ragflow_client,
        default_dataset_ids=resolved.ragflow.dataset_ids,
    )
    app.state.audio_pipeline = AudioPipeline(
        asr_client=app.state.asr_client,
        tts_client=app.state.tts_client,
        query_service=app.state.query_service,
        tts_sample_rate=resolved.tts.sample_rate,
    )
    if resolved.admin.password and resolved.admin.token_secret:
        app.state.admin_repository.upsert(
            resolved.admin.username,
            hash_password(resolved.admin.password),
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "biosafe-api", "version": __version__}

    app.include_router(chat.router)
    app.include_router(admin.router)
    app.include_router(audio.router)
    app.include_router(experiments.router)
    app.include_router(history.router)
    return app


app = create_app()
