"""Ports — structural interfaces that adapters implement."""

from humanoid_robot.ports.ai import (
    AsrPort,
    AsrStreamChunk,
    EmbeddingPort,
    LlmPort,
    LlmRequest,
    LlmResponse,
    TtsPort,
    TtsRequest,
)
from humanoid_robot.ports.event_bus import EventBusPort, EventHandler, Subscription
from humanoid_robot.ports.knowledge import (
    ChunkerPort,
    DocumentParserPort,
    RetrievalQuery,
    VectorStorePort,
)
from humanoid_robot.ports.robot import (
    ArmPort,
    AudioInPort,
    AudioOutPort,
    BatteryPort,
    HandPort,
    LocomotionPort,
    RobotAdapterPort,
)

__all__ = [
    "ArmPort",
    "AsrPort",
    "AsrStreamChunk",
    "AudioInPort",
    "AudioOutPort",
    "BatteryPort",
    "ChunkerPort",
    "DocumentParserPort",
    "EmbeddingPort",
    "EventBusPort",
    "EventHandler",
    "HandPort",
    "LlmPort",
    "LlmRequest",
    "LlmResponse",
    "LocomotionPort",
    "RetrievalQuery",
    "RobotAdapterPort",
    "Subscription",
    "TtsPort",
    "TtsRequest",
    "VectorStorePort",
]
