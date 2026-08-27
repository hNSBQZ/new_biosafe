"""SSE chat route."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from biosafe.application.query_service import QueryService
from biosafe.domain.query import QueryRequest as DomainQueryRequest
from services.api.deps import get_query_service
from services.api.schemas import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])
Service = Annotated[QueryService, Depends(get_query_service)]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"


@router.post("")
async def chat(payload: ChatRequest, request: Request, service: Service) -> StreamingResponse:
    query = DomainQueryRequest(
        question=payload.question,
        experiment_id=payload.experiment_id,
        session_id=payload.session_id,
        input_mode=payload.input_mode,
    )

    async def event_stream():
        async for event in service.answer_text(
            query,
            cancel_requested=request.is_disconnected,
        ):
            yield _sse(event.to_dict())

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
