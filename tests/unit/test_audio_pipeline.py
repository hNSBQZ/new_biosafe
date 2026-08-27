from __future__ import annotations

import base64
from typing import Any

import pytest

from biosafe.domain.query import QueryEvent, QueryStage
from biosafe.integrations.asr.client import ASRResult
from biosafe.integrations.tts.client import TTSResult
from services.audio import AudioPipeline, AudioSession


class FakeASR:
    def __init__(self, result: ASRResult):
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int = 16000,
        audio_format: str = "pcm",
        session_id: str = "default",
    ) -> ASRResult:
        self.calls.append(
            {
                "audio_bytes": audio_bytes,
                "sample_rate": sample_rate,
                "audio_format": audio_format,
                "session_id": session_id,
            }
        )
        return self.result


class FakeTTS:
    def __init__(self, *, success: bool = True):
        self.success = success
        self.texts: list[str] = []

    async def synthesize(self, text: str, *, sequence_id: int = 0) -> TTSResult:
        self.texts.append(text)
        return TTSResult(
            success=self.success,
            audio_bytes=f"pcm-{sequence_id}".encode(),
            text=text,
            sequence_id=sequence_id,
            error_code="" if self.success else "tts_failed",
        )


class FakeQueryService:
    def __init__(self, answer_source: str = "direct", answer: str = "回答。"):
        self.answer_source = answer_source
        self.answer = answer
        self.requests: list[Any] = []

    async def answer_text(self, request, *, cancel_requested=None):
        self.requests.append(request)
        if cancel_requested and cancel_requested():
            yield QueryEvent(
                event="cancelled",
                request_id=request.request_id,
                sequence=1,
                stage=QueryStage.CANCELLED.value,
                data={"answer_source": "error", "history_id": 1},
            )
            return
        if self.answer_source == "instruction":
            yield QueryEvent(
                event="completed",
                request_id=request.request_id,
                sequence=1,
                stage=QueryStage.COMPLETED.value,
                data={
                    "answer_source": "instruction",
                    "func_call": {
                        "command": "ShowProcedurePanel",
                        "confidence": 0.95,
                        "params": {},
                    },
                    "history_id": 2,
                },
            )
            return
        yield QueryEvent(
            event="completed",
            request_id=request.request_id,
            sequence=1,
            stage=QueryStage.COMPLETED.value,
            data={
                "answer_source": self.answer_source,
                "answer": self.answer,
                "references": [{"chunk_id": "c1"}] if self.answer_source == "rag" else [],
                "history_id": 3,
            },
        )


async def _collect(pipeline: AudioPipeline, session: AudioSession) -> list[dict]:
    messages: list[dict] = []

    async def sender(message: dict) -> None:
        messages.append(message)

    await pipeline.process_audio(session=session, audio_bytes=b"audio", sender=sender)
    return messages


@pytest.mark.asyncio
async def test_audio_pipeline_uses_voice_query_and_sends_tts_audio() -> None:
    asr = FakeASR(ASRResult(success=True, text="新冠培养需要什么实验室？"))
    tts = FakeTTS()
    query = FakeQueryService(answer="BSL-3实验室进行。注意0.1毫升。")
    pipeline = AudioPipeline(
        asr_client=asr,
        tts_client=tts,
        query_service=query,
    )  # type: ignore[arg-type]
    session = AudioSession(
        session_id="s1",
        experiment_id="exp-1",
        sample_rate=8000,
        audio_format="wav",
    )

    messages = await _collect(pipeline, session)

    assert asr.calls[0]["audio_bytes"] == b"audio"
    assert asr.calls[0]["sample_rate"] == 8000
    assert query.requests[0].question == "新冠培养需要什么实验室？"
    assert query.requests[0].input_mode == "voice"
    assert query.requests[0].session_id == "s1"
    assert any(message["type"] == "answer" for message in messages)
    audio_message = next(
        message
        for message in messages
        if message["type"] == "audio_stream" and message["event"] == "data"
    )
    assert base64.b64decode(audio_message["data"]) == b"pcm-0"
    assert tts.texts == ["BSL三级实验室进行。", "注意零点一毫升。"]
    finished = [message for message in messages if message["type"] == "session_complete"][-1]
    assert finished["reason"] == "done"


@pytest.mark.asyncio
async def test_audio_pipeline_instruction_path_does_not_call_tts() -> None:
    tts = FakeTTS()
    pipeline = AudioPipeline(
        asr_client=FakeASR(ASRResult(success=True, text="现在第几步了")),
        tts_client=tts,
        query_service=FakeQueryService(answer_source="instruction"),
    )  # type: ignore[arg-type]

    messages = await _collect(pipeline, AudioSession(session_id="s2", experiment_id="exp-1"))

    instruction = next(message for message in messages if message["type"] == "instruction")
    assert instruction["command"] == "ShowProcedurePanel"
    assert tts.texts == []


@pytest.mark.asyncio
async def test_audio_pipeline_tts_failure_keeps_text_answer() -> None:
    pipeline = AudioPipeline(
        asr_client=FakeASR(ASRResult(success=True, text="问题")),
        tts_client=FakeTTS(success=False),
        query_service=FakeQueryService(answer="文本仍然保留。"),
    )  # type: ignore[arg-type]

    messages = await _collect(pipeline, AudioSession(session_id="s3", experiment_id="exp-1"))

    answer = next(message for message in messages if message["type"] == "answer")
    assert answer["answer"] == "文本仍然保留。"
    finished_audio = next(
        message
        for message in messages
        if message["type"] == "audio_stream" and message["event"] == "finished"
    )
    assert finished_audio["tts_success"] is False
    assert not [
        message
        for message in messages
        if message["type"] == "error" and message["code"].startswith("tts")
    ]


@pytest.mark.asyncio
async def test_audio_pipeline_asr_empty_text_is_error() -> None:
    query = FakeQueryService()
    pipeline = AudioPipeline(
        asr_client=FakeASR(ASRResult(success=True, text=" ")),
        tts_client=FakeTTS(),
        query_service=query,
    )  # type: ignore[arg-type]

    messages = await _collect(pipeline, AudioSession(session_id="s4", experiment_id="exp-1"))

    assert query.requests == []
    error = next(message for message in messages if message["type"] == "error")
    assert error["code"] == "asr_empty_text"
    assert messages[-1]["reason"] == "error"


@pytest.mark.asyncio
async def test_audio_pipeline_cancelled_query_completes_as_interrupted() -> None:
    query = FakeQueryService()
    session = AudioSession(session_id="s5", experiment_id="exp-1")

    class InterruptingQuery(FakeQueryService):
        async def answer_text(self, request, *, cancel_requested=None):
            session.interrupt()
            assert cancel_requested is not None
            assert cancel_requested() is True
            yield QueryEvent(
                event="cancelled",
                request_id=request.request_id,
                sequence=1,
                stage=QueryStage.CANCELLED.value,
                data={"answer_source": "error", "history_id": 4},
            )

    pipeline = AudioPipeline(
        asr_client=FakeASR(ASRResult(success=True, text="问题")),
        tts_client=FakeTTS(),
        query_service=InterruptingQuery(),
    )  # type: ignore[arg-type]

    messages = await _collect(pipeline, session)

    assert query.requests == []
    assert messages[-1]["type"] == "session_complete"
    assert messages[-1]["reason"] == "interrupted"
