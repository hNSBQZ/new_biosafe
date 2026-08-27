from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from biosafe.config import Settings
from biosafe.domain.history import HistoryCreate
from services.api.app import create_app


@pytest.mark.asyncio
async def test_history_page_detail_and_correction(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "api.db"))
    created = app.state.history_repository.create(
        HistoryCreate(
            request_id="request-api",
            session_id="session-api",
            created_at=datetime.now(UTC).isoformat(),
            experiment_id="exp-1",
            input_mode="text",
            question="原始问题",
            answer_source="rag",
            system_answer="系统回答 [1]",
            references=[{"chunk_id": "chunk-1"}],
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/api/history", params={"page": 1, "page_size": 10})
        detail = await client.get(f"/api/history/{created.id}")
        correction = await client.patch(
            f"/api/history/{created.id}/correction", json={"corrected_answer": "人工纠错"}
        )

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert detail.json()["references"][0]["chunk_id"] == "chunk-1"
    assert correction.status_code == 200
    assert correction.json()["corrected_answer"] == "人工纠错"
    assert correction.json()["correction_updated_at"] is not None


@pytest.mark.asyncio
async def test_missing_history_returns_stable_404(tmp_path: Path) -> None:
    transport = httpx.ASGITransport(
        app=create_app(Settings(database_path=tmp_path / "api.db"))
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/history/999")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "history_not_found"
