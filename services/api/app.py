"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from biosafe import __version__
from biosafe.config import Settings
from biosafe.logging import configure_logging
from biosafe.storage import Database, HistoryRepository
from services.api.routes import history


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    configure_logging(resolved.log_level)
    database = Database(resolved.database_path)
    database.migrate()
    app = FastAPI(title="Biosafe Assistant API", version=__version__)
    app.state.settings = resolved
    app.state.database = database
    app.state.history_repository = HistoryRepository(database)
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

    app.include_router(history.router)
    return app


app = create_app()
