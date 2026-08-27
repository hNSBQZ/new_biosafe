"""Sentence splitting and ordered TTS audio delivery."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from biosafe.integrations.tts.client import TTSResult

logger = logging.getLogger(__name__)

AudioMessageSender = Callable[[dict], Awaitable[None]]

_SENTENCE_ENDINGS = {"。", "！", "？", ".", "!", "?", "\n", "；", ";"}
_MAX_BUFFER_CHARS = 80


class SentenceSplitter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        segments: list[str] = []
        while self._buffer:
            cut_at = -1
            for index, char in enumerate(self._buffer):
                if char == "." and _is_decimal_point(self._buffer, index):
                    continue
                if char in _SENTENCE_ENDINGS:
                    cut_at = index
                    break
            if cut_at >= 0:
                segment = self._buffer[: cut_at + 1].strip()
                self._buffer = self._buffer[cut_at + 1 :]
                if segment:
                    segments.append(segment)
            elif len(self._buffer) >= _MAX_BUFFER_CHARS:
                segment = self._buffer.strip()
                self._buffer = ""
                if segment:
                    segments.append(segment)
            else:
                break
        return segments

    def flush(self) -> list[str]:
        remaining = self._buffer.strip()
        self._buffer = ""
        return [remaining] if remaining else []


@dataclass(frozen=True)
class AudioSendStats:
    success_count: int = 0
    failure_count: int = 0


class OrderedAudioSender:
    def __init__(self, sender: AudioMessageSender):
        self._sender = sender
        self._next_seq = 0
        self._expected_seq = 0
        self._buffer: dict[int, TTSResult] = {}
        self._pending_tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._success_count = 0
        self._failure_count = 0

    def next_seq(self) -> int:
        seq = self._next_seq
        self._next_seq += 1
        return seq

    def add_task(self, task: asyncio.Task) -> None:
        self._pending_tasks.append(task)

    async def enqueue(self, result: TTSResult) -> None:
        async with self._lock:
            self._buffer[result.sequence_id] = result
            await self._drain()

    async def flush(self) -> AudioSendStats:
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            self._pending_tasks.clear()
        async with self._lock:
            await self._drain()
            return AudioSendStats(self._success_count, self._failure_count)

    async def _drain(self) -> None:
        while self._expected_seq in self._buffer:
            item = self._buffer.pop(self._expected_seq)
            if item.success:
                self._success_count += 1
                await self._sender(
                    {
                        "type": "audio_stream",
                        "event": "data",
                        "data": base64.b64encode(item.audio_bytes).decode("ascii"),
                        "text": item.text,
                        "sequence": item.sequence_id,
                        "phase": "answer",
                    }
                )
            else:
                self._failure_count += 1
                logger.warning(
                    "TTS segment failed: seq=%s code=%s",
                    item.sequence_id,
                    item.error_code,
                )
            self._expected_seq += 1


def _is_decimal_point(text: str, index: int) -> bool:
    return (
        index > 0
        and index < len(text) - 1
        and text[index - 1].isdigit()
        and text[index + 1].isdigit()
    )
