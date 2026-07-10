"""Ports — structural interfaces that adapters implement."""

from humanoid_robot.ports.ai import (
    AsrPort,
    AsrStreamChunk,
    EmbeddingPort,
    LlmPort,
    LlmRequest,
    LlmResponse,
    RerankerPort,
    TtsPort,
    TtsRequest,
)
from humanoid_robot.ports.event_bus import EventBusPort, EventHandler, Subscription
from humanoid_robot.ports.knowledge import (
    ChunkerPort,
    DocumentParserPort,
    KnowledgeSourceSummary,
    RetrievalQuery,
    VectorStorePort,
)
from humanoid_robot.ports.robot import (
    ArmPort,
    AudioFrame,
    AudioInPort,
    AudioOutPort,
    BatteryPort,
    HandPort,
    HeadPort,
    LocomotionPort,
    RobotAdapterPort,
)
from humanoid_robot.ports.safety import (
    SafetyDecision,
    SafetyPolicyPort,
    SafetyRequest,
    Verdict,
)
from humanoid_robot.ports.voice import (
    VadDecision,
    VadPort,
    WakeWordEvent,
    WakeWordPort,
)

__all__ = [
    "ArmPort",
    "AsrPort",
    "AsrStreamChunk",
    "AudioFrame",
    "AudioInPort",
    "AudioOutPort",
    "BatteryPort",
    "ChunkerPort",
    "DocumentParserPort",
    "EmbeddingPort",
    "EventBusPort",
    "EventHandler",
    "HandPort",
    "HeadPort",
    "KnowledgeSourceSummary",
    "LlmPort",
    "LlmRequest",
    "LlmResponse",
    "LocomotionPort",
    "RerankerPort",
    "RetrievalQuery",
    "RobotAdapterPort",
    "SafetyDecision",
    "SafetyPolicyPort",
    "SafetyRequest",
    "Subscription",
    "TtsPort",
    "TtsRequest",
    "VadDecision",
    "VadPort",
    "VectorStorePort",
    "Verdict",
    "WakeWordEvent",
    "WakeWordPort",
]
