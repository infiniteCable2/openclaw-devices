"""Bounded Pi-side speech preleveling after AEC/NS, before the Meeting transport.

The server remains the final speech-level owner. This controller never raises
gain on energy alone: a confirmed APM voice frame and a plausible noise gap
are required. Silence and likely loudspeaker echo cannot teach it a louder
target. It also exposes the unmodified input level for later server telemetry.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import sys
from threading import Lock

from .apm import AcousticStats, BYTES_PER_FRAME


@dataclass(frozen=True)
class PrelevelResult:
    pcm: bytes
    input_rms_dbfs: float
    input_peak_dbfs: float
    noise_dbfs: float | None
    estimated_snr_db: float | None
    gain_db: float
    confirmed_voice: bool


class SpeechPreLeveler:
    """Small, evidence-gated gain range with a fast protective downward path."""

    def __init__(
        self, *, target_rms_dbfs: float = -29.0, max_gain_db: float = 9.0,
        min_gain_db: float = -9.0, max_noise_dbfs: float = -39.0,
    ) -> None:
        if not -40 <= target_rms_dbfs <= -20:
            raise ValueError("invalid speech target")
        if not 0 <= max_gain_db <= 12 or not -12 <= min_gain_db <= 0:
            raise ValueError("invalid prelevel gain range")
        if not -60 <= max_noise_dbfs <= -25:
            raise ValueError("invalid noise ceiling")
        self.target_rms_dbfs = target_rms_dbfs
        self.max_gain_db = max_gain_db
        self.min_gain_db = min_gain_db
        self.max_noise_dbfs = max_noise_dbfs
        self.gain_db = 0.0
        self.noise_dbfs: float | None = None

    @staticmethod
    def _samples(pcm: bytes) -> array:
        if len(pcm) != BYTES_PER_FRAME:
            raise ValueError("prelevel requires 10 ms of mono 16-kHz PCM")
        samples = array("h")
        samples.frombytes(pcm)
        if sys.byteorder != "little":
            samples.byteswap()
        return samples

    def process(self, pcm: bytes, stats: AcousticStats) -> PrelevelResult:
        samples = self._samples(pcm)
        square_sum = sum(sample * sample for sample in samples)
        rms = math.sqrt(square_sum / len(samples))
        peak = max(abs(sample) for sample in samples)
        rms_dbfs = 20 * math.log10(max(rms, 1) / 32768)
        peak_dbfs = 20 * math.log10(max(peak, 1) / 32768)
        echo_likelihood = stats.residual_echo_likelihood
        likely_echo = echo_likelihood is not None and echo_likelihood >= 0.5
        # Missing AEC evidence is not proof that a voice frame is near-end.
        confirmed_voice = (
            stats.voice_detected is True
            and echo_likelihood is not None
            and not likely_echo
        )

        if not confirmed_voice and not likely_echo and peak_dbfs < -3:
            # Do not infer speech from amplitude. Learn the quiet floor quickly
            # downward and very slowly upward; a transient cannot raise it.
            if self.noise_dbfs is None:
                self.noise_dbfs = rms_dbfs
            else:
                rate = 0.2 if rms_dbfs < self.noise_dbfs else 0.002
                self.noise_dbfs += rate * (rms_dbfs - self.noise_dbfs)

        snr = rms_dbfs - self.noise_dbfs if self.noise_dbfs is not None else None
        desired = self.gain_db
        if confirmed_voice and snr is not None and snr >= 4:
            desired = max(self.min_gain_db, min(self.max_gain_db, self.target_rms_dbfs - rms_dbfs))
            # Positive gain must not lift the learned noise above its ceiling.
            desired = min(desired, max(0.0, self.max_noise_dbfs - self.noise_dbfs))
        elif not likely_echo and self.noise_dbfs is not None and desired > 0:
            # Retain a learned far-field level through silence unless the
            # background itself becomes too loud to amplify safely.
            desired = min(desired, max(0.0, self.max_noise_dbfs - self.noise_dbfs))
        if peak_dbfs + desired > -3:
            desired = max(self.min_gain_db, -3 - peak_dbfs)
        step = 0.12 if desired > self.gain_db else 0.24
        self.gain_db += max(-step, min(step, desired - self.gain_db))
        # A sudden close utterance must not clip for several hundred ms while
        # the normal smoothing catches up. This is a one-way safety override.
        if peak_dbfs + self.gain_db > -1:
            self.gain_db = max(self.min_gain_db, -1 - peak_dbfs)

        factor = 10 ** (self.gain_db / 20)
        for index, sample in enumerate(samples):
            samples[index] = max(-32768, min(32767, round(sample * factor)))
        if sys.byteorder != "little":
            samples.byteswap()
        return PrelevelResult(
            pcm=samples.tobytes(), input_rms_dbfs=rms_dbfs,
            input_peak_dbfs=peak_dbfs, noise_dbfs=self.noise_dbfs,
            estimated_snr_db=snr, gain_db=self.gain_db,
            confirmed_voice=confirmed_voice,
        )


class NearEndDucker:
    """Duck Pi playout on sustained, echo-checked local speech evidence.

    This never stops the server turn or discards input. The shared Meeting
    engine remains responsible for confirmed interruption and output clear.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._voice_frames = 0
        self._release_frames = 0
        self._active = False

    def observe(self, stats: AcousticStats) -> None:
        near_voice = (
            stats.voice_detected is True
            and stats.residual_echo_likelihood is not None
            and stats.residual_echo_likelihood < 0.4
        )
        with self._lock:
            if near_voice:
                self._voice_frames = min(8, self._voice_frames + 1)
                self._release_frames = 0
                if self._voice_frames >= 8:
                    self._active = True
            else:
                self._voice_frames = 0
                if self._active:
                    self._release_frames += 1
                    if self._release_frames >= 20:
                        self._active = False
                        self._release_frames = 0

    def reset(self) -> None:
        with self._lock:
            self._voice_frames = 0
            self._release_frames = 0
            self._active = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def volume_factor(self) -> float:
        return 0.2 if self.active else 1.0
