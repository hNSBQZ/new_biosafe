"""Live ASR -> QueryService -> TTS smoke using configured external services."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biosafe.config import Settings  # noqa: E402
from biosafe.integrations.tts import TTSClient  # noqa: E402
from services.api.app import create_app  # noqa: E402

DEFAULT_QUESTION = "P4实验室穿什么防护服，需要戴口罩吗"


def _load_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    path = Path(".env")
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _merged_env() -> dict[str, str]:
    env = _load_env_file()
    env.update(os.environ)
    return env


async def _synthesize_input(settings: Settings, question: str) -> bytes:
    client = TTSClient(settings.tts)
    try:
        result = await client.synthesize(question, sequence_id=1)
        if not result.success:
            raise RuntimeError(f"TTS failed: {result.error_code} {result.error_message}")
        return result.audio_bytes
    finally:
        await client.close()


def main() -> int:
    settings = Settings.from_env(_merged_env())
    if not (
        settings.asr.ready and settings.tts.ready and settings.llm.ready and settings.ragflow.ready
    ):
        print(
            json.dumps(
                {"ok": False, "reason": "Required services are not configured"},
                ensure_ascii=False,
            )
        )
        return 2

    question = DEFAULT_QUESTION
    with tempfile.TemporaryDirectory(prefix="biosafe-audio-smoke-") as temp_root:
        smoke_settings = replace(settings, database_path=Path(temp_root) / "audio-smoke.db")
        audio_bytes = asyncio.run(_synthesize_input(smoke_settings, question))
        app = create_app(smoke_settings)
        with (
            TestClient(app) as client,
            client.websocket_connect("/api/v1/chat/audio?experiment_id=generic") as websocket,
        ):
            connected = websocket.receive_json()
            websocket.send_json({"type": "audio_start", "sample_rate": 16000, "format": "pcm"})
            started = websocket.receive_json()
            websocket.send_json(
                {
                    "type": "audio_data",
                    "seq": 1,
                    "data": base64.b64encode(audio_bytes).decode("ascii"),
                }
            )
            ack = websocket.receive_json()
            websocket.send_json({"type": "audio_end"})

            transcript = ""
            answer_source = ""
            answer = ""
            history_id = None
            tts_success = False
            audio_chunks = 0
            session_reason = ""
            while True:
                message = websocket.receive_json()
                if message.get("type") == "transcription":
                    transcript = str(message.get("text") or "")
                elif message.get("type") == "answer":
                    answer_source = str(message.get("answer_source") or "")
                    answer = str(message.get("answer") or "")
                    history_id = message.get("history_id")
                elif message.get("type") == "audio_stream" and message.get("event") == "data":
                    audio_chunks += 1
                elif message.get("type") == "audio_stream" and message.get("event") == "finished":
                    tts_success = bool(message.get("tts_success"))
                elif message.get("type") == "session_complete":
                    session_reason = str(message.get("reason") or "")
                    break

        ok = bool(
            transcript.strip() and answer.strip() and tts_success and session_reason == "done"
        )
        print(
            json.dumps(
                {
                    "ok": ok,
                    "question": question,
                    "connected": connected,
                    "started": started,
                    "ack": ack,
                    "transcript": transcript,
                    "answer_source": answer_source,
                    "answer": answer,
                    "history_id": history_id,
                    "tts_success": tts_success,
                    "audio_chunks": audio_chunks,
                    "session_reason": session_reason,
                },
                ensure_ascii=False,
            )
        )
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
