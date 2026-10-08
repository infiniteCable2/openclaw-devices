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

from .apm import BYTES_PER_FRAME, SAMPLES_PER_FRAME
from .resample import PcmResampler


SAMPLE_RATE = 16_000
PLAYBACK_SAMPLE_RATE = 24_000
PLAYBACK_SAMPLES_PER_FRAME = 240
PLAYBACK_BYTES_PER_FRAME = PLAYBACK_SAMPLES_PER_FRAME * 2


class EchoProcessor(Protocol):
    def render(self, pcm: bytes) -> None: ...
    def capture(self, pcm: bytes, delay_ms: int) -> bytes: ...


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


class ReSpeakerAudio:
    """Two named ALSA streams; no dependency on a mutable card number."""

    def __init__(self, processor: EchoProcessor, *, playback_delay_ms: int = 40) -> None:
        if not 0 <= playback_delay_ms <= 500:
            raise ValueError("playback_delay_ms must be in [0, 500]")
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
            self._capture.setchannels(1)
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
        self._capture_buffer = bytearray()
        self._reference_resampler = PcmResampler(PLAYBACK_SAMPLE_RATE, SAMPLE_RATE)
        self._reference_buffer = bytearray()

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
            while len(self._capture_buffer) < BYTES_PER_FRAME:
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
                if len(data) != frames * 2:
                    raise RuntimeError("ALSA capture returned an unexpected PCM size")
                self._capture_buffer.extend(data)
                if len(self._capture_buffer) > BYTES_PER_FRAME * 20:
                    raise RuntimeError("ALSA capture exceeded the bounded frame buffer")
            raw = bytes(self._capture_buffer[:BYTES_PER_FRAME])
            del self._capture_buffer[:BYTES_PER_FRAME]
            return self._processor.capture(raw, self._playback_delay_ms)

    def write(self, pcm: bytes, volume: float, generation: int = 0) -> None:
        played = scale_pcm(pcm, volume)
        with self._playback_lock:
            if generation != self._playback_generation:
                return
            written = self._playback.write(played)
            if written is not None and written != PLAYBACK_SAMPLES_PER_FRAME:
                raise RuntimeError("ALSA playback did not accept the complete frame")
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

    def close(self) -> None:
        self._capture.close()
        with self._playback_lock:
            self._playback.close()
            self._reference_resampler.close()
