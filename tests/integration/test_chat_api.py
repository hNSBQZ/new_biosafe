from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from biosafe.config import Settings
from biosafe.domain.query import QueryEvent, QueryStage
from services.api.app import create_app


class StubQueryService:
    def __init__(self) -> None:
        self.questions: list[str] = []

    async def answer_text(self, request, *, cancel_requested=None):
        self.questions.append(request.question)
        yield QueryEvent(
            event="completed",
            request_id=request.request_id,
            sequence=1,
            stage=QueryStage.COMPLETED.value,
            data={"answer_source": "direct", "answer": "测试回答", "history_id": 1},
        )


def _sse_payloads(text: str) -> list[dict]:
    payloads = []
    for line in text.splitlines():
        if line.startswith("data:"):
            payloads.append(json.loads(line.removeprefix("data:").strip()))
    return payloads


@pytest.mark.asyncio
async def test_chat_route_streams_query_events(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "api.db"))
    service = StubQueryService()
    app.state.query_service = service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"question": "当前步骤注意什么？", "experiment_id": "4", "session_id": "s1"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert service.questions == ["当前步骤注意什么？"]
    payloads = _sse_payloads(response.text)
    assert payloads[0]["event"] == "completed"
    assert payloads[0]["data"]["answer"] == "测试回答"


@pytest.mark.asyncio
async def test_experiments_route_lists_loaded_contexts(tmp_path: Path) -> None:
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "1.md").write_text(
        '''"EXP1": {
  title: "样本处理",
  context: `
    {
      "experiment_supplies": ["生物安全柜"],
      "experiment_steps": ["1. 放入样本"],
      "knowledge_points_list": ["处理样本时应在生物安全柜内操作。"]
    }
  `
}''',
        encoding="utf-8",
    )
    app = create_app(
        Settings(database_path=tmp_path / "api.db", experiments_dir=experiments)
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/experiments")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": "1",
            "title": "样本处理",
            "step_count": 1,
            "knowledge_point_count": 1,
        }
    ]
