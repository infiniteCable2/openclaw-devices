import struct
import unittest

from openclaw_voiceassistant.wake_word import GatedWakeDetector


def frame(level: int) -> bytes:
    return struct.pack("<160h", *([level] * 160))


class FakeKeywordDetector:
    def __init__(self, *, detect_level: int | None = None):
        self.detect_level = detect_level
        self.frames = []
        self.resets = 0

    def feed(self, pcm):
        self.frames.append(pcm)
        return self.detect_level is not None and pcm == frame(self.detect_level)

    def reset(self):
        self.resets += 1


class GatedWakeDetectorTests(unittest.TestCase):
    def test_silence_does_not_run_keyword_model(self):
        keyword = FakeKeywordDetector()
        gate = GatedWakeDetector(keyword)
        for _ in range(1_000):
            self.assertFalse(gate.feed(frame(0)))
        self.assertEqual(gate.frames_seen, 1_000)
        self.assertEqual(gate.frames_decoded, 0)
        self.assertEqual(gate.activations, 0)

    def test_candidate_replays_audio_before_onset(self):
        keyword = FakeKeywordDetector(detect_level=500)
        gate = GatedWakeDetector(keyword, pre_roll_frames=100)
        for _ in range(120):
            gate.feed(frame(0))
        self.assertFalse(gate.feed(frame(200)))
        self.assertEqual(keyword.frames, [])
        self.assertTrue(gate.feed(frame(500)))
        self.assertEqual(keyword.frames[-2:], [frame(200), frame(500)])
        self.assertEqual(len(keyword.frames), 100)
        self.assertFalse(gate.active)
        self.assertEqual(keyword.resets, 1)

    def test_one_frame_impulse_is_not_enough_to_activate(self):
        keyword = FakeKeywordDetector()
        gate = GatedWakeDetector(keyword)
        gate.feed(frame(0))
        gate.feed(frame(8_000))
        for _ in range(100):
            gate.feed(frame(0))
        self.assertEqual(gate.activations, 0)
        self.assertEqual(keyword.frames, [])

    def test_noisy_period_falls_back_to_continuous_detection(self):
        keyword = FakeKeywordDetector()
        gate = GatedWakeDetector(keyword)
        for _ in range(200):
            gate.feed(frame(4_000))
        self.assertTrue(gate.active)
        self.assertGreaterEqual(gate.frames_decoded, 200)
        self.assertEqual(gate.activations, 1)

    def test_steady_moderate_noise_becomes_learned_background(self):
        keyword = FakeKeywordDetector()
        gate = GatedWakeDetector(keyword)
        for _ in range(500):
            gate.feed(frame(100))
        self.assertFalse(gate.active)
        decoded_after_learning = gate.frames_decoded
        for _ in range(100):
            gate.feed(frame(100))
        self.assertEqual(gate.frames_decoded, decoded_after_learning)
        gate.feed(frame(500))
        gate.feed(frame(500))
        self.assertTrue(gate.active)

    def test_trailing_quiet_resets_decoder_and_rearms(self):
        keyword = FakeKeywordDetector()
        gate = GatedWakeDetector(keyword, pre_roll_frames=5, release_frames=3)
        gate.feed(frame(500))
        gate.feed(frame(500))
        self.assertTrue(gate.active)
        for _ in range(3):
            gate.feed(frame(0))
        self.assertFalse(gate.active)
        self.assertEqual(keyword.resets, 1)
        gate.feed(frame(500))
        gate.feed(frame(500))
        self.assertEqual(gate.activations, 2)

    def test_reset_discards_private_audio_and_requires_new_onset(self):
        keyword = FakeKeywordDetector()
        gate = GatedWakeDetector(keyword)
        gate.feed(frame(800))
        gate.reset()
        self.assertFalse(gate.feed(frame(0)))
        self.assertEqual(gate.activations, 0)
        self.assertEqual(keyword.frames, [])
        self.assertEqual(keyword.resets, 1)

    def test_invalid_frame_fails_closed(self):
        gate = GatedWakeDetector(FakeKeywordDetector())
        with self.assertRaises(ValueError):
            gate.feed(b"short")


if __name__ == "__main__":
    unittest.main()
