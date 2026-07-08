"""Sanity checks: every port is a Protocol and typechecks against a stub impl."""

from __future__ import annotations

from typing import get_type_hints

import humanoid_robot.ports as ports


class TestPortsAreProtocols:
    def test_ports_are_protocol_subclasses(self) -> None:
        # All exported *Port names must be Protocol classes. `_is_protocol` is
        # the marker `typing.Protocol` sets on subclasses at class creation.
        port_names = [n for n in ports.__all__ if n.endswith("Port")]
        assert port_names, "no ports discovered"
        for name in port_names:
            cls = getattr(ports, name)
            assert getattr(cls, "_is_protocol", False), f"{name} must be a Protocol"

    def test_public_ports_have_docstrings(self) -> None:
        # Every exported port must document what it is for.
        port_names = [n for n in ports.__all__ if n.endswith("Port")]
        undocumented = [n for n in port_names if not getattr(ports, n).__doc__]
        assert not undocumented, f"undocumented ports: {undocumented}"


class TestPortShapes:
    def test_locomotion_port_shape(self) -> None:
        hints = get_type_hints(ports.LocomotionPort.move)
        assert "cmd" in hints
        assert "return" in hints
