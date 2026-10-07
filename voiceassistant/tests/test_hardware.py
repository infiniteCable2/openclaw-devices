import unittest

from openclaw_voiceassistant.controls import Indicator
from openclaw_voiceassistant.hardware import led_frame


class LedFrameTests(unittest.TestCase):
    def test_muted_is_red_on_all_three_pixels(self):
        frame = led_frame(Indicator.MUTED)
        self.assertEqual(len(frame), 20)
        self.assertEqual(frame[:4], bytes(4))
        self.assertEqual(frame[4:8], bytes((0xFF, 0, 0, 36)))
        self.assertEqual(frame[8:12], frame[4:8])
        self.assertEqual(frame[12:16], frame[4:8])

    def test_hearing_and_processing_are_distinct(self):
        hearing = led_frame(Indicator.HEARING)
        processing = led_frame(Indicator.PROCESSING)
        speaking = led_frame(Indicator.SPEAKING)
        self.assertNotEqual(hearing[4:8], processing[4:8])
        self.assertNotEqual(processing[4:8], speaking[4:8])

    def test_brightness_zero_turns_pixels_off(self):
        frame = led_frame(Indicator.IDLE, brightness=0)
        self.assertEqual(frame[4:8], bytes((0xFF, 0, 0, 0)))

    def test_agent_brightness_accepts_percent_scale(self):
        self.assertEqual(led_frame(Indicator.MUTED, 1)[7], 180)
        self.assertEqual(led_frame(Indicator.MUTED, 0.5)[7], 90)


if __name__ == "__main__":
    unittest.main()
