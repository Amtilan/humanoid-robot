"""Runtime discovery of robot adapters and plugins."""

from humanoid_robot.plugins_sdk.registry import (
    ADAPTER_ENTRY_POINT_GROUP,
    AdapterEntry,
    AdapterRegistry,
    UnknownAdapterError,
)

__all__ = [
    "ADAPTER_ENTRY_POINT_GROUP",
    "AdapterEntry",
    "AdapterRegistry",
    "UnknownAdapterError",
]
