"""Runtime configuration.

Layered defaults: package defaults → YAML config file → environment variables.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
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


class AuthSettings(BaseModel):
    """Bearer-token gate on the HTTP + WebSocket surface.

    Auth is **opt-in**: unset ``token`` (or set it empty) leaves the API
    open exactly as before — same behaviour as every previous release,
    same convenience for dev laptops.  Setting ``HR_AUTH__TOKEN=...``
    switches every non-health `/api/v1/*` route to requiring
    ``Authorization: Bearer <token>``, and the WS event stream to
    accepting either that header or a ``?token=`` query arg.

    ``rate_limit_max_attempts`` and ``rate_limit_window_s`` cap the
    number of failed-auth requests a single client (identified by
    remote host or first X-Forwarded-For hop) can make in the window;
    once exceeded the client gets 429 with ``Retry-After`` until the
    oldest failure ages out.  A successful auth clears that client's
    counter, so operators who typo their token a couple of times
    aren't locked out for the full window.
    """

    token: str = ""
    rate_limit_max_attempts: int = 10
    rate_limit_window_s: float = 60.0


class ActorBudget(BaseModel):
    """Sliding-window rate budget for a single submitter class."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_s: float = Field(gt=0.0)
    max_events: int = Field(ge=0)


class SafetySettings(BaseModel):
    """Safety gate configuration.

    `allowed_capabilities` is fail-closed: capabilities not listed here
    are denied.  Default set intentionally excludes free-form locomotion
    to prevent accidental motion on boot.
    """

    allowed_capabilities: tuple[str, ...] = (
        "arms.gesture",
        "arms.release",
        "hands.close",
        "hands.open",
        "hands.set_positions",
        "head.pose",
        "head.reset",
        "locomotion.move",
        "locomotion.posture",
        "locomotion.stop",
        "voice.speak",
    )
    rate_limit_window_s: float = 5.0
    rate_limit_max_events: int = 20
    actor_budgets: dict[str, ActorBudget] = Field(
        default_factory=lambda: {
            "operator": ActorBudget(window_s=60.0, max_events=60),
            "llm": ActorBudget(window_s=60.0, max_events=10),
            "plugin": ActorBudget(window_s=60.0, max_events=20),
            "test": ActorBudget(window_s=60.0, max_events=100),
        }
    )
    actor_default_budget: ActorBudget = ActorBudget(window_s=60.0, max_events=5)
    watchdog_timeout_s: float = 5.0
    watchdog_check_interval_s: float = 1.0
    command_timeout_s: float = 3.0
    command_check_interval_s: float = 0.5
    audit_db_path: Path = Path("var/safety_audit.sqlite")
    audit_max_rows: int | None = 100_000
    audit_max_age_days: float | None = 30.0
    audit_rotation_interval_s: float = 3_600.0
    tilt_max_pitch_rad: float = 0.6
    tilt_max_roll_rad: float = 0.6
    max_temperature_c: float = 85.0
    max_linear_speed_mps: float = 0.5
    max_angular_rate_rps: float = 1.0

    @field_validator("audit_db_path", mode="before")
    @classmethod
    def _resolve_path(cls, value: str | Path) -> Path:
        return Path(value)


class WallSettings(BaseModel):
    """Video-wall integration (presenter deployments).

    ``agent_url`` points at the ``cortex-wall-agent`` next to the wall
    application — the compose simulator by default, the wall PC's address in
    production (``HR_WALL__AGENT_URL=http://<wall-pc>:8093``).

    Off by default: only presenter-role robots enable it explicitly
    (``HR_WALL__ENABLED=true`` in /etc/humanoid-robot/cortex-core.env), so a
    guard-desk deployment carries no video-wall surface at all.
    """

    enabled: bool = False
    agent_url: str = "http://wall-agent:8093"
    token: str = ""
    timeout_s: float = 5.0


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
    # Deployment role of THIS robot: drives which product surface the
    # dashboard shows. One platform, per-robot profiles — a presenter
    # customer never sees the guard desk and vice versa.
    #   "guard"     — пункт охраны (visit intake, журнал посетителей)
    #   "presenter" — робот-презентатор (видеостена)
    #   "generic"   — full dev surface, no customer-specific tabs
    role: str = "generic"
    http: HttpSettings = HttpSettings()
    nats: NatsSettings = NatsSettings()
    observability: ObservabilitySettings = ObservabilitySettings()
    auth: AuthSettings = AuthSettings()
    safety: SafetySettings = SafetySettings()
    wall: WallSettings = WallSettings()

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
