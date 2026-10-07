"""Pi-local microphone and indicator state; no agent or network decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Action(str, Enum):
    MUTE_CHANGED = "mute_changed"
    LISTENING_STARTED = "listening_started"
    WAKE_REQUESTED = "wake_requested"
    LISTENING_ENDED = "listening_ended"


class Phase(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"


class Mode(str, Enum):
    MUTED = "muted"
    WAKE_WORD = "wake_word"
    CONTINUOUS = "continuous"


class Indicator(str, Enum):
    UNPAIRED = "unpaired"
    MUTED = "muted"
    IDLE = "idle"
    LISTENING = "listening"
    SENSING = "sensing"
    HEARING = "hearing"
    PROCESSING = "processing"
    SPEAKING = "speaking"


@dataclass(frozen=True)
class ControlConfig:
    listen_seconds: float = 6.0

    def __post_init__(self) -> None:
        if self.listen_seconds <= 0:
            raise ValueError("listen timeout must be positive")


@dataclass
class Controls:
    """Local mode, conversation and LED state; the button owns privacy mute."""

    config: ControlConfig = field(default_factory=ControlConfig)
    paired: bool = False
    mode: Mode = Mode.MUTED
    volume: float = 0.5
    brightness: float = 0.2
    phase: Phase = Phase.IDLE
    listen_deadline: float | None = None
    activity: Indicator | None = None
    _pressed_at: float | None = None
    _physical_mute_latched: bool = True

    @property
    def muted(self) -> bool:
        return self.mode == Mode.MUTED

    @property
    def persistent(self) -> bool:
        return self.mode == Mode.CONTINUOUS

    @property
    def can_detect_wake(self) -> bool:
        return self.paired and self.mode == Mode.WAKE_WORD and self.phase == Phase.IDLE

    @property
    def can_capture(self) -> bool:
        return self.paired and not self.muted and self.phase == Phase.LISTENING

    @property
    def indicator(self) -> Indicator:
        if not self.paired:
            return Indicator.UNPAIRED
        if self.muted:
            return Indicator.MUTED
        if self.phase == Phase.LISTENING:
            return self.activity or Indicator.LISTENING
        return Indicator.IDLE

    def set_paired(self, paired: bool) -> tuple[Action, ...]:
        self.paired = paired
        if paired:
            return ()
        self._pressed_at = None
        actions = self.stop()
        if not self.muted:
            self.mode = Mode.MUTED
            self._physical_mute_latched = True
            return (Action.MUTE_CHANGED, *actions)
        self._physical_mute_latched = True
        return actions

    def press(self, now: float) -> None:
        if self._pressed_at is None:
            self._pressed_at = now

    def release(self, now: float) -> tuple[Action, ...]:
        if self._pressed_at is None:
            return ()
        self._pressed_at = None
        if not self.paired:
            return ()
        if self.mode == Mode.MUTED:
            return self.set_mode(Mode.WAKE_WORD, now, from_button=True)
        if self.mode == Mode.WAKE_WORD:
            return self.set_mode(Mode.CONTINUOUS, now, from_button=True)
        return self.set_mode(Mode.MUTED, now, from_button=True)

    def set_mode(self, mode: Mode, now: float, *, from_button: bool = False) -> tuple[Action, ...]:
        if not self.paired:
            raise PermissionError("device is not paired")
        # A remotely requested mode cannot undo a physical button mute.
        if self.muted and self._physical_mute_latched and not from_button and mode != Mode.MUTED:
            raise PermissionError("physical button mute must be cleared locally")
        if mode == self.mode:
            return ()
        was_muted = self.muted
        if from_button:
            self._physical_mute_latched = mode == Mode.MUTED
        elif mode == Mode.MUTED:
            self._physical_mute_latched = False
        self.mode = mode
        actions = list(self.stop()) if mode != Mode.CONTINUOUS else []
        if mode == Mode.CONTINUOUS:
            actions.extend(self.wake(now))
            if Action.LISTENING_STARTED in actions:
                actions.append(Action.WAKE_REQUESTED)
        if was_muted != self.muted:
            actions.insert(0, Action.MUTE_CHANGED)
        return tuple(actions)

    def tick(self, now: float) -> tuple[Action, ...]:
        if (self.listen_deadline is not None and now >= self.listen_deadline and
                self.activity not in {Indicator.SENSING, Indicator.HEARING,
                                      Indicator.PROCESSING, Indicator.SPEAKING}):
            return self.stop()
        return ()

    def wake(self, now: float) -> tuple[Action, ...]:
        if not self.paired or self.muted:
            return ()
        was_listening = self.phase == Phase.LISTENING
        self.phase = Phase.LISTENING
        self.listen_deadline = None if self.persistent else now + self.config.listen_seconds
        self.activity = None
        return () if was_listening else (Action.LISTENING_STARTED,)

    def extend_listening(self, now: float) -> None:
        if self.can_capture and not self.persistent:
            self.listen_deadline = now + self.config.listen_seconds

    def set_activity(self, activity: Indicator, now: float) -> None:
        if activity not in {Indicator.LISTENING, Indicator.SENSING, Indicator.HEARING,
                            Indicator.PROCESSING, Indicator.SPEAKING}:
            raise ValueError("invalid conversation activity")
        if self.can_capture:
            self.activity = None if activity == Indicator.LISTENING else activity
            self.extend_listening(now)

    def stop(self) -> tuple[Action, ...]:
        was_listening = self.phase == Phase.LISTENING
        self.phase = Phase.IDLE
        self.listen_deadline = None
        self.activity = None
        return (Action.LISTENING_ENDED,) if was_listening else ()
