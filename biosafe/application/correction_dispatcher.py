"""Bounded background dispatcher for independent answer correction."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from biosafe.config import CorrectionConfig
from biosafe.domain.correction import AnswerCorrection
from biosafe.domain.history import ChatHistory
from biosafe.integrations.correction import (
    AnswerCorrectionClientProtocol,
    CorrectionClientError,
)
from biosafe.storage.correction_repository import AnswerCorrectionRepository

logger = logging.getLogger(__name__)


class CorrectionDispatcherProtocol(Protocol):
    @property
    def is_running(self) -> bool: ...

    def submit(self, history: ChatHistory, *, retry: bool = False) -> AnswerCorrection | None: ...


class AnswerCorrectionDispatcher:
    def __init__(
        self,
        *,
        repository: AnswerCorrectionRepository,
        client: AnswerCorrectionClientProtocol,
        config: CorrectionConfig,
    ):
        self._repository = repository
        self._client = client
        self._config = config
        self._queue: asyncio.Queue[int] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._started = False
        self._closing = False

    @property
    def is_running(self) -> bool:
        return self._started and not self._closing

    def stats(self) -> dict[str, Any]:
        return {
            "enabled": self._config.ready,
            "running": self.is_running,
            "queue_size": self._queue.qsize() if self._queue is not None else 0,
            "queue_maxsize": self._config.queue_maxsize,
            "worker_count": len(self._workers),
            "model": self._config.model,
        }

    async def start(self) -> None:
        if self._started or not self._config.ready:
            return
        self._queue = asyncio.Queue(maxsize=self._config.queue_maxsize)
        self._started = True
        for task in self._repository.list_unfinished():
            self._repository.mark_pending(task.id)
            try:
                self._queue.put_nowait(task.id)
            except asyncio.QueueFull:
                self._repository.mark_failed(
                    task.id, status="dropped", error="correction queue full during recovery"
                )
        for index in range(self._config.worker_count):
            self._workers.append(
                asyncio.create_task(self._worker(index), name=f"answer-correction-{index}")
            )
        logger.info("answer correction dispatcher started", extra={"details": self.stats()})

    async def close(self) -> None:
        if not self._started:
            return
        self._closing = True
        assert self._queue is not None
        try:
            await asyncio.wait_for(
                self._queue.join(), timeout=self._config.drain_timeout_seconds
            )
        except TimeoutError:
            logger.warning(
                "answer correction queue drain timed out", extra={"details": self.stats()}
            )
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False
        self._closing = False

    def submit(self, history: ChatHistory, *, retry: bool = False) -> AnswerCorrection | None:
        if not self.is_running or self._queue is None:
            return None
        task, should_queue = self._repository.enqueue(
            history_id=history.id,
            question=history.question,
            original_answer=history.system_answer,
            force=retry,
        )
        if not should_queue:
            return task
        try:
            self._queue.put_nowait(task.id)
        except asyncio.QueueFull:
            self._repository.mark_failed(
                task.id, status="dropped", error="correction queue full"
            )
            task = self._repository.get(task.id) or task
            logger.warning(
                "answer correction queue full",
                extra={"details": {"history_id": history.id, **self.stats()}},
            )
        return task

    async def wait_until_idle(self, timeout: float = 5.0) -> None:
        if self._queue is not None:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)

    async def _worker(self, index: int) -> None:
        assert self._queue is not None
        while True:
            task_id = await self._queue.get()
            try:
                await self._handle(task_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "answer correction worker failed",
                    extra={"details": {"worker": index, "task_id": task_id}},
                )
            finally:
                self._queue.task_done()

    async def _handle(self, task_id: int) -> None:
        task = self._repository.get(task_id)
        if task is None:
            return
        self._repository.mark_running(task_id, model=self._config.model)
        try:
            result = await self._client.generate(task.question, task.original_answer)
        except CorrectionClientError as exc:
            status = "parse_error" if exc.code == "correction_parse_error" else "request_error"
            self._repository.mark_failed(task_id, status=status, error=exc.message)
            logger.warning(
                "answer correction failed",
                extra={
                    "error_code": exc.code,
                    "details": {"history_id": task.history_id, "task_id": task_id},
                },
            )
            return
        self._repository.mark_success(task_id, model=self._config.model, result=result)
