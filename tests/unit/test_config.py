from biosafe.config import Settings


def test_settings_read_secrets_without_exposing_repr() -> None:
    settings = Settings.from_env(
        {
            "BIOSAFE_LOG_FILE": "/tmp/biosafe-test.log",
            "TTS_SAMPLE_RATE": "22050",
            "RAGFLOW_BASE_URL": "http://ragflow.test/",
            "RAGFLOW_API_KEY": "rag-secret",
            "CHAT_BASE_URL": "http://llm.test/v1/",
            "CHAT_API_KEY": "llm-secret",
            "CHAT_MODEL": "test-model",
            "ANSWER_EVALUATION_BASE_URL": "http://correction.test/v1/",
            "ANSWER_EVALUATION_API_KEY": "correction-secret",
            "ANSWER_EVALUATION_MODEL": "strong-model",
            "EVAL_ENABLED": "true",
            "EVAL_QUEUE_MAXSIZE": "7",
        }
    )

    assert settings.ragflow.base_url == "http://ragflow.test"
    assert str(settings.log_file) == "/tmp/biosafe-test.log"
    assert settings.tts.sample_rate == 22_050
    assert settings.llm.ready is True
    assert settings.correction.ready is True
    assert settings.correction.base_url == "http://correction.test/v1"
    assert settings.correction.queue_maxsize == 7
    rendered = repr(settings)
    assert "rag-secret" not in rendered
    assert "llm-secret" not in rendered
    assert "correction-secret" not in rendered
