"""SQLite connection and incremental migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            experiment_id TEXT NOT NULL DEFAULT '',
            input_mode TEXT NOT NULL DEFAULT 'text',
            question TEXT NOT NULL,
            answer_source TEXT NOT NULL,
            system_answer TEXT NOT NULL DEFAULT '',
            corrected_answer TEXT NOT NULL DEFAULT '',
            references_json TEXT NOT NULL DEFAULT '[]',
            ragflow_request_json TEXT NOT NULL DEFAULT '{}',
            latency_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'completed',
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            seed_fingerprint TEXT UNIQUE,
            correction_updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_history_created_at ON chat_history(created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_history_experiment
        ON chat_history(experiment_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS admin_user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS experiment_dataset_binding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            dataset_name_snapshot TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(experiment_id, dataset_id)
        );
        """,
    ),
)


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migration "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {
                row[0]
                for row in connection.execute("SELECT version FROM schema_migration").fetchall()
            }
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                connection.executescript(sql)
                connection.execute("INSERT INTO schema_migration(version) VALUES (?)", (version,))
            connection.commit()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=OFF")
        try:
            yield connection
        finally:
            connection.close()
