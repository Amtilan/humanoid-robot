"""Lazy access to the vendor Python SDK.

`unitree_sdk2_python` (aka `unitree_sdk2py`) is not on PyPI. To keep the
package importable everywhere (CI runners, developer laptops, docs builds),
we defer the import to first use and raise a clear error if it is missing.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType


class UnitreeSdkNotAvailableError(RuntimeError):
    """Raised when the runtime tries to talk to hardware without the SDK."""

    def __init__(self) -> None:
        super().__init__(
            "unitree_sdk2py is not importable in this environment. "
            "Install it on the robot from the vendor repository: "
            "https://github.com/unitreerobotics/unitree_sdk2_python"
        )


@dataclass(slots=True)
class SdkHandles:
    """The subset of SDK modules the adapter needs.

    Held once per process; obtained via `require_sdk()`.
    """

    channel: ModuleType
    audio_client: ModuleType
    arm_client: ModuleType
    loco_client: ModuleType | None = None


_CACHED: SdkHandles | None = None


def require_sdk() -> SdkHandles:
    """Import the SDK on first use; raise a helpful error otherwise."""
    global _CACHED
    if _CACHED is not None:
        return _CACHED

    try:
        channel = importlib.import_module("unitree_sdk2py.core.channel")
        audio_client = importlib.import_module("unitree_sdk2py.g1.audio.g1_audio_client")
        arm_client = importlib.import_module("unitree_sdk2py.g1.arm.g1_arm_action_client")
    except ImportError as exc:
        raise UnitreeSdkNotAvailableError from exc

    # LocoClient is optional — it exists on newer SDKs; degrade gracefully.
    try:
        loco_client: ModuleType | None = importlib.import_module(
            "unitree_sdk2py.g1.loco.g1_loco_client"
        )
    except ImportError:
        loco_client = None

    _CACHED = SdkHandles(
        channel=channel,
        audio_client=audio_client,
        arm_client=arm_client,
        loco_client=loco_client,
    )
    return _CACHED


def reset_cache_for_tests() -> None:
    """Test helper — clear the cached SDK handle."""
    global _CACHED
    _CACHED = None
