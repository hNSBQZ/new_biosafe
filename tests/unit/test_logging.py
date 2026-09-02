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
