"""Audio conversation orchestration."""

from __future__ import annotations

import asyncio
from typing import Any

from biosafe.application.query_service import QueryService
from biosafe.domain.query import QueryRequest
from biosafe.integrations.asr.client import ASRProtocol
from biosafe.integrations.tts.client import TTSProtocol, TTSResult
from services.audio.normalizer import normalize_for_tts
from services.audio.sender import AudioMessageSender, OrderedAudioSender, SentenceSplitter
from services.audio.session import AudioSession

_VOICE_INPUT_MODE = "voice"


class AudioPipeline:
    def __init__(
        self,
        *,
        asr_client: ASRProtocol,
        tts_client: TTSProtocol,
        query_service: QueryService,
    ):
        self._asr = asr_client
        self._tts = tts_client
        self._query_service = query_service

    async def process_audio(
        self,
        *,
        session: AudioSession,
        audio_bytes: bytes,
        sender: AudioMessageSender,
    ) -> None:
        reason = "done"
        session.is_processing = True
        try:
            await _send_status(sender, "asr_started", "正在识别语音")
            asr_result = await self._asr.transcribe(
                audio_bytes,
                sample_rate=session.sample_rate,
                audio_format=session.audio_format,
                session_id=session.session_id,
            )
            await sender(
                {
                    "type": "transcription",
                    "success": asr_result.success,
                    "text": asr_result.text,
                    "duration_ms": asr_result.duration_ms,
                    "code": asr_result.error_code,
                }
            )
            if not asr_result.success:
                reason = "error"
                await _send_error(
                    sender,
                    asr_result.error_code or "asr_failed",
                    asr_result.error_message or "ASR failed",
                )
                return
            question = asr_result.text.strip()
            if not question:
                reason = "error"
                await _send_error(sender, "asr_empty_text", "ASR returned empty text")
                return
            if session.is_interrupted:
                reason = "interrupted"
                return

            await _send_status(sender, "query_started", "正在生成回答")
            outcome = await self._run_query(session, question, sender)
            if outcome["state"] == "cancelled":
                reason = "interrupted"
                return
            if outcome["state"] == "failed":
                reason = "error"
                await _send_error(
                    sender,
                    str(outcome.get("code") or "query_failed"),
                    str(outcome.get("message") or "Query failed"),
                )
                return
            if outcome["answer_source"] == "instruction":
                return

            answer = str(outcome.get("answer") or "").strip()
            if answer and not session.is_interrupted:
                await self._send_tts(session, answer, outcome, sender)
        except Exception:
            reason = "error"
            await _send_error(sender, "audio_internal_error", "Audio pipeline failed unexpectedly")
        finally:
            session.is_processing = False
            if session.is_interrupted and reason == "done":
                reason = "interrupted"
            await sender(
                {
                    "type": "session_complete",
                    "reason": reason,
                    "session_id": session.session_id,
                }
            )

    async def _run_query(
        self,
        session: AudioSession,
        question: str,
        sender: AudioMessageSender,
    ) -> dict[str, Any]:
        request = QueryRequest(
            question=question,
            experiment_id=session.experiment_id,
            session_id=session.session_id,
            input_mode=_VOICE_INPUT_MODE,
        )
        completed: dict[str, Any] = {"state": "failed", "code": "query_no_result"}
        async for event in self._query_service.answer_text(
            request,
            cancel_requested=lambda: session.is_interrupted,
        ):
            event_payload = event.to_dict()
            await sender({"type": "query_event", **event_payload})
            if event.event == "completed":
                data = event.data
                answer_source = str(data.get("answer_source") or "")
                if answer_source == "instruction":
                    func_call = data.get("func_call") or {}
                    await sender(
                        {
                            "type": "instruction",
                            "request_id": event.request_id,
                            "history_id": data.get("history_id"),
                            **func_call,
                        }
                    )
                else:
                    await sender(
                        {
                            "type": "answer",
                            "request_id": event.request_id,
                            "answer_source": answer_source,
                            "answer": data.get("answer", ""),
                            "references": data.get("references", []),
                            "history_id": data.get("history_id"),
                        }
                    )
                completed = {"state": "completed", **data}
            elif event.event == "failed":
                completed = {"state": "failed", **event.data}
            elif event.event == "cancelled":
                completed = {"state": "cancelled", **event.data}
        return completed

    async def _send_tts(
        self,
        session: AudioSession,
        answer: str,
        outcome: dict[str, Any],
        sender: AudioMessageSender,
    ) -> None:
        await _send_status(sender, "tts_started", "正在合成语音")
        audio_sender = OrderedAudioSender(sender)
        splitter = SentenceSplitter()
        segments = splitter.feed(answer) + splitter.flush()
        for segment in segments:
            if session.is_interrupted:
                break
            seq = audio_sender.next_seq()
            task = asyncio.create_task(
                self._synthesize_and_enqueue(normalize_for_tts(segment), seq, audio_sender)
            )
            audio_sender.add_task(task)
        stats = await audio_sender.flush()
        await sender(
            {
                "type": "audio_stream",
                "event": "finished",
                "full_text": answer,
                "references": outcome.get("references", []),
                "history_id": outcome.get("history_id"),
                "tts_success": stats.success_count > 0,
                "tts_failure_count": stats.failure_count,
            }
        )

    async def _synthesize_and_enqueue(
        self,
        text: str,
        sequence_id: int,
        audio_sender: OrderedAudioSender,
    ) -> None:
        try:
            result = await self._tts.synthesize(text, sequence_id=sequence_id)
        except Exception as exc:
            result = TTSResult(
                success=False,
                text=text,
                sequence_id=sequence_id,
                error_code="tts_exception",
                error_message=str(exc),
            )
        await audio_sender.enqueue(result)


async def _send_status(sender: AudioMessageSender, phase: str, text: str) -> None:
    await sender({"type": "status", "phase": phase, "text": text})


async def _send_error(sender: AudioMessageSender, code: str, message: str) -> None:
    await sender({"type": "error", "code": code, "message": message})
