import json
import logging

from biosafe.logging import configure_logging, redact


def test_redact_nested_credentials_and_inline_headers() -> None:
    value = {
        "Authorization": "Bearer abc123",
        "nested": {"api_key": "secret", "message": "token=visible password:bad"},
    }

    redacted = redact(value)

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert "visible" not in redacted["nested"]["message"]
    assert "bad" not in redacted["nested"]["message"]


def test_configure_logging_writes_redacted_json_file(tmp_path) -> None:
    log_file = tmp_path / "logs" / "api.log"
    configure_logging("INFO", log_file)

    logging.getLogger("biosafe.test").info("password=secret service started")

    payload = json.loads(log_file.read_text(encoding="utf-8"))
    assert payload["logger"] == "biosafe.test"
    assert "secret" not in payload["message"]
    assert "[REDACTED]" in payload["message"]


def test_structured_details_are_written_and_recursively_redacted(tmp_path) -> None:
    log_file = tmp_path / "logs" / "api.log"
    configure_logging("INFO", log_file)

    logging.getLogger("biosafe.test").warning(
        "citation failed",
        extra={
            "request_id": "req-log",
            "error_code": "rag_citation_incomplete",
            "details": {
                "initial": {"draft": "回答包含 token=secret-value"},
                "chunks": [{"document_name": "规则.pdf", "api_key": "hidden"}],
            },
        },
    )

    payload = json.loads(log_file.read_text(encoding="utf-8"))
    assert payload["request_id"] == "req-log"
    assert payload["error_code"] == "rag_citation_incomplete"
    assert "secret-value" not in payload["details"]["initial"]["draft"]
    assert payload["details"]["chunks"][0]["api_key"] == "[REDACTED]"
    assert payload["details"]["chunks"][0]["document_name"] == "规则.pdf"
