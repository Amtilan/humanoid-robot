"""Runtime configuration for cortex-rag."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class NatsSettings(BaseModel):
    servers: tuple[str, ...] = ("nats://127.0.0.1:4222",)
    client_name: str = "cortex-rag"
    connect_timeout_s: float = 5.0
    reconnect_time_wait_s: float = 1.0
    max_reconnect_attempts: int = -1


class AdapterSelection(BaseModel):
    """Adapter name + kwargs pair for one port slot."""

    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class RagStackSettings(BaseModel):
    """Which adapter to load for each RAG port slot."""

    llm: AdapterSelection
    embedder: AdapterSelection
    reranker: AdapterSelection
    vector_store: AdapterSelection


class QaSettings(BaseModel):
    top_k_retrieve: int = 8
    top_k_after_rerank: int = 4
    min_top1_rerank_score: float = 0.35
    min_chunk_coverage: int = 2
    max_answer_tokens: int = 768
    max_retries_on_citation_fail: int = 1


class ConversationSettings(BaseModel):
    """Tuning for the conversational (RAG-augmented chat) path."""

    retrieve: bool = True
    top_k_retrieve: int = 6
    top_k_context: int = 3
    min_context_score: float = 0.30
    temperature: float = 0.7
    max_tokens: int = 512
    # Persona / system prompt overrides. When unset, the ConversationConfig
    # code defaults (the "Слуга" robot persona) apply. Set these to make the
    # robot answer as any character you like.
    system_prompt_ru: str | None = None
    system_prompt_en: str | None = None


class GuardSettings(BaseModel):
    """Security-desk (пункт охраны) mode."""

    # When true, «оформите визит»-style phrases (or visit.intake.start from
    # the guard panel) run the sequential visitor interview.
    intake_enabled: bool = False
    # Customer reference data (rooms, FAQ, справка) for consultations.
    kb_path: str = "/etc/humanoid-robot/guard-kb.yaml"


class WallIntentSettings(BaseModel):
    """Presenter mode — voice commands that drive the video wall."""

    enabled: bool = False
    # Customer overrides for aliases / spoken accompaniment texts; the
    # built-in matrix (plan §5) applies when the file is absent.
    config_path: str = "/etc/humanoid-robot/wall-intents.yaml"


class RagRunnerSettings(BaseSettings):
    """Top-level RAG configuration."""

    model_config = SettingsConfigDict(
        env_prefix="HR_RAG__",
        env_nested_delimiter="__",
        yaml_file=None,
        extra="forbid",
    )

    environment: str = "prod"
    service_name: str = "cortex-rag"
    log_level: str = "INFO"
    # "conversation" = RAG-augmented chat (answers anything, uses docs when
    # relevant); "grounded" = strict document-only QA that rejects off-KB
    # questions.
    mode: str = "conversation"
    nats: NatsSettings = NatsSettings()
    qa: QaSettings = QaSettings()
    conversation: ConversationSettings = ConversationSettings()
    guard: GuardSettings = GuardSettings()
    wall: WallIntentSettings = WallIntentSettings()
    stack: RagStackSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_source = YamlConfigSettingsSource(settings_cls)
        return (init_settings, env_settings, yaml_source, dotenv_settings, file_secret_settings)


def load_settings(*, config_path: Path) -> RagRunnerSettings:
    """YAML config is mandatory — the stack is data-driven."""
    RagRunnerSettings.model_config = SettingsConfigDict(
        **{**RagRunnerSettings.model_config, "yaml_file": str(config_path)}
    )
    return RagRunnerSettings()
