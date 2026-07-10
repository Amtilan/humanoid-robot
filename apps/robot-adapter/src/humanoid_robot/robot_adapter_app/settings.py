"""Runtime configuration for cortex-robot-adapter."""

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
    client_name: str = "cortex-robot-adapter"
    connect_timeout_s: float = 5.0
    reconnect_time_wait_s: float = 1.0
    max_reconnect_attempts: int = -1


class RobotAdapterSettings(BaseSettings):
    """Runner-level settings; adapter kwargs come from `adapter_config`."""

    model_config = SettingsConfigDict(
        env_prefix="HR_ROBOT_ADAPTER__",
        env_nested_delimiter="__",
        yaml_file=None,
        extra="forbid",
    )

    environment: str = "prod"
    service_name: str = "cortex-robot-adapter"
    adapter_name: str = "unitree_g1_edu"
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    nats: NatsSettings = NatsSettings()
    log_level: str = "INFO"
    telemetry_interval_s: float = 5.0

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


def load_settings(*, config_path: Path | None = None) -> RobotAdapterSettings:
    if config_path is not None:
        RobotAdapterSettings.model_config = SettingsConfigDict(
            **{**RobotAdapterSettings.model_config, "yaml_file": str(config_path)}
        )
    return RobotAdapterSettings()
