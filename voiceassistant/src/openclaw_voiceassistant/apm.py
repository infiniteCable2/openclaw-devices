"""Thin Python ownership wrapper for the native 10-ms WebRTC APM boundary."""

from __future__ import annotations

import ctypes
from pathlib import Path


SAMPLES_PER_FRAME = 160
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2
_Frame = ctypes.c_int16 * SAMPLES_PER_FRAME


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

    def close(self) -> None:
        if self._handle:
            self._library.openclaw_apm_destroy(self._handle)
            self._handle = None

    def __enter__(self) -> AudioProcessor:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
