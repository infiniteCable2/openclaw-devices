import unittest
from array import array
import errno
from threading import Lock

from openclaw_voiceassistant.apm import BYTES_PER_FRAME
from openclaw_voiceassistant.audio_io import PLAYBACK_BYTES_PER_FRAME, ReSpeakerAudio, scale_pcm


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


if __name__ == "__main__":
    unittest.main()
