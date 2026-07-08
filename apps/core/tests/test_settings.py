"""CoreSettings loading tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from humanoid_robot.core.settings import load_settings


class TestCoreSettings:
    def test_defaults(self) -> None:
        s = load_settings()
        assert s.service_name == "cortex-core"
        assert s.environment == "prod"
        assert s.http.host == "0.0.0.0"  # noqa: S104
        assert s.http.port == 8080
        assert s.nats.servers[0].startswith("nats://")

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # HR_HTTP__PORT overrides http.port via nested delimiter.
        monkeypatch.setenv("HR_HTTP__PORT", "9090")
        s = load_settings()
        assert s.http.port == 9090

    def test_yaml_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "test.yaml"
        cfg.write_text("service_name: test-core\nenvironment: staging\nhttp:\n  port: 7070\n")
        s = load_settings(config_path=cfg)
        assert s.service_name == "test-core"
        assert s.environment == "staging"
        assert s.http.port == 7070
