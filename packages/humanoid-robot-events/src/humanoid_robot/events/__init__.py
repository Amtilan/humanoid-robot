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
    SafetyCommandTimeout,
    SafetyEStopEngaged,
    SafetyEStopReleased,
    SafetyWatchdogHeartbeat,
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
from humanoid_robot.events.guard import (
    VisitCardCompleted,
    VisitIntakeStart,
)
from humanoid_robot.events.presence import VisitorDetected
from humanoid_robot.events.wall import (
    WallCommandRequested,
    WallCommandResulted,
)
from humanoid_robot.events.voice import (
    AsrFinal,
    AudioMonitorControl,
    AudioMonitorFrame,
    AsrPartial,
    LlmAnswer,
    LlmAnswerToken,
    LlmRejected,
    SpeechDetected,
    TtsSynthesisFinished,
    TtsSynthesisStarted,
    LlmConfigChanged,
    VoiceInterrupt,
    WakeWordTriggered,
)

__all__ = [
    "AsrFinal",
    "AsrPartial",
    "AudioMonitorControl",
    "AudioMonitorFrame",
    "BaseEvent",
    "EventMetadata",
    "LlmAnswer",
    "LlmAnswerToken",
    "LlmConfigChanged",
    "LlmRejected",
    "OtaApplied",
    "OtaAvailable",
    "RobotAdapterReady",
    "RobotCommandRequested",
    "RobotCommandResulted",
    "RobotTelemetry",
    "SafetyCommandDenied",
    "SafetyCommandForwarded",
    "SafetyCommandTimeout",
    "SafetyEStopEngaged",
    "SafetyEStopReleased",
    "SafetyWatchdogHeartbeat",
    "SecurityAudit",
    "SpeechDetected",
    "SystemDiagnosticsTick",
    "SystemHealth",
    "SystemReady",
    "SystemShuttingDown",
    "TtsSynthesisFinished",
    "TtsSynthesisStarted",
    "VisitCardCompleted",
    "VisitIntakeStart",
    "VisitorDetected",
    "VoiceInterrupt",
    "WakeWordTriggered",
    "WallCommandRequested",
    "WallCommandResulted",
]
