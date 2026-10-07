import unittest
from array import array

from openclaw_voiceassistant.audio_io import PLAYBACK_BYTES_PER_FRAME, scale_pcm


class AudioIoTests(unittest.TestCase):
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
