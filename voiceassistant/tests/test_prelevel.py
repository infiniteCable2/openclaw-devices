import unittest
from array import array

from openclaw_voiceassistant.apm import AcousticStats
from openclaw_voiceassistant.prelevel import NearEndDucker, SpeechPreLeveler


def frame(amplitude: int) -> bytes:
    return array("h", [amplitude, -amplitude] * 80).tobytes()


def stats(voice: bool, echo: float = 0.0) -> AcousticStats:
    return AcousticStats(voice, None, None, echo)


class SpeechPreLevelerTests(unittest.TestCase):
    def test_weak_confirmed_speech_is_raised_but_bounded(self) -> None:
        leveler = SpeechPreLeveler()
        for _ in range(50):
            leveler.process(frame(30), stats(False))
        for _ in range(100):
            result = leveler.process(frame(400), stats(True))
        self.assertGreater(result.gain_db, 0)
        self.assertLessEqual(result.gain_db, 9)
        self.assertGreater(result.estimated_snr_db, 4)

    def test_noise_and_echo_never_trigger_upward_gain(self) -> None:
        leveler = SpeechPreLeveler()
        for _ in range(100):
            result = leveler.process(frame(500), stats(False))
        self.assertEqual(result.gain_db, 0)
        for _ in range(100):
            result = leveler.process(frame(1000), stats(True, echo=0.8))
        self.assertEqual(result.gain_db, 0)

    def test_missing_echo_evidence_cannot_confirm_near_end_speech(self) -> None:
        leveler = SpeechPreLeveler()
        for _ in range(50):
            leveler.process(frame(30), stats(False))
        unknown = AcousticStats(True, None, None, None)
        for _ in range(100):
            result = leveler.process(frame(400), unknown)
        self.assertEqual(result.gain_db, 0)
        self.assertFalse(result.confirmed_voice)

    def test_close_loud_speech_reduces_gain_without_overflow(self) -> None:
        leveler = SpeechPreLeveler()
        for _ in range(30):
            leveler.process(frame(30), stats(False))
        for _ in range(100):
            leveler.process(frame(400), stats(True))
        for _ in range(100):
            result = leveler.process(frame(25000), stats(True))
        self.assertLess(result.gain_db, 0)
        self.assertEqual(len(result.pcm), 320)

    def test_sudden_close_speech_has_immediate_peak_protection(self) -> None:
        leveler = SpeechPreLeveler()
        for _ in range(20):
            leveler.process(frame(30), stats(False))
        for _ in range(100):
            leveler.process(frame(400), stats(True))
        result = leveler.process(frame(30000), stats(True))
        self.assertLessEqual(result.input_peak_dbfs + result.gain_db, -1)

    def test_silence_does_not_decay_after_a_short_pause(self) -> None:
        leveler = SpeechPreLeveler()
        for _ in range(30):
            leveler.process(frame(30), stats(False))
        for _ in range(80):
            leveler.process(frame(400), stats(True))
        gain = leveler.gain_db
        for _ in range(1200):
            result = leveler.process(frame(30), stats(False))
        self.assertAlmostEqual(result.gain_db, gain)

    def test_invalid_frame_and_configuration_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SpeechPreLeveler(max_gain_db=30)
        with self.assertRaises(ValueError):
            SpeechPreLeveler().process(b"", stats(False))


class NearEndDuckerTests(unittest.TestCase):
    def test_requires_sustained_non_echo_voice_and_releases_after_pause(self) -> None:
        ducker = NearEndDucker()
        for _ in range(20):
            ducker.observe(stats(True, echo=0.8))
        self.assertEqual(ducker.volume_factor, 1.0)
        for _ in range(7):
            ducker.observe(stats(True))
        self.assertEqual(ducker.volume_factor, 1.0)
        ducker.observe(stats(True))
        self.assertEqual(ducker.volume_factor, 0.2)
        for _ in range(19):
            ducker.observe(stats(False))
        self.assertEqual(ducker.volume_factor, 0.2)
        ducker.observe(stats(False))
        self.assertEqual(ducker.volume_factor, 1.0)

    def test_reset_clears_a_pending_or_active_candidate(self) -> None:
        ducker = NearEndDucker()
        for _ in range(8):
            ducker.observe(stats(True))
        self.assertTrue(ducker.active)
        ducker.reset()
        self.assertFalse(ducker.active)

    def test_unknown_echo_state_does_not_duck_playback(self) -> None:
        ducker = NearEndDucker()
        unknown = AcousticStats(True, None, None, None)
        for _ in range(20):
            ducker.observe(unknown)
        self.assertEqual(ducker.volume_factor, 1.0)


if __name__ == "__main__":
    unittest.main()
