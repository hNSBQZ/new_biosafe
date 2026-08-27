"""FunASR WebSocket adapter."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

import websockets

from biosafe.config import ASRConfig

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 10 * 1024 * 1024


@dataclass(frozen=True)
class ASRResult:
    success: bool
    text: str = ""
    error_code: str = ""
    error_message: str = ""
    duration_ms: float = 0.0


class ASRProtocol(Protocol):
    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int = 16000,
        audio_format: str = "pcm",
        session_id: str = "default",
    ) -> ASRResult: ...


class ASRClient:
    """Per-request FunASR WebSocket client.

    The adapter accepts complete in-memory audio bytes and never writes audio
    to disk. All service endpoints come from ASRConfig.
    """

    def __init__(self, config: ASRConfig):
        self._config = config

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int = 16000,
        audio_format: str = "pcm",
        session_id: str = "default",
    ) -> ASRResult:
        started_at = perf_counter()
        if not self._config.ready:
            return _failure(started_at, "asr_not_configured", "ASR is not configured")
        if not audio_bytes:
            return _failure(started_at, "asr_audio_empty", "Audio data is empty")

        try:
            async with websockets.connect(
                self._config.uri,
                open_timeout=self._config.connect_timeout,
            ) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "mode": "offline",
                            "wav_name": session_id,
                            "wav_format": audio_format,
                            "audio_fs": sample_rate,
                            "is_speaking": True,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                for offset in range(0, len(audio_bytes), _CHUNK_SIZE):
                    await websocket.send(audio_bytes[offset : offset + _CHUNK_SIZE])
                await websocket.send('{"is_speaking":false}')

                raw = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=self._config.recognize_timeout,
                )
        except TimeoutError:
            return _failure(started_at, "asr_timeout", "ASR recognition timed out")
        except websockets.exceptions.WebSocketException as exc:
            logger.warning("ASR WebSocket failed for session=%s: %s", session_id, exc)
            return _failure(started_at, "asr_connection_error", "ASR connection failed")
        except Exception:
            logger.exception("ASR request failed unexpectedly for session=%s", session_id)
            return _failure(started_at, "asr_unavailable", "ASR response was unavailable")

        if isinstance(raw, bytes):
            return _failure(started_at, "asr_invalid_response", "ASR returned binary data")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return _failure(started_at, "asr_invalid_response", "ASR returned invalid JSON")

        text = str(payload.get("text") or "").strip()
        return ASRResult(success=True, text=text, duration_ms=_elapsed_ms(started_at))


def _failure(started_at: float, code: str, message: str) -> ASRResult:
    return ASRResult(
        success=False,
        error_code=code,
        error_message=message,
        duration_ms=_elapsed_ms(started_at),
    )


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)
