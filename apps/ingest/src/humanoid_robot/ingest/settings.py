"""Runtime configuration for cortex-ingest."""

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


class AdapterSelection(BaseModel):
    """Adapter name + kwargs pair."""

    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class ParserBinding(BaseModel):
    """Which parser adapter handles a given file extension."""

    extension: str  # e.g. ".txt", ".md"
    adapter: AdapterSelection


class IngestStackSettings(BaseModel):
    """Which adapter to load per port slot."""

    chunker: AdapterSelection
    embedder: AdapterSelection
    vector_store: AdapterSelection
    parsers: tuple[ParserBinding, ...]


class IngestSettings(BaseSettings):
    """Top-level ingest configuration."""

    model_config = SettingsConfigDict(
        env_prefix="HR_INGEST__",
        env_nested_delimiter="__",
        yaml_file=None,
        extra="forbid",
    )

    environment: str = "prod"
    service_name: str = "cortex-ingest"
    log_level: str = "INFO"
    chunk_batch_size: int = 64
    stack: IngestStackSettings

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


def load_settings(*, config_path: Path) -> IngestSettings:
    IngestSettings.model_config = SettingsConfigDict(
        **{**IngestSettings.model_config, "yaml_file": str(config_path)}
    )
    return IngestSettings()
