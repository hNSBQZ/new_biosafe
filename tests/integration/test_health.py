from fastapi.testclient import TestClient

from biosafe.config import Settings
from services.api.app import create_app


def test_health() -> None:
    client = TestClient(create_app(Settings()))
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "biosafe-api", "version": "0.1.0"}
