"""HTTP round-trip against the wall-agent server (sim driver)."""

from __future__ import annotations

import json
import threading
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from humanoid_robot.wall_agent.drivers import SimWallDriver
from humanoid_robot.wall_agent.server import serve

_TOKEN = "test-secret"  # noqa: S105 — test fixture value


@pytest.fixture
def agent_url() -> Iterator[str]:
    driver = SimWallDriver()
    server = serve(driver, host="127.0.0.1", port=0, token=_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _request(
    url: str, *, method: str = "GET", body: dict[str, Any] | None = None, token: str = _TOKEN
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(  # noqa: S310 — fixed http://127.0.0.1 test URL
        url, data=data, method=method, headers={"X-Wall-Token": token}
    )
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_healthz(agent_url: str) -> None:
    status, payload = _request(f"{agent_url}/healthz")
    assert status == 200
    assert payload == {"status": "ok", "driver": "sim"}


def test_command_roundtrip_updates_state(agent_url: str) -> None:
    status, result = _request(
        f"{agent_url}/wall/command",
        method="POST",
        body={"kind": "open_section", "section": "Aero1"},
    )
    assert status == 200
    assert result["outcome"] == "accepted"

    _, state = _request(f"{agent_url}/wall/state")
    assert state["screen"] == "Aero1"


def test_invalid_command_is_400(agent_url: str) -> None:
    status, payload = _request(
        f"{agent_url}/wall/command",
        method="POST",
        body={"kind": "open_section"},  # missing section
    )
    assert status == 400
    assert payload["error"] == "invalid command"


def test_bad_token_is_401(agent_url: str) -> None:
    status, _ = _request(f"{agent_url}/healthz", token="wrong")
    assert status == 401
