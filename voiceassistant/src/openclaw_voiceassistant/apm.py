"""Thin Python ownership wrapper for the native 10-ms WebRTC APM boundary."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path


SAMPLES_PER_FRAME = 160
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2
_Frame = ctypes.c_int16 * SAMPLES_PER_FRAME
_StereoFrame = ctypes.c_int16 * (SAMPLES_PER_FRAME * 2)


class _NativeStats(ctypes.Structure):
    _fields_ = [
        ("voice_detected", ctypes.c_int),
        ("output_rms_dbfs", ctypes.c_int),
        ("estimated_delay_ms", ctypes.c_int),
        ("residual_echo_likelihood", ctypes.c_float),
    ]


@dataclass(frozen=True)
class AcousticStats:
    voice_detected: bool | None
    output_rms_dbfs: int | None
    estimated_delay_ms: int | None
    residual_echo_likelihood: float | None


class AudioProcessor:
    def __init__(self, library_path: Path) -> None:
        library = ctypes.CDLL(str(library_path))
        library.openclaw_apm_create.argtypes = []
        library.openclaw_apm_create.restype = ctypes.c_void_p
        library.openclaw_apm_destroy.argtypes = [ctypes.c_void_p]
        library.openclaw_apm_render.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16), ctypes.c_int]
        library.openclaw_apm_render.restype = ctypes.c_int
        library.openclaw_apm_capture.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int16),
        ]
        library.openclaw_apm_capture.restype = ctypes.c_int
        library.openclaw_apm_capture_stereo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int16),
        ]
        library.openclaw_apm_capture_stereo.restype = ctypes.c_int
        library.openclaw_apm_get_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NativeStats)]
        library.openclaw_apm_get_stats.restype = ctypes.c_int
        handle = library.openclaw_apm_create()
        if not handle:
            raise RuntimeError("WebRTC APM initialization failed")
        self._library = library
        self._handle = handle

    def render(self, pcm: bytes) -> None:
        if len(pcm) != BYTES_PER_FRAME:
            raise ValueError("render requires exactly 10 ms of mono 16-kHz PCM")
        source = _Frame.from_buffer_copy(pcm)
        result = self._library.openclaw_apm_render(self._handle, source, SAMPLES_PER_FRAME)
        if result != 0:
            raise RuntimeError(f"WebRTC reverse processing failed: {result}")

    def capture(self, pcm: bytes, delay_ms: int) -> bytes:
        if len(pcm) != BYTES_PER_FRAME:
            raise ValueError("capture requires exactly 10 ms of mono 16-kHz PCM")
        if not 0 <= delay_ms <= 500:
            raise ValueError("delay_ms must be between 0 and 500")
        source = _Frame.from_buffer_copy(pcm)
        output = _Frame()
        result = self._library.openclaw_apm_capture(
            self._handle, source, SAMPLES_PER_FRAME, delay_ms, output
        )
        if result != 0:
            raise RuntimeError(f"WebRTC capture processing failed: {result}")
        return bytes(output)

    def capture_stereo(self, pcm: bytes, delay_ms: int) -> bytes:
        if len(pcm) != BYTES_PER_FRAME * 2:
            raise ValueError("stereo capture requires exactly 10 ms of 16-kHz PCM")
        if not 0 <= delay_ms <= 500:
            raise ValueError("delay_ms must be between 0 and 500")
        source = _StereoFrame.from_buffer_copy(pcm)
        output = _Frame()
        result = self._library.openclaw_apm_capture_stereo(
            self._handle, source, SAMPLES_PER_FRAME * 2, delay_ms, output
        )
        if result != 0:
            raise RuntimeError(f"WebRTC stereo capture processing failed: {result}")
        return bytes(output)

    def stats(self) -> AcousticStats:
        native = _NativeStats()
        result = self._library.openclaw_apm_get_stats(self._handle, ctypes.byref(native))
        if result != 0:
            raise RuntimeError(f"WebRTC acoustic statistics failed: {result}")
        return AcousticStats(
            voice_detected=None if native.voice_detected < 0 else bool(native.voice_detected),
            output_rms_dbfs=(
                native.output_rms_dbfs if -127 <= native.output_rms_dbfs <= 0 else None
            ),
            estimated_delay_ms=None if native.estimated_delay_ms < 0 else native.estimated_delay_ms,
            residual_echo_likelihood=(
                None if native.residual_echo_likelihood < 0 else native.residual_echo_likelihood
            ),
        )

    def close(self) -> None:
        if self._handle:
            self._library.openclaw_apm_destroy(self._handle)
            self._handle = None

    def __enter__(self) -> AudioProcessor:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
