"""Runtime discovery of robot adapters and plugins."""

from humanoid_robot.plugins_sdk.plugin import (
    PluginContext,
    PluginManifest,
    PluginPort,
)
from humanoid_robot.plugins_sdk.plugin_registry import (
    PLUGIN_ENTRY_POINT_GROUP,
    PluginEntry,
    PluginRegistry,
    UnknownPluginError,
)
from humanoid_robot.plugins_sdk.registry import (
    ADAPTER_ENTRY_POINT_GROUP,
    AdapterEntry,
    AdapterRegistry,
    UnknownAdapterError,
)

__all__ = [
    "ADAPTER_ENTRY_POINT_GROUP",
    "PLUGIN_ENTRY_POINT_GROUP",
    "AdapterEntry",
    "AdapterRegistry",
    "PluginContext",
    "PluginEntry",
    "PluginManifest",
    "PluginPort",
    "PluginRegistry",
    "UnknownAdapterError",
    "UnknownPluginError",
]
