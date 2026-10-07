"""Pure device-control state machine; no network or GPIO side effects.

All timestamps are monotonic seconds supplied by the caller. Hardware and
transport adapters apply the returned actions; neither can clear physical
mute or infer an agent instruction from an audio stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Action(str, Enum):
    MUTE_CHANGED = "mute_changed"
    VOLUME_CHANGED = "volume_changed"
    LISTENING_STARTED = "listening_started"
    WAKE_REQUESTED = "wake_requested"
    LISTENING_ENDED = "listening_ended"
    PLAYBACK_CANCEL = "playback_cancel"


class Phase(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


class Indicator(str, Enum):
    UNPAIRED = "unpaired"
    MUTED = "muted"
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    VOLUME = "volume"


@dataclass(frozen=True)
class ControlConfig:
    hold_seconds: float = 0.7
    double_press_seconds: float = 0.35
    volume_tick_seconds: float = 0.3
    volume_step: float = 0.1
    min_volume: float = 0.2
    max_volume: float = 0.9
    listen_seconds: float = 20.0

    def __post_init__(self) -> None:
        if self.hold_seconds <= 0 or self.volume_tick_seconds <= 0 or self.double_press_seconds <= 0:
            raise ValueError("button timing must be positive")
        if self.volume_step <= 0 or not 0 <= self.min_volume < self.max_volume <= 1:
            raise ValueError("invalid volume bounds")
        if self.listen_seconds <= 0:
            raise ValueError("listen timeout must be positive")


@dataclass
class Controls:
    """Deterministic one-button state and local wake/stop policy.

    Unpaired or muted devices cannot enter the listening state. The initial
    state is muted, so a restart cannot silently re-open a microphone.
    """

    config: ControlConfig = field(default_factory=ControlConfig)
    paired: bool = False
    muted: bool = True
    volume: float = 0.5
    phase: Phase = Phase.IDLE
    listen_deadline: float | None = None
    _pressed_at: float | None = None
    _next_volume_tick: float | None = None
    _volume_direction: int = 1
    _tap_deadline: float | None = None
    _second_press: bool = False

    @property
    def can_capture(self) -> bool:
        return self.paired and not self.muted and self.phase == Phase.LISTENING

    @property
    def indicator(self) -> Indicator:
        if not self.paired:
            return Indicator.UNPAIRED
        if self.muted:
            return Indicator.MUTED
        if self._next_volume_tick is not None:
            return Indicator.VOLUME
        return Indicator(self.phase.value)

    def set_paired(self, paired: bool) -> tuple[Action, ...]:
        self.paired = paired
        if not paired:
            self._tap_deadline = None
            self._second_press = False
            self._pressed_at = None
            self._next_volume_tick = None
            actions = self.stop()
            if not self.muted:
                self.muted = True
                return (Action.MUTE_CHANGED, *actions)
            return actions
        return ()

    def press(self, now: float) -> None:
        if self._pressed_at is not None:
            return
        if self._tap_deadline is not None and now <= self._tap_deadline:
            self._tap_deadline = None
            self._second_press = True
        self._pressed_at = now

    def release(self, now: float) -> tuple[Action, ...]:
        if self._pressed_at is None:
            return ()
        held = max(0.0, now - self._pressed_at)
        self._pressed_at = None
        self._next_volume_tick = None
        if held >= self.config.hold_seconds:
            self._tap_deadline = None
            self._second_press = False
            self._volume_direction *= -1
            return ()
        if not self.paired:
            self._tap_deadline = None
            self._second_press = False
            return ()
        if self._second_press:
            self._second_press = False
            actions: list[Action] = []
            if self.muted:
                self.muted = False
                actions.append(Action.MUTE_CHANGED)
            actions.extend(self.wake(now))
            actions.append(Action.WAKE_REQUESTED)
            return tuple(actions)
        previous = self._toggle_mute() if self._tap_deadline is not None else ()
        self._tap_deadline = now + self.config.double_press_seconds
        return previous

    def _toggle_mute(self) -> tuple[Action, ...]:
        self.muted = not self.muted
        if self.muted:
            if self.phase == Phase.LISTENING:
                self.phase = Phase.IDLE
                self.listen_deadline = None
                return (Action.MUTE_CHANGED, Action.LISTENING_ENDED)
            return (Action.MUTE_CHANGED,)
        return (Action.MUTE_CHANGED,)

    def tick(self, now: float) -> tuple[Action, ...]:
        actions: list[Action] = []
        if self._pressed_at is None and self._tap_deadline is not None and now >= self._tap_deadline:
            self._tap_deadline = None
            actions.extend(self._toggle_mute())
        if self._pressed_at is not None and now - self._pressed_at >= self.config.hold_seconds:
            if self._next_volume_tick is None:
                self._next_volume_tick = self._pressed_at + self.config.hold_seconds
            if now >= self._next_volume_tick:
                elapsed_ticks = int(
                    (now - self._next_volume_tick) / self.config.volume_tick_seconds
                ) + 1
                old = self.volume
                self.volume = round(
                    min(
                        self.config.max_volume,
                        max(
                            self.config.min_volume,
                            self.volume
                            + self._volume_direction * self.config.volume_step * elapsed_ticks,
                        ),
                    ),
                    3,
                )
                if self.volume != old:
                    actions.append(Action.VOLUME_CHANGED)
                self._next_volume_tick += elapsed_ticks * self.config.volume_tick_seconds
        if self.listen_deadline is not None and now >= self.listen_deadline:
            self.listen_deadline = None
            if self.phase == Phase.LISTENING:
                self.phase = Phase.IDLE
                actions.append(Action.LISTENING_ENDED)
        return tuple(actions)

    def wake(self, now: float) -> tuple[Action, ...]:
        if not self.paired or self.muted:
            return ()
        was_listening = self.phase == Phase.LISTENING
        self.phase = Phase.LISTENING
        self.listen_deadline = now + self.config.listen_seconds
        return () if was_listening else (Action.LISTENING_STARTED,)

    def extend_listening(self, now: float) -> None:
        if self.can_capture:
            self.listen_deadline = now + self.config.listen_seconds

    def set_phase(self, phase: Phase) -> None:
        if phase != Phase.IDLE and not self.paired:
            raise ValueError("active phase requires paired device")
        if phase == Phase.LISTENING and self.muted:
            raise ValueError("listening requires unmuted device")
        self.phase = phase
        if phase != Phase.LISTENING:
            self.listen_deadline = None

    def stop(self) -> tuple[Action, ...]:
        was_listening = self.phase == Phase.LISTENING
        was_speaking = self.phase == Phase.SPEAKING
        self.phase = Phase.IDLE
        self.listen_deadline = None
        actions: list[Action] = []
        if was_listening:
            actions.append(Action.LISTENING_ENDED)
        if was_speaking:
            actions.append(Action.PLAYBACK_CANCEL)
        return tuple(actions)
