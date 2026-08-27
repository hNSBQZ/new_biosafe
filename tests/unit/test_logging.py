from biosafe.logging import redact


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
