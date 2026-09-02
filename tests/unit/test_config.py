from biosafe.config import Settings


def test_settings_read_secrets_without_exposing_repr() -> None:
    settings = Settings.from_env(
        {
            "BIOSAFE_LOG_FILE": "/tmp/biosafe-test.log",
            "RAGFLOW_BASE_URL": "http://ragflow.test/",
            "RAGFLOW_API_KEY": "rag-secret",
            "CHAT_BASE_URL": "http://llm.test/v1/",
            "CHAT_API_KEY": "llm-secret",
            "CHAT_MODEL": "test-model",
        }
    )

    assert settings.ragflow.base_url == "http://ragflow.test"
    assert str(settings.log_file) == "/tmp/biosafe-test.log"
    assert settings.llm.ready is True
    rendered = repr(settings)
    assert "rag-secret" not in rendered
    assert "llm-secret" not in rendered
