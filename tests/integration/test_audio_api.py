from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from biosafe.config import Settings
from services.api.app import create_app


class StubAudioPipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def process_audio(self, *, session, audio_bytes: bytes, sender) -> None:
        self.calls.append(
            {
                "session_id": session.session_id,
                "experiment_id": session.experiment_id,
                "sample_rate": session.sample_rate,
                "audio_format": session.audio_format,
                "audio_bytes": audio_bytes,
            }
        )
        await sender({"type": "transcription", "success": True, "text": "测试问题"})
        await sender(
            {"type": "session_complete", "reason": "done", "session_id": session.session_id}
        )


def test_audio_websocket_accepts_audio_frames(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "api.db"))
    pipeline = StubAudioPipeline()
    app.state.audio_pipeline = pipeline

    with (
        TestClient(app) as client,
        client.websocket_connect("/api/v1/chat/audio?experiment_id=exp-a") as websocket,
    ):
        connected = websocket.receive_json()
        websocket.send_json({"type": "audio_start", "sample_rate": 8000, "format": "wav"})
        started = websocket.receive_json()
        websocket.send_json(
            {
                "type": "audio_data",
                "seq": 7,
                "data": base64.b64encode(b"audio").decode("ascii"),
            }
        )
        ack = websocket.receive_json()
        websocket.send_json({"type": "audio_end"})
        transcription = websocket.receive_json()
        complete = websocket.receive_json()

    assert connected["type"] == "connected"
    assert started == {"type": "status", "phase": "recording_started", "text": "recording started"}
    assert ack == {"type": "packet_ack", "seq": 7}
    assert transcription["text"] == "测试问题"
    assert complete["reason"] == "done"
    assert pipeline.calls == [
        {
            "session_id": connected["session_id"],
            "experiment_id": "exp-a",
            "sample_rate": 8000,
            "audio_format": "wav",
            "audio_bytes": b"audio",
        }
    ]


def test_audio_websocket_rejects_invalid_base64(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "api.db"))
    app.state.audio_pipeline = StubAudioPipeline()

    with TestClient(app) as client, client.websocket_connect("/api/v1/chat/audio") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "audio_start"})
        websocket.receive_json()
        websocket.send_json({"type": "audio_data", "data": "not-base64!!"})
        error = websocket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "audio_invalid_base64"
