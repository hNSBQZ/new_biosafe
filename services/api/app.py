"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from biosafe import __version__
from biosafe.application.correction_dispatcher import AnswerCorrectionDispatcher
from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.application.query_service import QueryService
from biosafe.auth import hash_password
from biosafe.config import Settings
from biosafe.integrations.asr import ASRClient
from biosafe.integrations.correction import OpenAIAnswerCorrectionClient
from biosafe.integrations.llm import OpenAIChatClient
from biosafe.integrations.ragflow import RAGFlowClient
from biosafe.integrations.tts import TTSClient
from biosafe.logging import configure_logging
from biosafe.storage import (
    AdminRepository,
    AnswerCorrectionRepository,
    BindingRepository,
    Database,
    HistoryRepository,
)
from services.api.routes import admin, audio, chat, experiments, history
from services.audio import AudioPipeline

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    await app.state.correction_dispatcher.start()
    try:
        yield
    finally:
        await app.state.correction_dispatcher.close()
        await app.state.correction_client.close()
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
    app.state.correction_repository = AnswerCorrectionRepository(database)
    app.state.binding_repository = BindingRepository(database)
    app.state.experiment_prompt_store = ExperimentPromptStore(resolved.experiments_dir)
    app.state.llm_client = OpenAIChatClient(resolved.llm)
    app.state.ragflow_client = RAGFlowClient(resolved.ragflow)
    app.state.asr_client = ASRClient(resolved.asr)
    app.state.tts_client = TTSClient(resolved.tts)
    app.state.correction_client = OpenAIAnswerCorrectionClient(resolved.correction)
    app.state.correction_dispatcher = AnswerCorrectionDispatcher(
        repository=app.state.correction_repository,
        client=app.state.correction_client,
        config=resolved.correction,
    )
    app.state.query_service = QueryService(
        history_repository=app.state.history_repository,
        binding_repository=app.state.binding_repository,
        prompt_store=app.state.experiment_prompt_store,
        llm_client=app.state.llm_client,
        ragflow_client=app.state.ragflow_client,
        default_dataset_ids=resolved.ragflow.dataset_ids,
        correction_dispatcher=app.state.correction_dispatcher,
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
    _mount_web(app, resolved.web_dist_path)
    return app


def _mount_web(app: FastAPI, web_dist_path: Path) -> None:
    index_path = web_dist_path / "index.html"
    if not index_path.is_file():
        logger.info("web distribution does not exist: %s", web_dist_path)
        return

    assets_path = web_dist_path / "assets"
    if assets_path.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_path), name="web-assets")

    async def spa_index() -> FileResponse:
        return FileResponse(index_path, headers={"Cache-Control": "no-cache"})

    app.add_api_route("/", spa_index, methods=["GET", "HEAD"], include_in_schema=False)

    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/") or full_path == "health":
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return await spa_index()

    app.add_api_route(
        "/{full_path:path}",
        spa_fallback,
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )


app = create_app()
