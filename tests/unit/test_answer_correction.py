from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from biosafe.application.correction_dispatcher import AnswerCorrectionDispatcher
from biosafe.config import CorrectionConfig
from biosafe.domain.correction import CorrectionResult
from biosafe.domain.history import HistoryCreate
from biosafe.integrations.correction import CorrectionClientError, parse_correction_response
from biosafe.storage import AnswerCorrectionRepository, Database, HistoryRepository


class FakeCorrectionClient:
    def __init__(self, result: CorrectionResult | Exception):
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def generate(self, question: str, original_answer: str) -> CorrectionResult:
        self.calls.append((question, original_answer))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _history(database: Database, index: int = 1):
    return HistoryRepository(database).create(
        HistoryCreate(
            request_id=f"correction-request-{index}",
            session_id="session",
            created_at=datetime.now(UTC).isoformat(),
            experiment_id="generic",
            input_mode="text",
            question="新冠活病毒培养需要什么实验室？",
            answer_source="direct",
            system_answer="原系统答案",
        )
    )


def _config(**overrides) -> CorrectionConfig:
    values = {
        "enabled": True,
        "base_url": "http://correction.test/v1",
        "api_key": "test-secret",
        "model": "strong-model",
        "queue_maxsize": 4,
        "worker_count": 1,
        "drain_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return CorrectionConfig(**values)


def test_parse_correction_response_merges_and_deduplicates_sources() -> None:
    output = (
        'prefix {"can_answer":true,"answer":"应在三级实验室进行。",'
        '"cannot_answer_reason":"","citations":'
        '[{"title":"标准","url":"https://example.test/standard","note":"条款"}]} suffix'
    )
    payload = {
        "output": [
            {
                "content": [
                    {
                        "annotations": [
                            {
                                "title": "标准",
                                "url": "https://example.test/standard",
                                "note": "条款",
                            }
                        ]
                    }
                ]
            }
        ]
    }

    result = parse_correction_response(output, payload)

    assert result.can_answer is True
    assert result.answer == "应在三级实验室进行。"
    assert result.citations == [
        {"title": "标准", "url": "https://example.test/standard", "note": "条款"}
    ]


@pytest.mark.asyncio
async def test_dispatcher_processes_and_persists_correction(tmp_path: Path) -> None:
    database = Database(tmp_path / "correction.db")
    database.migrate()
    history = _history(database)
    repository = AnswerCorrectionRepository(database)
    result = CorrectionResult(
        can_answer=True,
        answer="经复核应在三级实验室进行。",
        citations=[{"title": "标准", "url": "https://example.test", "note": ""}],
    )
    client = FakeCorrectionClient(result)
    dispatcher = AnswerCorrectionDispatcher(
        repository=repository,
        client=client,
        config=_config(),
    )

    await dispatcher.start()
    queued = dispatcher.submit(history)
    assert queued is not None
    assert queued.status == "pending"
    await dispatcher.wait_until_idle()
    saved = repository.get_by_history_id(history.id)
    await dispatcher.close()

    assert client.calls == [(history.question, history.system_answer)]
    assert saved is not None
    assert saved.status == "success"
    assert saved.model == "strong-model"
    assert saved.answer == "经复核应在三级实验室进行。"
    assert saved.finished_at is not None


@pytest.mark.asyncio
async def test_dispatcher_recovers_pending_and_records_parse_failure(tmp_path: Path) -> None:
    database = Database(tmp_path / "recovery.db")
    database.migrate()
    history = _history(database)
    repository = AnswerCorrectionRepository(database)
    repository.enqueue(
        history_id=history.id,
        question=history.question,
        original_answer=history.system_answer,
    )
    client = FakeCorrectionClient(
        CorrectionClientError("correction_parse_error", "invalid structured response")
    )
    dispatcher = AnswerCorrectionDispatcher(
        repository=repository,
        client=client,
        config=_config(),
    )

    await dispatcher.start()
    await dispatcher.wait_until_idle()
    saved = repository.get_by_history_id(history.id)
    await dispatcher.close()

    assert len(client.calls) == 1
    assert saved is not None
    assert saved.status == "parse_error"
    assert saved.error == "invalid structured response"
