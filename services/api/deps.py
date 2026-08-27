from fastapi import Request

from biosafe.storage.history_repository import HistoryRepository


def get_history_repository(request: Request) -> HistoryRepository:
    return request.app.state.history_repository
