"""Named ReSpeaker ALSA I/O with bounded, 10-ms, mono PCM frames.

This module owns only the physical audio endpoints. It never chooses an agent,
stores audio, or bypasses physical mute. The caller provides the AEC processor
and decides whether a processed frame may leave the device.
"""

from __future__ import annotations

from array import array
import errno
import sys
from threading import Lock
import time
from typing import Protocol

from .apm import AcousticStats, BYTES_PER_FRAME, SAMPLES_PER_FRAME
from .prelevel import NearEndDucker, PrelevelResult, SpeechPreLeveler
from .resample import PcmResampler


SAMPLE_RATE = 16_000
PLAYBACK_SAMPLE_RATE = 24_000
PLAYBACK_SAMPLES_PER_FRAME = 240
PLAYBACK_BYTES_PER_FRAME = PLAYBACK_SAMPLES_PER_FRAME * 2


class EchoProcessor(Protocol):
    def render(self, pcm: bytes) -> None: ...
    def capture(self, pcm: bytes, delay_ms: int) -> bytes: ...
    def capture_stereo(self, pcm: bytes, delay_ms: int) -> bytes: ...
    def stats(self) -> AcousticStats: ...


def scale_pcm(pcm: bytes, volume: float) -> bytes:
    """Apply software speaker volume before forwarding the same PCM to AEC."""
    if len(pcm) != PLAYBACK_BYTES_PER_FRAME:
        raise ValueError("playback requires exactly one 10-ms 24-kHz mono PCM frame")
    if not 0 <= volume <= 1:
        raise ValueError("volume must be in [0, 1]")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        samples[index] = round(sample * volume)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def fade_pcm(pcm: bytes, start_sample: int, fade_samples: int) -> bytes:
    """Ramp the first playout samples from silence after opening I²S."""
    if len(pcm) != PLAYBACK_BYTES_PER_FRAME or fade_samples <= 0:
        raise ValueError("invalid playback fade")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        position = start_sample + index
        if position < fade_samples:
            samples[index] = round(sample * (position + 1) / fade_samples)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


class ReSpeakerAudio:
    """Two named ALSA streams; no dependency on a mutable card number."""

    def __init__(
        self, processor: EchoProcessor, *, playback_delay_ms: int = 40,
        capture_channels: int = 1, preleveler: SpeechPreLeveler | None = None,
        near_end_ducker: NearEndDucker | None = None,
    ) -> None:
        if not 0 <= playback_delay_ms <= 500:
            raise ValueError("playback_delay_ms must be in [0, 500]")
        if capture_channels not in (1, 2):
            raise ValueError("capture_channels must be 1 or 2")
        import alsaaudio

        cards = alsaaudio.cards()
        if "seeed2micvoicec" not in cards:
            raise RuntimeError("ReSpeaker ALSA card seeed2micvoicec is missing")
        self._capture_lock = Lock()
        self._playback_lock = Lock()
        self._playback_generation = 0
        self._alsaaudio = alsaaudio
        self._capture = alsaaudio.PCM(
            type=alsaaudio.PCM_CAPTURE,
            mode=alsaaudio.PCM_NORMAL,
            device="capture",
        )
        try:
            self._playback = self._open_playback()
            self._capture.setchannels(capture_channels)
            self._capture.setrate(SAMPLE_RATE)
            self._capture.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            self._capture.setperiodsize(SAMPLES_PER_FRAME)
        except BaseException:
            self._capture.close()
            if hasattr(self, "_playback"):
                self._playback.close()
            raise
        self._processor = processor
        self._playback_delay_ms = playback_delay_ms
        self._capture_channels = capture_channels
        self._capture_frame_bytes = BYTES_PER_FRAME * capture_channels
        self._preleveler = preleveler
        self._near_end_ducker = near_end_ducker
        self._last_prelevel: PrelevelResult | None = None
        self._last_acoustic_stats: AcousticStats | None = None
        self._capture_buffer = bytearray()
        self._reference_resampler = PcmResampler(PLAYBACK_SAMPLE_RATE, SAMPLE_RATE)
        self._reference_buffer = bytearray()
        self._playback_started = False
        self._fade_position = 0

    def _open_playback(self):
        stream = self._alsaaudio.PCM(
            type=self._alsaaudio.PCM_PLAYBACK,
            mode=self._alsaaudio.PCM_NORMAL,
            device="playback",
        )
        try:
            stream.setchannels(1)
            stream.setrate(PLAYBACK_SAMPLE_RATE)
            stream.setformat(self._alsaaudio.PCM_FORMAT_S16_LE)
            stream.setperiodsize(PLAYBACK_SAMPLES_PER_FRAME)
        except BaseException:
            stream.close()
            raise
        return stream

    def read(self) -> bytes:
        """Return exactly one processed 10-ms frame or fail on a broken stream."""
        # A cancelled wake or bridge task can leave its to_thread() read in
        # flight briefly. Never let the next mode read the same ALSA stream or
        # shared frame buffer concurrently.
        with self._capture_lock:
            empty_deadline = time.monotonic() + 0.25
            overruns = 0
            while len(self._capture_buffer) < self._capture_frame_bytes:
                frames, data = self._capture.read()
                if frames == -errno.EPIPE:
                    # ALSA reports a recoverable capture overrun when a mode
                    # change leaves the stream unread. Pyalsaaudio prepares it
                    # for the next read; discard any partial stale frame.
                    self._capture_buffer.clear()
                    overruns += 1
                    if overruns > 3:
                        raise RuntimeError("ALSA capture overrun persisted")
                    continue
                if frames == 0 and not data:
                    if time.monotonic() >= empty_deadline:
                        raise RuntimeError("ALSA capture returned no audio")
                    time.sleep(0.005)
                    continue
                if frames <= 0 or not data:
                    raise RuntimeError(f"ALSA capture read failed ({frames})")
                if len(data) != frames * 2 * self._capture_channels:
                    raise RuntimeError("ALSA capture returned an unexpected PCM size")
                self._capture_buffer.extend(data)
                if len(self._capture_buffer) > self._capture_frame_bytes * 20:
                    raise RuntimeError("ALSA capture exceeded the bounded frame buffer")
            raw = bytes(self._capture_buffer[:self._capture_frame_bytes])
            del self._capture_buffer[:self._capture_frame_bytes]
            if self._capture_channels == 2:
                processed = self._processor.capture_stereo(raw, self._playback_delay_ms)
            else:
                processed = self._processor.capture(raw, self._playback_delay_ms)
            if self._preleveler is not None or self._near_end_ducker is not None:
                self._last_acoustic_stats = self._processor.stats()
            if self._near_end_ducker is not None and self._last_acoustic_stats is not None:
                self._near_end_ducker.observe(self._last_acoustic_stats)
            if self._preleveler is not None and self._last_acoustic_stats is not None:
                self._last_prelevel = self._preleveler.process(processed, self._last_acoustic_stats)
                return self._last_prelevel.pcm
            return processed

    def acoustic_stats(self) -> AcousticStats:
        return self._last_acoustic_stats or self._processor.stats()

    def prelevel_stats(self) -> PrelevelResult | None:
        return self._last_prelevel

    def write(self, pcm: bytes, volume: float, generation: int = 0) -> None:
        duck = self._near_end_ducker.volume_factor if self._near_end_ducker is not None else 1.0
        scaled = scale_pcm(pcm, volume * duck)
        with self._playback_lock:
            if generation != self._playback_generation:
                return
            if not self._playback_started:
                # Keep the MAX98357A's first I²S samples at zero before any
                # nonzero signal. This is a digital pre-roll, not a mute bypass.
                silence = bytes(PLAYBACK_BYTES_PER_FRAME)
                for _ in range(2):
                    written = self._playback.write(silence)
                    if written is not None and written != PLAYBACK_SAMPLES_PER_FRAME:
                        raise RuntimeError("ALSA playback did not accept the silent pre-roll")
                    self._processor.render(bytes(BYTES_PER_FRAME))
                self._playback_started = True
            played = fade_pcm(scaled, self._fade_position, PLAYBACK_SAMPLE_RATE // 50)
            written = self._playback.write(played)
            if written is not None and written != PLAYBACK_SAMPLES_PER_FRAME:
                raise RuntimeError("ALSA playback did not accept the complete frame")
            self._fade_position = min(
                self._fade_position + PLAYBACK_SAMPLES_PER_FRAME, PLAYBACK_SAMPLE_RATE // 50,
            )
            self._reference_buffer.extend(self._reference_resampler.process(played))
            while len(self._reference_buffer) >= BYTES_PER_FRAME:
                reference = bytes(self._reference_buffer[:BYTES_PER_FRAME])
                del self._reference_buffer[:BYTES_PER_FRAME]
                self._processor.render(reference)

    def clear_playback(self, generation: int) -> None:
        """Drop already buffered sound, then re-open ALSA for subsequent TTS."""
        with self._playback_lock:
            if generation < self._playback_generation:
                return
            self._playback_generation = generation
            self._playback.drop()
            self._playback.close()
            self._playback = self._open_playback()
            self._reference_resampler.close()
            self._reference_resampler = PcmResampler(PLAYBACK_SAMPLE_RATE, SAMPLE_RATE)
            self._reference_buffer.clear()
            self._playback_started = False
            self._fade_position = 0
            if self._near_end_ducker is not None:
                self._near_end_ducker.reset()

    def close(self) -> None:
        self._capture.close()
        with self._playback_lock:
            self._playback.close()
            self._reference_resampler.close()
