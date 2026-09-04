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


@pytest.mark.asyncio
async def test_built_web_assets_and_spa_routes_are_served_without_masking_api_404(
    tmp_path: Path,
) -> None:
    web_dist = tmp_path / "dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    (web_dist / "index.html").write_text("<title>Biosafe production</title>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('biosafe')", encoding="utf-8")
    app = create_app(Settings(database_path=tmp_path / "web.db", web_dist_path=web_dist))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        admin_route = await client.get("/admin/history")
        asset = await client.get("/assets/app.js")
        missing_api = await client.get("/api/does-not-exist")

    assert root.status_code == 200
    assert admin_route.status_code == 200
    assert "Biosafe production" in admin_route.text
    assert asset.text == "console.log('biosafe')"
    assert missing_api.status_code == 404
    assert missing_api.headers["content-type"].startswith("application/json")
