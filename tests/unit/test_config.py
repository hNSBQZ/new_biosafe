from biosafe.config import Settings


def test_settings_read_secrets_without_exposing_repr() -> None:
    settings = Settings.from_env(
        {
            "RAGFLOW_BASE_URL": "http://ragflow.test/",
            "RAGFLOW_API_KEY": "rag-secret",
            "CHAT_BASE_URL": "http://llm.test/v1/",
            "CHAT_API_KEY": "llm-secret",
            "CHAT_MODEL": "test-model",
            "CORRECTION_BASE_URL": "http://correction.test/v1/",
            "CORRECTION_API_KEY": "correction-secret",
            "CORRECTION_MODEL": "strong-model",
            "CORRECTION_ENABLED": "true",
        }
    )

    assert settings.ragflow.base_url == "http://ragflow.test"
    assert str(settings.log_file) == "logs/biosafe-api.log"
    assert settings.tts.sample_rate == 24_000
    assert settings.llm.ready is True
    assert settings.correction.ready is True
    assert settings.correction.base_url == "http://correction.test/v1"
    assert settings.correction.queue_maxsize == 200
    rendered = repr(settings)
    assert "rag-secret" not in rendered
    assert "llm-secret" not in rendered
    assert "correction-secret" not in rendered
