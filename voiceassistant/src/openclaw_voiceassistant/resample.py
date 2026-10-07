"""Small streaming PCM resampler backed by the Pi's libspeexdsp.

The Meeting transport speaks 24-kHz mono PCM; local WebRTC APM requires a
native 16-kHz rate. This wrapper preserves phase across arbitrary chunks.
"""

from __future__ import annotations

import ctypes


class PcmResampler:
    def __init__(self, input_rate: int, output_rate: int, quality: int = 5) -> None:
        if (input_rate, output_rate) not in ((16_000, 24_000), (24_000, 16_000)):
            raise ValueError("unsupported voiceassistant rate conversion")
        if not 0 <= quality <= 10:
            raise ValueError("invalid Speex resampler quality")
        library = ctypes.CDLL("libspeexdsp.so.1")
        library.speex_resampler_init.argtypes = [
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        library.speex_resampler_init.restype = ctypes.c_void_p
        library.speex_resampler_process_int.argtypes = [
            ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_uint),
        ]
        library.speex_resampler_process_int.restype = ctypes.c_int
        library.speex_resampler_destroy.argtypes = [ctypes.c_void_p]
        error = ctypes.c_int()
        handle = library.speex_resampler_init(1, input_rate, output_rate, quality, ctypes.byref(error))
        if not handle or error.value != 0:
            raise RuntimeError(f"Speex resampler initialization failed: {error.value}")
        self._library = library
        self._handle = handle
        self.input_rate = input_rate
        self.output_rate = output_rate

    def process(self, pcm: bytes) -> bytes:
        if len(pcm) % 2:
            raise ValueError("PCM input has an incomplete sample")
        if not pcm:
            return b""
        samples = len(pcm) // 2
        source = (ctypes.c_int16 * samples).from_buffer_copy(pcm)
        maximum = (samples * self.output_rate // self.input_rate) + 256
        output = (ctypes.c_int16 * maximum)()
        input_length = ctypes.c_uint(samples)
        output_length = ctypes.c_uint(maximum)
        result = self._library.speex_resampler_process_int(
            self._handle, 0, source, ctypes.byref(input_length), output, ctypes.byref(output_length)
        )
        if result != 0 or input_length.value != samples:
            raise RuntimeError(f"Speex resampler failed or did not consume all input: {result}")
        return bytes(output)[: output_length.value * 2]

    def close(self) -> None:
        if self._handle:
            self._library.speex_resampler_destroy(self._handle)
            self._handle = None

    def __enter__(self) -> PcmResampler:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
