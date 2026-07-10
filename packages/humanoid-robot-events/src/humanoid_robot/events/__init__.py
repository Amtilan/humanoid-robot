"""Event catalog and versioned schemas for the humanoid-robot platform."""

from humanoid_robot.events.base import BaseEvent, EventMetadata
from humanoid_robot.events.robot import (
    RobotAdapterReady,
    RobotCommandRequested,
    RobotCommandResulted,
    RobotTelemetry,
)
from humanoid_robot.events.safety import (
    SafetyCommandDenied,
    SafetyCommandForwarded,
    SafetyEStopEngaged,
    SafetyEStopReleased,
)
from humanoid_robot.events.system import (
    OtaAvailable,
    OtaApplied,
    SecurityAudit,
    SystemDiagnosticsTick,
    SystemHealth,
    SystemReady,
    SystemShuttingDown,
)
from humanoid_robot.events.voice import (
    AsrFinal,
    AsrPartial,
    LlmAnswer,
    LlmAnswerToken,
    LlmRejected,
    SpeechDetected,
    TtsSynthesisFinished,
    TtsSynthesisStarted,
    WakeWordTriggered,
)

__all__ = [
    "AsrFinal",
    "AsrPartial",
    "BaseEvent",
    "EventMetadata",
    "LlmAnswer",
    "LlmAnswerToken",
    "LlmRejected",
    "OtaApplied",
    "OtaAvailable",
    "RobotAdapterReady",
    "RobotCommandRequested",
    "RobotCommandResulted",
    "RobotTelemetry",
    "SafetyCommandDenied",
    "SafetyCommandForwarded",
    "SafetyEStopEngaged",
    "SafetyEStopReleased",
    "SecurityAudit",
    "SpeechDetected",
    "SystemDiagnosticsTick",
    "SystemHealth",
    "SystemReady",
    "SystemShuttingDown",
    "TtsSynthesisFinished",
    "TtsSynthesisStarted",
    "WakeWordTriggered",
]
