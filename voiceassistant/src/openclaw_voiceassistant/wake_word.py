"""Pi-local, offline Nova keyword spotting; no raw standby audio leaves the Pi."""

from __future__ import annotations

from array import array
from collections import deque
from pathlib import Path
import math
import sys
from typing import Protocol

from .apm import BYTES_PER_FRAME


class NovaWakeDetector:
    """Small open-vocabulary sherpa-onnx keyword spotter on 16-kHz PCM."""

    def __init__(self, model_dir: Path) -> None:
        import numpy as np
        import sherpa_onnx

        if not model_dir.is_dir() or model_dir.is_symlink():
            raise ValueError("wake-word model directory is missing or a symlink")
        self._np = np
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx"),
            decoder=str(model_dir / "decoder-epoch-13-avg-2-chunk-8-left-64.onnx"),
            joiner=str(model_dir / "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx"),
            keywords_file=str(model_dir / "keywords.txt"),
            num_threads=1,
            provider="cpu",
        )
        self._stream = self._spotter.create_stream()
        self._buffer = bytearray()

    def feed(self, pcm: bytes) -> bool:
        if len(pcm) != BYTES_PER_FRAME:
            raise ValueError("wake-word input must be one 10-ms 16-kHz PCM frame")
        self._buffer.extend(pcm)
        if len(self._buffer) < BYTES_PER_FRAME * 10:
            return False
        samples = array("h")
        samples.frombytes(self._buffer)
        if sys.byteorder != "little":
            samples.byteswap()
        self._buffer.clear()
        audio = self._np.asarray(samples, dtype=self._np.float32) / 32768.0
        self._stream.accept_waveform(16_000, audio)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
        detected = self._spotter.get_result(self._stream)
        if detected:
            self.reset()
            return True
        return False

    def reset(self) -> None:
        self._buffer.clear()
        self._spotter.reset_stream(self._stream)


class KeywordDetector(Protocol):
    def feed(self, pcm: bytes) -> bool: ...
    def reset(self) -> None: ...


class GatedWakeDetector:
    """Keep a short PCM pre-roll; run KWS only around acoustic candidates.

    This gate is deliberately permissive: it saves CPU in quiet periods, but
    uncertain/noisy periods fall back to the keyword model. A level change is
    never treated as a wake word by itself.
    """

    def __init__(
        self,
        detector: KeywordDetector,
        *,
        pre_roll_frames: int = 100,
        release_frames: int = 80,
        trigger_ratio: float = 1.5,
        minimum_rms: float = 0.001,
        noisy_rms: float = 0.025,
    ) -> None:
        if pre_roll_frames < 2 or release_frames < 1:
            raise ValueError("wake gate requires positive pre-roll and release")
        if trigger_ratio <= 1 or not 0 < minimum_rms < noisy_rms < 1:
            raise ValueError("invalid wake gate thresholds")
        self._detector = detector
        self._pre_roll_frames = pre_roll_frames
        self._release_frames = release_frames
        self._trigger_ratio = trigger_ratio
        self._minimum_rms = minimum_rms
        self._noisy_rms = noisy_rms
        self._ring: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._active_levels: deque[float] = deque(maxlen=300)
        self._noise_floor = minimum_rms / 2
        self._active = False
        self._candidate_frames = 0
        self._quiet_frames = 0
        self.frames_seen = 0
        self.frames_decoded = 0
        self.activations = 0

    @property
    def active(self) -> bool:
        return self._active

    @staticmethod
    def _rms(pcm: bytes) -> float:
        if len(pcm) != BYTES_PER_FRAME:
            raise ValueError("wake-word input must be one 10-ms 16-kHz PCM frame")
        samples = array("h")
        samples.frombytes(pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768

    def feed(self, pcm: bytes) -> bool:
        rms = self._rms(pcm)
        self.frames_seen += 1
        self._ring.append(pcm)
        threshold = max(self._minimum_rms, self._noise_floor * self._trigger_ratio)
        candidate = rms >= threshold or rms >= self._noisy_rms

        if not self._active:
            if candidate:
                self._candidate_frames += 1
            else:
                self._candidate_frames = 0
                # Learn upward slowly and downward quickly, only outside a
                # candidate. Speech must not teach the gate to ignore speech.
                alpha = 0.005 if rms > self._noise_floor else 0.05
                self._noise_floor += alpha * (rms - self._noise_floor)
            if self._candidate_frames < 2:
                return False
            self._active = True
            self._quiet_frames = 0
            self._active_levels.clear()
            self.activations += 1
            pending = tuple(self._ring)
            self._ring.clear()
        else:
            pending = (pcm,)
            self._quiet_frames = 0 if candidate else self._quiet_frames + 1
        self._active_levels.append(rms)

        for frame in pending:
            self.frames_decoded += 1
            if self._detector.feed(frame):
                self.reset()
                return True
        if self._quiet_frames >= self._release_frames:
            self._detector.reset()
            self._active = False
            self._candidate_frames = 0
            self._quiet_frames = 0
            self._active_levels.clear()
        elif len(self._active_levels) == self._active_levels.maxlen:
            # A steady fan/hum can initially look like an onset. After three
            # seconds of nearly flat, *moderate* level, treat it as background.
            # Truly loud or varying audio remains on continuous KWS (fail open).
            low, high = min(self._active_levels), max(self._active_levels)
            if high < self._noisy_rms and high - low <= max(self._minimum_rms, low * 0.15):
                self._noise_floor = sum(self._active_levels) / len(self._active_levels)
                self._detector.reset()
                self._active = False
                self._candidate_frames = 0
                self._quiet_frames = 0
                self._active_levels.clear()
        return False

    def reset(self) -> None:
        # Mute/disconnect must discard all standby PCM, including the pre-roll.
        self._ring.clear()
        self._active = False
        self._candidate_frames = 0
        self._quiet_frames = 0
        self._active_levels.clear()
        self._noise_floor = self._minimum_rms / 2
        self._detector.reset()
