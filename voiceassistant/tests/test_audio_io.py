import unittest
from array import array
import errno
from threading import Lock

from openclaw_voiceassistant.apm import BYTES_PER_FRAME
from openclaw_voiceassistant.audio_io import (
    PLAYBACK_BYTES_PER_FRAME, ReSpeakerAudio, fade_pcm, scale_pcm,
)


class AudioIoTests(unittest.TestCase):
    @staticmethod
    def _capture_with_results(results):
        class Capture:
            def __init__(self):
                self.results = iter(results)

            def read(self):
                return next(self.results)

        class Processor:
            def capture(self, pcm, delay_ms):
                return pcm

        audio = object.__new__(ReSpeakerAudio)
        audio._capture_lock = Lock()
        audio._capture_buffer = bytearray()
        audio._capture = Capture()
        audio._processor = Processor()
        audio._playback_delay_ms = 40
        audio._capture_channels = 1
        audio._capture_frame_bytes = BYTES_PER_FRAME
        audio._preleveler = None
        audio._last_prelevel = None
        audio._near_end_ducker = None
        audio._last_acoustic_stats = None
        return audio

    def test_capture_recovers_from_single_overrun(self) -> None:
        pcm = bytes(BYTES_PER_FRAME)
        audio = self._capture_with_results([(-errno.EPIPE, b""), (BYTES_PER_FRAME // 2, pcm)])
        self.assertEqual(audio.read(), pcm)

    def test_capture_recovers_from_transient_empty_read(self) -> None:
        pcm = bytes(BYTES_PER_FRAME)
        audio = self._capture_with_results([(0, b""), (BYTES_PER_FRAME // 2, pcm)])
        self.assertEqual(audio.read(), pcm)

    def test_capture_fails_on_persistent_overrun(self) -> None:
        audio = self._capture_with_results([(-errno.EPIPE, b"")] * 4)
        with self.assertRaisesRegex(RuntimeError, "overrun persisted"):
            audio.read()

    def test_stereo_capture_passes_both_channels_to_apm_and_returns_mono(self) -> None:
        stereo = bytes(BYTES_PER_FRAME * 2)
        audio = self._capture_with_results([(160, stereo)])
        audio._capture_channels = 2
        audio._capture_frame_bytes = BYTES_PER_FRAME * 2

        class Processor:
            def capture_stereo(self, pcm, delay_ms):
                self.seen = (pcm, delay_ms)
                return bytes(BYTES_PER_FRAME)

        audio._processor = Processor()
        self.assertEqual(audio.read(), bytes(BYTES_PER_FRAME))
        self.assertEqual(audio._processor.seen, (stereo, 40))

    def test_scaled_pcm_preserves_frame_shape_and_sign(self) -> None:
        samples = array("h", [1000, -2000] * (PLAYBACK_BYTES_PER_FRAME // 4))
        output = array("h")
        output.frombytes(scale_pcm(samples.tobytes(), 0.5))
        self.assertEqual(output.tolist()[:4], [500, -1000, 500, -1000])
        self.assertEqual(len(output), 240)

    def test_rejects_unbounded_volume_or_wrong_frame(self) -> None:
        with self.assertRaises(ValueError):
            scale_pcm(bytes(PLAYBACK_BYTES_PER_FRAME), 1.1)
        with self.assertRaises(ValueError):
            scale_pcm(b"", 0.5)

    def test_playback_fade_reaches_full_level_without_changing_frame_size(self) -> None:
        samples = array("h", [1000] * (PLAYBACK_BYTES_PER_FRAME // 2))
        first = array("h")
        first.frombytes(fade_pcm(samples.tobytes(), 0, 480))
        second = array("h")
        second.frombytes(fade_pcm(samples.tobytes(), 240, 480))
        self.assertEqual(len(first), 240)
        self.assertEqual(first[0], 2)
        self.assertEqual(first[-1], 500)
        self.assertEqual(second[-1], 1000)

    def test_first_playback_has_one_silent_preroll_and_matching_aec_reference(self) -> None:
        class Playback:
            def __init__(self):
                self.writes = []

            def write(self, pcm):
                self.writes.append(pcm)
                return 240

        class Processor:
            def __init__(self):
                self.references = []

            def render(self, pcm):
                self.references.append(pcm)

        class Resampler:
            def process(self, pcm):
                return bytes(BYTES_PER_FRAME)

        audio = object.__new__(ReSpeakerAudio)
        audio._playback_lock = Lock()
        audio._playback_generation = 1
        audio._playback = Playback()
        audio._processor = Processor()
        audio._reference_resampler = Resampler()
        audio._reference_buffer = bytearray()
        audio._playback_started = False
        audio._fade_position = 0
        audio._near_end_ducker = None
        signal = array("h", [1000] * 240).tobytes()
        audio.write(signal, 1, 1)
        audio.write(signal, 1, 1)
        self.assertEqual(len(audio._playback.writes), 4)
        self.assertEqual(audio._playback.writes[:2], [bytes(480), bytes(480)])
        self.assertEqual(len(audio._processor.references), 4)
        self.assertEqual(audio._processor.references[:2], [bytes(320), bytes(320)])
        self.assertNotEqual(audio._playback.writes[2], signal)
        final = array("h")
        final.frombytes(audio._playback.writes[3])
        self.assertEqual(final[-1], 1000)

    def test_barge_duck_scales_playout_before_aec_reference(self) -> None:
        class Ducker:
            volume_factor = 0.2

        class Playback:
            def __init__(self):
                self.writes = []

            def write(self, pcm):
                self.writes.append(pcm)
                return 240

        class Processor:
            def __init__(self):
                self.references = []

            def render(self, pcm):
                self.references.append(pcm)

        class Resampler:
            def process(self, pcm):
                return pcm[:BYTES_PER_FRAME]

        audio = object.__new__(ReSpeakerAudio)
        audio._playback_lock = Lock()
        audio._playback_generation = 1
        audio._playback = Playback()
        audio._processor = Processor()
        audio._reference_resampler = Resampler()
        audio._reference_buffer = bytearray()
        audio._playback_started = True
        audio._fade_position = 480
        audio._near_end_ducker = Ducker()
        audio.write(array("h", [1000] * 240).tobytes(), 1.0, 1)
        played = array("h")
        played.frombytes(audio._playback.writes[0])
        self.assertEqual(played[0], 200)
        reference = array("h")
        reference.frombytes(audio._processor.references[0])
        self.assertEqual(reference[0], 200)


if __name__ == "__main__":
    unittest.main()
