import unittest

from openclaw_voiceassistant.controls import Indicator
from openclaw_voiceassistant.hardware import led_frame


class LedFrameTests(unittest.TestCase):
    def test_muted_is_red_on_all_three_pixels(self):
        frame = led_frame(Indicator.MUTED, volume=0.5)
        self.assertEqual(len(frame), 20)
        self.assertEqual(frame[:4], bytes(4))
        self.assertEqual(frame[4:8], bytes((0xE6, 0, 0, 180)))
        self.assertEqual(frame[8:12], frame[4:8])
        self.assertEqual(frame[12:16], frame[4:8])

    def test_volume_bars_and_off_pixels(self):
        frame = led_frame(Indicator.VOLUME, volume=0.5)
        self.assertEqual(frame[4:8], bytes((0xE6, 255, 255, 255)))
        self.assertEqual(frame[8:12], bytes((0xE6, 255, 255, 255)))
        self.assertEqual(frame[12:16], bytes((0xE0, 0, 0, 0)))

    def test_brightness_zero_turns_pixels_off(self):
        frame = led_frame(Indicator.IDLE, volume=0.5, brightness=0)
        self.assertEqual(frame[4:8], bytes((0xE0, 0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
