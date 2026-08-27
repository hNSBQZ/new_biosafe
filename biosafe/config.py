"""Environment-only application configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


def _value(env: Mapping[str, str], name: str, default: str = "") -> str:
    return env.get(name, default).strip()


def _integer(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _value(env, name)
    return int(raw) if raw else default


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _value(env, name)
    return float(raw) if raw else default


def _csv(env: Mapping[str, str], name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = _value(env, name)
    return tuple(part.strip() for part in raw.split(",") if part.strip()) if raw else default


@dataclass(frozen=True)
class RAGFlowConfig:
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = 30.0
    dataset_ids: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return bool(self.base_url and self.api_key)


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout_seconds: float = 60.0

    @property
    def ready(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


@dataclass(frozen=True)
class ASRConfig:
    uri: str = ""
    connect_timeout: float = 10.0
    recognize_timeout: float = 60.0

    @property
    def ready(self) -> bool:
        return bool(self.uri)


@dataclass(frozen=True)
class TTSConfig:
    base_url: str = ""
    model: str = ""
    voice: str = ""
    response_format: str = "pcm"
    timeout: float = 60.0
    max_concurrent: int = 2
    max_retries: int = 1
    retry_base_delay: float = 0.25

    @property
    def ready(self) -> bool:
        return bool(self.base_url and self.model and self.voice)


@dataclass(frozen=True)
class AdminConfig:
    username: str = "admin"
    password: str = field(default="", repr=False)
    token_secret: str = field(default="", repr=False)
    token_ttl_seconds: int = 28_800


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_path: Path = Path("data/biosafe.db")
    experiments_dir: Path = Path("experiments")
    log_level: str = "INFO"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    ragflow: RAGFlowConfig = field(default_factory=RAGFlowConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = env if env is not None else os.environ
        return cls(
            environment=_value(source, "BIOSAFE_ENV", "development"),
            database_path=Path(_value(source, "BIOSAFE_DATABASE_PATH", "data/biosafe.db")),
            experiments_dir=Path(_value(source, "BIOSAFE_EXPERIMENTS_DIR", "experiments")),
            log_level=_value(source, "BIOSAFE_LOG_LEVEL", "INFO").upper(),
            cors_origins=_csv(source, "BIOSAFE_CORS_ORIGINS", ("http://localhost:5173",)),
            ragflow=RAGFlowConfig(
                base_url=_value(source, "RAGFLOW_BASE_URL").rstrip("/"),
                api_key=_value(source, "RAGFLOW_API_KEY"),
                timeout_seconds=_float(source, "RAGFLOW_TIMEOUT_SECONDS", 30.0),
                dataset_ids=_csv(source, "RAGFLOW_DATASET_IDS"),
            ),
            llm=LLMConfig(
                base_url=_value(source, "CHAT_BASE_URL").rstrip("/"),
                api_key=_value(source, "CHAT_API_KEY"),
                model=_value(source, "CHAT_MODEL"),
                timeout_seconds=_float(source, "CHAT_TIMEOUT_SECONDS", 60.0),
            ),
            asr=ASRConfig(
                uri=_value(source, "ASR_URI"),
                connect_timeout=_float(source, "ASR_CONNECT_TIMEOUT", 10.0),
                recognize_timeout=_float(source, "ASR_RECOGNIZE_TIMEOUT", 60.0),
            ),
            tts=TTSConfig(
                base_url=_value(source, "TTS_BASE_URL").rstrip("/"),
                model=_value(source, "TTS_MODEL"),
                voice=_value(source, "TTS_VOICE"),
                response_format=_value(source, "TTS_RESPONSE_FORMAT", "pcm"),
                timeout=_float(source, "TTS_TIMEOUT", 60.0),
                max_concurrent=_integer(source, "TTS_MAX_CONCURRENT", 2),
                max_retries=_integer(source, "TTS_MAX_RETRIES", 1),
                retry_base_delay=_float(source, "TTS_RETRY_BASE_DELAY", 0.25),
            ),
            admin=AdminConfig(
                username=_value(source, "BIOSAFE_ADMIN_USERNAME", "admin"),
                password=_value(source, "BIOSAFE_ADMIN_PASSWORD"),
                token_secret=_value(source, "BIOSAFE_ADMIN_TOKEN_SECRET"),
                token_ttl_seconds=_integer(source, "BIOSAFE_ADMIN_TOKEN_TTL_SECONDS", 28_800),
            ),
        )
