"""HTTP TTS adapter."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

import httpx

from biosafe.config import TTSConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSResult:
    success: bool
    audio_bytes: bytes = b""
    text: str = ""
    sequence_id: int = 0
    error_code: str = ""
    error_message: str = ""
    duration_ms: float = 0.0


class TTSProtocol(Protocol):
    async def synthesize(self, text: str, *, sequence_id: int = 0) -> TTSResult: ...


class TTSClient:
    """OpenAI-style speech endpoint adapter."""

    def __init__(
        self,
        config: TTSConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._config = config
        self._semaphore = asyncio.Semaphore(max(1, config.max_concurrent))
        self._client: httpx.AsyncClient | None = None
        if config.base_url:
            self._client = httpx.AsyncClient(timeout=config.timeout, transport=transport)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def synthesize(self, text: str, *, sequence_id: int = 0) -> TTSResult:
        started_at = perf_counter()
        clean_text = text.strip()
        if not clean_text:
            return _failure(
                started_at,
                "tts_text_empty",
                "TTS text is empty",
                clean_text,
                sequence_id,
            )
        if not self._config.ready or self._client is None:
            return _failure(
                started_at,
                "tts_not_configured",
                "TTS is not configured",
                clean_text,
                sequence_id,
            )

        attempts = max(0, self._config.max_retries) + 1
        last_result: TTSResult | None = None
        for attempt in range(attempts):
            result = await self._request(clean_text, sequence_id, started_at)
            if result.success:
                return result
            last_result = result
            if attempt >= attempts - 1 or result.error_code == "tts_http_error":
                break
            delay = min(self._config.retry_base_delay * (2**attempt), 3.0)
            await asyncio.sleep(delay)
        return last_result or _failure(
            started_at, "tts_unavailable", "TTS response was unavailable", clean_text, sequence_id
        )

    async def _request(self, text: str, sequence_id: int, started_at: float) -> TTSResult:
        payload = {
            "model": self._config.model,
            "voice": self._config.voice,
            "input": text,
            "response_format": self._config.response_format,
        }
        try:
            async with self._semaphore:
                assert self._client is not None
                response = await self._client.post(self._config.base_url, json=payload)
        except httpx.TimeoutException:
            return _failure(started_at, "tts_timeout", "TTS request timed out", text, sequence_id)
        except httpx.HTTPError:
            return _failure(started_at, "tts_unavailable", "TTS request failed", text, sequence_id)

        if response.status_code != 200:
            detail = response.text[:200]
            logger.warning("TTS HTTP error: seq=%s status=%s", sequence_id, response.status_code)
            return _failure(
                started_at,
                "tts_http_error" if response.status_code < 500 else "tts_server_error",
                f"TTS HTTP {response.status_code}: {detail}",
                text,
                sequence_id,
            )
        if not response.content:
            return _failure(
                started_at,
                "tts_empty_audio",
                "TTS returned empty audio",
                text,
                sequence_id,
            )
        return TTSResult(
            success=True,
            audio_bytes=response.content,
            text=text,
            sequence_id=sequence_id,
            duration_ms=_elapsed_ms(started_at),
        )


def _failure(
    started_at: float,
    code: str,
    message: str,
    text: str = "",
    sequence_id: int = 0,
) -> TTSResult:
    return TTSResult(
        success=False,
        text=text,
        sequence_id=sequence_id,
        error_code=code,
        error_message=message,
        duration_ms=_elapsed_ms(started_at),
    )


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)
