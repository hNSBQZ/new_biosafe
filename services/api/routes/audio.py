"""Audio chat WebSocket route."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from uuid import uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from services.audio import AudioPipeline, AudioSession

router = APIRouter(tags=["audio"])


@router.websocket("/api/v1/chat/audio")
async def audio_chat(
    websocket: WebSocket,
    experiment_id: str = Query(default="generic"),
) -> None:
    await websocket.accept()
    pipeline: AudioPipeline = websocket.app.state.audio_pipeline
    session = AudioSession(session_id=uuid4().hex, experiment_id=experiment_id)
    send_lock = asyncio.Lock()

    async def send(message: dict) -> None:
        async with send_lock:
            await websocket.send_json(message)

    await send(
        {
            "type": "connected",
            "session_id": session.session_id,
            "experiment_id": experiment_id,
            "sample_rate": session.sample_rate,
            "format": session.audio_format,
            "message": "connected",
        }
    )

    processing_task: asyncio.Task | None = None
    try:
        while True:
            if processing_task is not None:
                receive_task = asyncio.create_task(websocket.receive_text())
                done, pending = await asyncio.wait(
                    {processing_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if processing_task in done:
                    receive_task.cancel()
                    await asyncio.gather(receive_task, return_exceptions=True)
                    await processing_task
                    break
                raw = receive_task.result()
            else:
                raw = await websocket.receive_text()

            action = await _handle_message(raw, session, send)
            if action == "break":
                break
            if action == "process" and processing_task is None:
                audio_bytes = session.finish_recording()
                session.is_processing = True
                processing_task = asyncio.create_task(
                    pipeline.process_audio(
                        session=session,
                        audio_bytes=audio_bytes,
                        sender=send,
                    )
                )
    except WebSocketDisconnect:
        session.interrupt()
    finally:
        if processing_task is not None and not processing_task.done():
            session.interrupt()
            await asyncio.gather(processing_task, return_exceptions=True)


async def _handle_message(
    raw: str,
    session: AudioSession,
    send,
) -> str:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        await send({"type": "error", "code": "audio_invalid_json", "message": "Invalid JSON"})
        return "break"

    message_type = message.get("type")
    if message_type == "audio_start":
        if session.is_processing:
            await send(
                {
                    "type": "error",
                    "code": "audio_already_processing",
                    "message": "Audio is already being processed",
                }
            )
            return "continue"
        session.start_recording(
            sample_rate=_optional_int(message.get("sample_rate")),
            audio_format=str(message.get("format") or "pcm"),
        )
        await send({"type": "status", "phase": "recording_started", "text": "recording started"})
        return "continue"

    if message_type == "audio_data":
        if not session.is_recording:
            await send(
                {
                    "type": "error",
                    "code": "audio_not_recording",
                    "message": "audio_start is required before audio_data",
                }
            )
            return "continue"
        try:
            audio_bytes = base64.b64decode(str(message.get("data") or ""), validate=True)
        except (binascii.Error, ValueError):
            await send(
                {
                    "type": "error",
                    "code": "audio_invalid_base64",
                    "message": "audio_data.data must be base64",
                }
            )
            return "break"
        session.append_audio(audio_bytes)
        await send({"type": "packet_ack", "seq": message.get("seq", 0)})
        return "continue"

    if message_type == "audio_end":
        if not session.is_recording:
            await send(
                {
                    "type": "error",
                    "code": "audio_not_recording",
                    "message": "audio_start is required before audio_end",
                }
            )
            return "break"
        return "process"

    if message_type == "interrupt":
        session.interrupt()
        await send({"type": "status", "phase": "interrupt_requested", "text": "interrupted"})
        return "continue"

    await send(
        {
            "type": "error",
            "code": "audio_unknown_message",
            "message": "Unknown audio message type",
        }
    )
    return "continue"


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
