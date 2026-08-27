from pathlib import Path

import httpx
import pytest

from biosafe.config import Settings
from services.api.app import create_app


@pytest.mark.asyncio
async def test_health(tmp_path: Path) -> None:
    transport = httpx.ASGITransport(
        app=create_app(Settings(database_path=tmp_path / "health.db"))
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "biosafe-api", "version": "0.1.0"}
