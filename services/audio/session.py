"""Single WebSocket audio session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class AudioSession:
    session_id: str
    experiment_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sample_rate: int = 16000
    audio_format: str = "pcm"
    audio_buffer: bytearray = field(default_factory=bytearray)
    audio_packets: int = 0
    is_recording: bool = False
    is_processing: bool = False
    is_interrupted: bool = False

    def start_recording(
        self,
        *,
        sample_rate: int | None = None,
        audio_format: str | None = None,
    ) -> None:
        self.audio_buffer = bytearray()
        self.audio_packets = 0
        self.is_recording = True
        self.is_interrupted = False
        if sample_rate is not None:
            self.sample_rate = sample_rate
        if audio_format:
            self.audio_format = audio_format

    def append_audio(self, data: bytes) -> None:
        self.audio_buffer.extend(data)
        self.audio_packets += 1

    def finish_recording(self) -> bytes:
        self.is_recording = False
        return bytes(self.audio_buffer)

    def interrupt(self) -> None:
        self.is_interrupted = True
