"""Composition root for the voice runner — resolves adapters by entry-point name."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, cast

from humanoid_robot.adapters.nats import NatsEventBus, NatsEventBusConfig
from humanoid_robot.domain.voice import Language
from humanoid_robot.ports import (
    AsrPort,
    AudioInPort,
    AudioOutPort,
    EventBusPort,
    TtsPort,
    VadPort,
    WakeWordPort,
)
from humanoid_robot.voice.settings import (
    AdapterSelection,
    NatsSettings,
    VoiceRunnerSettings,
    VoiceStackSettings,
)

_AUDIO_IN_GROUP = "humanoid_robot.audio_in_adapters"
_AUDIO_OUT_GROUP = "humanoid_robot.audio_out_adapters"
_VAD_GROUP = "humanoid_robot.vad_adapters"
_ASR_GROUP = "humanoid_robot.asr_adapters"
_TTS_GROUP = "humanoid_robot.tts_adapters"
_WAKEWORD_GROUP = "humanoid_robot.wakeword_adapters"


class UnknownAdapterError(LookupError):
    """The runtime asked for an adapter that no installed distribution provides."""


@dataclass(slots=True)
class VoiceComposition:
    """Composed voice runtime — created once by the CLI."""

    settings: VoiceRunnerSettings
    audio_in: AudioInPort
    audio_out: AudioOutPort
    vad: VadPort
    asr: AsrPort
    tts: TtsPort
    bus: EventBusPort
    wake_word: WakeWordPort | None = None

    @classmethod
    async def build(cls, settings: VoiceRunnerSettings) -> VoiceComposition:
        stack = settings.stack
        audio_in = _resolve(_AUDIO_IN_GROUP, stack.audio_in)
        audio_out = _resolve(_AUDIO_OUT_GROUP, stack.audio_out)
        vad = _resolve(_VAD_GROUP, stack.vad)
        asr = _resolve(_ASR_GROUP, stack.asr)
        tts = _resolve(_TTS_GROUP, stack.tts)
        wake_word = (
            _resolve(_WAKEWORD_GROUP, stack.wake_word) if stack.wake_word is not None else None
        )
        bus = await _build_nats(settings.nats)
        return cls(
            settings=settings,
            audio_in=cast(AudioInPort, audio_in),
            audio_out=cast(AudioOutPort, audio_out),
            vad=cast(VadPort, vad),
            asr=cast(AsrPort, asr),
            tts=cast(TtsPort, tts),
            wake_word=cast(WakeWordPort, wake_word) if wake_word is not None else None,
            bus=bus,
        )

    def session_language(self) -> Language:
        code = self.settings.session.language_hint
        try:
            return Language(code)
        except ValueError:
            return Language.UNKNOWN


def _resolve(group: str, selection: AdapterSelection) -> Any:
    for ep in entry_points(group=group):
        if ep.name == selection.name:
            factory: Callable[..., Any] = ep.load()
            return factory(**selection.config)
    available = sorted(ep.name for ep in entry_points(group=group))
    msg = (
        f"no adapter named {selection.name!r} in entry-point group {group!r}; "
        f"available: {available or '<none>'}"
    )
    raise UnknownAdapterError(msg)


async def _build_nats(cfg: NatsSettings) -> EventBusPort:
    bus = NatsEventBus(
        config=NatsEventBusConfig(
            servers=cfg.servers,
            name=cfg.client_name,
            connect_timeout_s=cfg.connect_timeout_s,
            reconnect_time_wait_s=cfg.reconnect_time_wait_s,
            max_reconnect_attempts=cfg.max_reconnect_attempts,
        )
    )
    await bus.connect()
    return bus


_ = VoiceStackSettings  # keep the import used for a future TOML-based override
