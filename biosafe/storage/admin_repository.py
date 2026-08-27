"""Repositories for admin identities and experiment dataset bindings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from biosafe.storage.database import Database


class AdminRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(self, username: str, password_hash: str, role: str = "admin") -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO admin_user(username, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash=excluded.password_hash, role=excluded.role,
                    enabled=1, updated_at=excluded.updated_at
                """,
                (username, password_hash, role, now, now),
            )
            connection.commit()

    def get(self, username: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM admin_user WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None


class BindingRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(
        self, experiment_id: str, dataset_id: str, dataset_name: str, enabled: bool = True
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO experiment_dataset_binding(
                    experiment_id, dataset_id, dataset_name_snapshot,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id, dataset_id) DO UPDATE SET
                    dataset_name_snapshot=excluded.dataset_name_snapshot,
                    enabled=excluded.enabled, updated_at=excluded.updated_at
                """,
                (experiment_id, dataset_id, dataset_name, int(enabled), now, now),
            )
            connection.commit()

    def list_for_experiment(self, experiment_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM experiment_dataset_binding WHERE experiment_id = ? AND enabled = 1",
                (experiment_id,),
            ).fetchall()
        return [dict(row) for row in rows]
