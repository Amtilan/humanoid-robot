"""Runtime configuration for cortex-voice."""

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
    client_name: str = "cortex-voice"
    connect_timeout_s: float = 5.0
    reconnect_time_wait_s: float = 1.0
    max_reconnect_attempts: int = -1


class AdapterSelection(BaseModel):
    """Adapter name + kwargs pair for one port slot."""

    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class VoiceStackSettings(BaseModel):
    """Which adapter to load for each port slot."""

    audio_in: AdapterSelection
    audio_out: AdapterSelection
    vad: AdapterSelection
    asr: AdapterSelection
    tts: AdapterSelection
    wake_word: AdapterSelection | None = None


class SessionSettings(BaseModel):
    language_hint: str = "ru"
    min_speech_ms: int = 200
    silence_hang_ms: int = 600
    max_utterance_ms: int = 10_000
    require_wake_word: bool = False
    wake_word_grace_ms: int = 1_500
    wake_name: str | None = None


class VoiceRunnerSettings(BaseSettings):
    """Top-level runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="HR_VOICE__",
        env_nested_delimiter="__",
        yaml_file=None,
        extra="forbid",
    )

    environment: str = "prod"
    service_name: str = "cortex-voice"
    log_level: str = "INFO"
    nats: NatsSettings = NatsSettings()
    session: SessionSettings = SessionSettings()
    stack: VoiceStackSettings

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


def load_settings(*, config_path: Path) -> VoiceRunnerSettings:
    """YAML config is mandatory for the voice runner — stack is data-driven."""
    VoiceRunnerSettings.model_config = SettingsConfigDict(
        **{**VoiceRunnerSettings.model_config, "yaml_file": str(config_path)}
    )
    return VoiceRunnerSettings()
