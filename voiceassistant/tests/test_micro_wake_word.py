import json

import pytest

from openclaw_voiceassistant.micro_wake_word import MicroWakeDetector, validate_nova_manifest


def make_manifest(tmp_path):
    (tmp_path / "nova.tflite").write_bytes(b"test-model")
    manifest = tmp_path / "nova.json"
    manifest.write_text(json.dumps({"wake_word": "Nova", "model": "nova.tflite"}))
    return manifest


def test_requires_nova_manifest(tmp_path):
    manifest = make_manifest(tmp_path)
    assert validate_nova_manifest(manifest) == manifest
    manifest.write_text(json.dumps({"wake_word": "Other", "model": "nova.tflite"}))
    with pytest.raises(ValueError, match="Nova"):
        validate_nova_manifest(manifest)


def test_rejects_outside_and_linked_assets(tmp_path):
    manifest = make_manifest(tmp_path)
    manifest.write_text(json.dumps({"wake_word": "Nova", "model": "../elsewhere.tflite"}))
    with pytest.raises(ValueError, match="beside"):
        validate_nova_manifest(manifest)


def test_rejects_invalid_wake_word_type(tmp_path):
    manifest = make_manifest(tmp_path)
    manifest.write_text(json.dumps({"wake_word": None, "model": "nova.tflite"}))
    with pytest.raises(ValueError, match="Nova"):
        validate_nova_manifest(manifest)


class FakeModel:
    def __init__(self):
        self.calls = 0
        self.resets = 0
        self.closed = False

    def process_streaming(self, _features):
        self.calls += 1
        return self.calls == 2

    def reset(self):
        self.resets += 1

    def close(self):
        self.closed = True


class FakeFeatures:
    def __init__(self):
        self.resets = 0

    def process_streaming(self, pcm):
        yield pcm

    def reset(self):
        self.resets += 1


def test_detection_and_reset(tmp_path):
    manifest = make_manifest(tmp_path)
    model = FakeModel()
    features = FakeFeatures()
    detector = MicroWakeDetector(
        manifest,
        model_factory=lambda _path: model,
        features_factory=lambda: features,
    )
    assert not detector.feed(bytes(320))
    assert detector.feed(bytes(320))
    assert model.resets == features.resets == 1
    with pytest.raises(ValueError, match="10-ms"):
        detector.feed(bytes(319))
    detector.close()
    assert model.closed
