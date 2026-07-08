"""openWakeWord adapter."""

from humanoid_robot.adapters.wakeword_openwakeword.adapter import (
    OpenWakeWord,
    OpenWakeWordConfig,
    OpenWakeWordRuntimeNotAvailableError,
)

__all__ = [
    "OpenWakeWord",
    "OpenWakeWordConfig",
    "OpenWakeWordRuntimeNotAvailableError",
]
