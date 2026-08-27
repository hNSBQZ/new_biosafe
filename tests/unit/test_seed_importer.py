from pathlib import Path

from openpyxl import Workbook

from biosafe.storage import Database, HistoryRepository
from biosafe.storage.seed_importer import import_excel


def test_excel_import_is_idempotent_and_maps_answers(tmp_path: Path) -> None:
    excel = tmp_path / "seed.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["timestamp", "question", "answer", "original_answer", "references"])
    sheet.append(
        [
            "2026-08-27T10:00:00+08:00",
            "测试问题",
            "纠错答案",
            "系统答案",
            '[{"document_name":"规则.pdf","content":"引用"}]',
        ]
    )
    workbook.save(excel)
    database = Database(tmp_path / "seed.db")
    database.migrate()
    repository = HistoryRepository(database)

    first = import_excel(excel, repository)
    second = import_excel(excel, repository)

    assert (first.added, first.skipped, first.errors) == (1, 0, 0)
    assert (second.added, second.skipped, second.errors) == (0, 1, 0)
    items, total = repository.list()
    assert total == 1
    assert items[0].system_answer == "系统答案"
    assert items[0].corrected_answer == "纠错答案"
    assert items[0].references[0]["document_name"] == "规则.pdf"
