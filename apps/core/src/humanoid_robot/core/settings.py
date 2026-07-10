"""Runtime configuration.

Layered defaults: package defaults → YAML config file → environment variables.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class HttpSettings(BaseModel):
    host: str = "0.0.0.0"  # noqa: S104 — listen on all interfaces by design
    port: int = Field(default=8080, ge=1, le=65_535)


class NatsSettings(BaseModel):
    servers: tuple[str, ...] = ("nats://127.0.0.1:4222",)
    client_name: str = "cortex-core"
    connect_timeout_s: float = 5.0
    reconnect_time_wait_s: float = 1.0
    max_reconnect_attempts: int = -1
    user_credentials: str | None = None
    tls_ca: str | None = None
    tls_cert: str | None = None
    tls_key: str | None = None


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    otlp_endpoint: str = "http://127.0.0.1:4318/v1/traces"
    tracing_enabled: bool = True


class SafetySettings(BaseModel):
    """Safety gate configuration.

    `allowed_capabilities` is fail-closed: capabilities not listed here
    are denied.  Default set intentionally excludes free-form locomotion
    to prevent accidental motion on boot.
    """

    allowed_capabilities: tuple[str, ...] = (
        "arms.gesture",
        "head.pose",
        "locomotion.move",
        "voice.speak",
    )
    rate_limit_window_s: float = 5.0
    rate_limit_max_events: int = 20
    watchdog_timeout_s: float = 5.0
    watchdog_check_interval_s: float = 1.0
    command_timeout_s: float = 3.0
    command_check_interval_s: float = 0.5
    audit_db_path: Path = Path("var/safety_audit.sqlite")
    max_linear_speed_mps: float = 0.5
    max_angular_rate_rps: float = 1.0

    @field_validator("audit_db_path", mode="before")
    @classmethod
    def _resolve_path(cls, value: str | Path) -> Path:
        return Path(value)


class CoreSettings(BaseSettings):
    """Root configuration object."""

    model_config = SettingsConfigDict(
        env_prefix="HR_",
        env_nested_delimiter="__",
        yaml_file=None,
        extra="forbid",
    )

    environment: str = "prod"
    service_name: str = "cortex-core"
    http: HttpSettings = HttpSettings()
    nats: NatsSettings = NatsSettings()
    observability: ObservabilitySettings = ObservabilitySettings()
    safety: SafetySettings = SafetySettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Layer priority (highest first):
        #   1. explicit constructor kwargs
        #   2. environment variables
        #   3. YAML config file (if any)
        #   4. .env
        #   5. secrets directory
        yaml_source = YamlConfigSettingsSource(settings_cls)
        return (init_settings, env_settings, yaml_source, dotenv_settings, file_secret_settings)


def load_settings(*, config_path: Path | None = None) -> CoreSettings:
    """Load settings, optionally from a YAML file."""
    if config_path is not None:
        CoreSettings.model_config = SettingsConfigDict(
            **{**CoreSettings.model_config, "yaml_file": str(config_path)}
        )
    return CoreSettings()
