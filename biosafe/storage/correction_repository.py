"""SQLite repository for asynchronous answer correction tasks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from biosafe.domain.correction import AnswerCorrection, CorrectionResult
from biosafe.domain.history import decode_json_list
from biosafe.storage.database import Database

ACTIVE_STATUSES = ("pending", "running")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AnswerCorrectionRepository:
    def __init__(self, database: Database):
        self.database = database

    def enqueue(
        self,
        *,
        history_id: int,
        question: str,
        original_answer: str,
        force: bool = False,
    ) -> tuple[AnswerCorrection, bool]:
        now = _now()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM answer_correction WHERE history_id = ?", (history_id,)
            ).fetchone()
            if row is not None and (row["status"] in ACTIVE_STATUSES or not force):
                connection.commit()
                return self._from_row(row), False
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO answer_correction (
                        history_id, question, original_answer, status, enqueued_at
                    ) VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (history_id, question, original_answer, now),
                )
                task_id = int(cursor.lastrowid)
            else:
                task_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE answer_correction
                    SET question = ?, original_answer = ?, status = 'pending', model = '',
                        can_answer = NULL, answer = '', cannot_answer_reason = '',
                        citations_json = '[]', error = '', enqueued_at = ?,
                        started_at = NULL, finished_at = NULL
                    WHERE id = ?
                    """,
                    (question, original_answer, now, task_id),
                )
            connection.commit()
            created = connection.execute(
                "SELECT * FROM answer_correction WHERE id = ?", (task_id,)
            ).fetchone()
        assert created is not None
        return self._from_row(created), True

    def get(self, task_id: int) -> AnswerCorrection | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM answer_correction WHERE id = ?", (task_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_history_id(self, history_id: int) -> AnswerCorrection | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM answer_correction WHERE history_id = ?", (history_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def get_for_history_ids(self, history_ids: list[int]) -> dict[int, AnswerCorrection]:
        if not history_ids:
            return {}
        placeholders = ",".join("?" for _ in history_ids)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM answer_correction WHERE history_id IN ({placeholders})",
                history_ids,
            ).fetchall()
        items = [self._from_row(row) for row in rows]
        return {item.history_id: item for item in items}

    def list_unfinished(self) -> list[AnswerCorrection]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM answer_correction WHERE status IN ('pending', 'running') "
                "ORDER BY enqueued_at, id"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def mark_pending(self, task_id: int) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE answer_correction SET status = 'pending', started_at = NULL, "
                "finished_at = NULL, error = '' WHERE id = ?",
                (task_id,),
            )
            connection.commit()

    def mark_running(self, task_id: int, *, model: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE answer_correction SET status = 'running', model = ?, started_at = ?, "
                "finished_at = NULL, error = '' WHERE id = ?",
                (model, _now(), task_id),
            )
            connection.commit()

    def mark_success(self, task_id: int, *, model: str, result: CorrectionResult) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE answer_correction
                SET status = 'success', model = ?, can_answer = ?, answer = ?,
                    cannot_answer_reason = ?, citations_json = ?, error = '', finished_at = ?
                WHERE id = ?
                """,
                (
                    model,
                    int(result.can_answer),
                    result.answer,
                    result.cannot_answer_reason,
                    json.dumps(result.citations, ensure_ascii=False),
                    _now(),
                    task_id,
                ),
            )
            connection.commit()

    def mark_failed(self, task_id: int, *, status: str, error: str) -> None:
        if status not in {"parse_error", "request_error", "dropped"}:
            raise ValueError(f"invalid correction failure status: {status}")
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE answer_correction SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (status, error[:2000], _now(), task_id),
            )
            connection.commit()

    @staticmethod
    def _from_row(row: Any) -> AnswerCorrection:
        can_answer = row["can_answer"]
        return AnswerCorrection(
            id=int(row["id"]),
            history_id=int(row["history_id"]),
            question=str(row["question"]),
            original_answer=str(row["original_answer"]),
            status=str(row["status"]),
            model=str(row["model"]),
            can_answer=None if can_answer is None else bool(can_answer),
            answer=str(row["answer"]),
            cannot_answer_reason=str(row["cannot_answer_reason"]),
            citations=decode_json_list(row["citations_json"], field_name="correction_citations"),
            error=str(row["error"]),
            enqueued_at=str(row["enqueued_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
