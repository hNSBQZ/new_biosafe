from pathlib import Path

from fastapi.testclient import TestClient

from biosafe.config import Settings
from services.api.app import create_app


def test_health(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(database_path=tmp_path / "health.db")))
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "biosafe-api", "version": "0.1.0"}
