"""Pi-local, offline Nova keyword spotting; no raw standby audio leaves the Pi."""

from __future__ import annotations

from array import array
from pathlib import Path
import sys

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
