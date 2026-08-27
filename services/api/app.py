"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from biosafe import __version__
from biosafe.application.experiment_prompts import ExperimentPromptStore
from biosafe.application.query_service import QueryService
from biosafe.config import Settings
from biosafe.integrations.llm import OpenAIChatClient
from biosafe.integrations.ragflow import RAGFlowClient
from biosafe.logging import configure_logging
from biosafe.storage import BindingRepository, Database, HistoryRepository
from services.api.routes import chat, experiments, history


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    configure_logging(resolved.log_level)
    database = Database(resolved.database_path)
    database.migrate()
    app = FastAPI(title="Biosafe Assistant API", version=__version__)
    app.state.settings = resolved
    app.state.database = database
    app.state.history_repository = HistoryRepository(database)
    app.state.binding_repository = BindingRepository(database)
    app.state.experiment_prompt_store = ExperimentPromptStore(resolved.experiments_dir)
    app.state.llm_client = OpenAIChatClient(resolved.llm)
    app.state.ragflow_client = RAGFlowClient(resolved.ragflow)
    app.state.query_service = QueryService(
        history_repository=app.state.history_repository,
        binding_repository=app.state.binding_repository,
        prompt_store=app.state.experiment_prompt_store,
        llm_client=app.state.llm_client,
        ragflow_client=app.state.ragflow_client,
        default_dataset_ids=resolved.ragflow.dataset_ids,
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
    app.include_router(experiments.router)
    app.include_router(history.router)
    return app


app = create_app()
