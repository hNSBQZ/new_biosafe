"""Flat SQLite history repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from biosafe.domain.history import ChatHistory, HistoryCreate, decode_json_list, decode_json_object
from biosafe.storage.database import Database


class HistoryRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(self, item: HistoryCreate) -> ChatHistory:
        values = (
            item.request_id,
            item.session_id,
            item.created_at,
            item.experiment_id,
            item.input_mode,
            item.question,
            item.answer_source,
            item.system_answer,
            item.corrected_answer,
            json.dumps(item.references, ensure_ascii=False),
            json.dumps(item.ragflow_request, ensure_ascii=False),
            json.dumps(item.latency, ensure_ascii=False),
            item.status,
            item.error_code,
            item.error_message,
            item.seed_fingerprint,
        )
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT INTO chat_history (
                    request_id, session_id, created_at, experiment_id, input_mode, question,
                    answer_source, system_answer, corrected_answer, references_json,
                    ragflow_request_json, latency_json, status, error_code, error_message,
                    seed_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM chat_history WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        assert row is not None
        return self._from_row(row)

    def get(self, history_id: int) -> ChatHistory | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM chat_history WHERE id = ?", (history_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_request_id(self, request_id: str) -> ChatHistory | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM chat_history WHERE request_id = ?", (request_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        experiment_id: str | None = None,
        status: str | None = None,
    ) -> tuple[list[ChatHistory], int]:
        conditions: list[str] = []
        params: list[Any] = []
        if experiment_id:
            conditions.append("experiment_id = ?")
            params.append(experiment_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.database.connection() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) FROM chat_history{where}", params).fetchone()[
                    0
                ]
            )
            rows = connection.execute(
                f"SELECT * FROM chat_history{where} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return [self._from_row(row) for row in rows], total

    def update_correction(self, history_id: int, corrected_answer: str) -> ChatHistory | None:
        now = datetime.now(UTC).isoformat()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE chat_history SET corrected_answer = ?, correction_updated_at = ? "
                "WHERE id = ?",
                (corrected_answer, now, history_id),
            )
            connection.commit()
        return self.get(history_id) if cursor.rowcount else None

    def exists_seed(self, fingerprint: str) -> bool:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM chat_history WHERE seed_fingerprint = ?", (fingerprint,)
            ).fetchone()
        return row is not None

    @staticmethod
    def _from_row(row: Any) -> ChatHistory:
        return ChatHistory(
            id=row["id"],
            request_id=row["request_id"],
            session_id=row["session_id"],
            created_at=row["created_at"],
            experiment_id=row["experiment_id"],
            input_mode=row["input_mode"],
            question=row["question"],
            answer_source=row["answer_source"],
            system_answer=row["system_answer"],
            corrected_answer=row["corrected_answer"],
            references=decode_json_list(row["references_json"], field_name="references"),
            ragflow_request=decode_json_object(row["ragflow_request_json"]),
            latency=decode_json_object(row["latency_json"]),
            status=row["status"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            correction_updated_at=row["correction_updated_at"],
        )
