"""Experimental microWakeWord adapter; never selected by the running service.

The Pi captures 10-ms 16-kHz mono PCM frames. This adapter deliberately has
the same ``feed``/``reset`` contract as the existing wake detector, so the
model can be measured without changing transport or agent behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .apm import BYTES_PER_FRAME


def validate_nova_manifest(manifest_path: Path) -> Path:
    """Reject missing, linked or out-of-directory model assets before loading."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("microWakeWord manifest is missing or a symlink")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("wake_word"), str)
        or manifest["wake_word"].casefold() != "nova"
    ):
        raise ValueError("microWakeWord manifest must identify the Nova wake word")
    model_name = manifest.get("model")
    if not isinstance(model_name, str) or not model_name or Path(model_name).name != model_name:
        raise ValueError("microWakeWord model must be a file beside its manifest")
    model_path = manifest_path.parent / model_name
    if not model_path.is_file() or model_path.is_symlink():
        raise ValueError("microWakeWord model is missing or a symlink")
    return manifest_path


class MicroWakeDetector:
    """Feed local PCM to a custom, *measured* Nova microWakeWord model."""

    def __init__(
        self,
        manifest_path: Path,
        *,
        model_factory: Callable[[Path], Any] | None = None,
        features_factory: Callable[[], Any] | None = None,
    ) -> None:
        manifest_path = validate_nova_manifest(manifest_path)
        if model_factory is None or features_factory is None:
            from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures

            model_factory = model_factory or MicroWakeWord.from_config
            features_factory = features_factory or MicroWakeWordFeatures
        self._model = model_factory(manifest_path)
        self._features = features_factory()

    def feed(self, pcm: bytes) -> bool:
        if len(pcm) != BYTES_PER_FRAME:
            raise ValueError("wake-word input must be one 10-ms 16-kHz PCM frame")
        for features in self._features.process_streaming(pcm):
            if self._model.process_streaming(features):
                self.reset()
                return True
        return False

    def reset(self) -> None:
        self._features.reset()
        self._model.reset()

    def close(self) -> None:
        self._model.close()
