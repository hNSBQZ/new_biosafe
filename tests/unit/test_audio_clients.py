from __future__ import annotations

import json

import httpx
import pytest

from biosafe.config import ASRConfig, TTSConfig
from biosafe.integrations.asr import ASRClient
from biosafe.integrations.tts import TTSClient


@pytest.mark.asyncio
async def test_asr_client_rejects_missing_config_and_empty_audio() -> None:
    not_configured = await ASRClient(ASRConfig()).transcribe(b"abc")
    assert not_configured.success is False
    assert not_configured.error_code == "asr_not_configured"

    empty = await ASRClient(ASRConfig(uri="ws://asr.test")).transcribe(b"")
    assert empty.success is False
    assert empty.error_code == "asr_audio_empty"


@pytest.mark.asyncio
async def test_asr_client_sends_funasr_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[bytes | str] = []
    captured: dict[str, object] = {}

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def send(self, payload: bytes | str) -> None:
            sent.append(payload)

        async def recv(self) -> str:
            return json.dumps({"text": "转写结果"}, ensure_ascii=False)

    def fake_connect(uri: str, *, open_timeout: float):
        captured["uri"] = uri
        captured["open_timeout"] = open_timeout
        return FakeWebSocket()

    monkeypatch.setattr("biosafe.integrations.asr.client.websockets.connect", fake_connect)

    result = await ASRClient(
        ASRConfig(uri="ws://asr.test/funasr", connect_timeout=3)
    ).transcribe(
        b"audio",
        sample_rate=8000,
        audio_format="wav",
        session_id="s1",
    )

    assert result.success is True
    assert result.text == "转写结果"
    assert captured == {"uri": "ws://asr.test/funasr", "open_timeout": 3}
    assert json.loads(str(sent[0])) == {
        "mode": "offline",
        "wav_name": "s1",
        "wav_format": "wav",
        "audio_fs": 8000,
        "is_speaking": True,
    }
    assert sent[1] == b"audio"
    assert sent[2] == '{"is_speaking":false}'


@pytest.mark.asyncio
async def test_tts_client_posts_payload_and_returns_audio() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=b"pcm-data")

    client = TTSClient(
        TTSConfig(base_url="http://tts.test/v1/audio/speech", model="cosy", voice="zh"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.synthesize("你好", sequence_id=2)
    finally:
        await client.close()

    assert result.success is True
    assert result.audio_bytes == b"pcm-data"
    assert result.sequence_id == 2
    assert requests == [
        {
            "model": "cosy",
            "voice": "zh",
            "input": "你好",
            "response_format": "pcm",
        }
    ]


@pytest.mark.asyncio
async def test_tts_client_retries_server_error() -> None:
    statuses = [500, 200]

    def handler(_: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        return httpx.Response(status, content=b"ok" if status == 200 else b"temporary")

    client = TTSClient(
        TTSConfig(
            base_url="http://tts.test/v1/audio/speech",
            model="cosy",
            voice="zh",
            max_retries=1,
            retry_base_delay=0,
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.synthesize("重试")
    finally:
        await client.close()

    assert result.success is True
    assert result.audio_bytes == b"ok"
    assert statuses == []


@pytest.mark.asyncio
async def test_tts_client_keeps_http_4xx_as_failure() -> None:
    client = TTSClient(
        TTSConfig(base_url="http://tts.test/v1/audio/speech", model="cosy", voice="zh"),
        transport=httpx.MockTransport(lambda _: httpx.Response(400, text="bad request")),
    )
    try:
        result = await client.synthesize("错误")
    finally:
        await client.close()

    assert result.success is False
    assert result.error_code == "tts_http_error"
