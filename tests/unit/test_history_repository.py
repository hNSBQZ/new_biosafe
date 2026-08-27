import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from biosafe.domain.history import HistoryCreate
from biosafe.storage import Database, HistoryRepository


def _item(index: int) -> HistoryCreate:
    return HistoryCreate(
        request_id=f"request-{index}",
        session_id="session",
        created_at=datetime.now(UTC).isoformat(),
        experiment_id="exp-1",
        input_mode="text",
        question=f"question-{index}",
        answer_source="direct",
        system_answer="answer",
        references=[{"chunk_id": "chunk-1"}],
    )


def test_migration_is_repeatable_and_corrupt_json_does_not_break_reads(tmp_path: Path) -> None:
    database = Database(tmp_path / "history.db")
    database.migrate()
    database.migrate()
    repository = HistoryRepository(database)
    created = repository.create(_item(1))

    with database.connection() as connection:
        connection.execute(
            "UPDATE chat_history SET references_json = ?, latency_json = ? WHERE id = ?",
            ("not-json", "[]", created.id),
        )

    loaded = repository.get(created.id)
    assert loaded is not None
    assert loaded.references == []
    assert loaded.latency == {}
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0] == 1


def test_concurrent_writes_are_serialized(tmp_path: Path) -> None:
    database = Database(tmp_path / "concurrent.db")
    database.migrate()
    repository = HistoryRepository(database)

    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(repository.create, [_item(index) for index in range(24)]))

    items, total = repository.list(page_size=100)
    assert len(created) == 24
    assert total == len(items) == 24
    assert len({item.request_id for item in items}) == 24


def test_duplicate_request_id_is_rejected(tmp_path: Path) -> None:
    database = Database(tmp_path / "unique.db")
    database.migrate()
    repository = HistoryRepository(database)
    repository.create(_item(1))

    try:
        repository.create(_item(1))
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("duplicate request_id should fail")
