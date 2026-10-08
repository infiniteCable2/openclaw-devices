import unittest

from openclaw_voiceassistant.controls import Action, Controls, Indicator, Mode


class ControlsTests(unittest.TestCase):
    def test_button_only_mode_toggles_conversation_and_mute(self):
        control = Controls(paired=True, wake_word_enabled=False)
        self.assertFalse(control.can_detect_wake)
        control.press(1)
        self.assertEqual(control.release(1.1),
                         (Action.MUTE_CHANGED, Action.LISTENING_STARTED,
                          Action.WAKE_REQUESTED))
        self.assertEqual(control.mode, Mode.CONTINUOUS)
        self.assertTrue(control.can_capture)
        control.press(2)
        self.assertEqual(control.release(2.1),
                         (Action.MUTE_CHANGED, Action.LISTENING_ENDED))
        self.assertTrue(control.muted)
        with self.assertRaisesRegex(ValueError, "wake-word mode is disabled"):
            control.set_mode(Mode.WAKE_WORD, 3, from_button=True)

    def test_button_cycles_muted_wake_word_continuous_muted(self):
        control = Controls(paired=True)
        control.press(1)
        self.assertEqual(control.release(1.1), (Action.MUTE_CHANGED,))
        self.assertEqual(control.mode, Mode.WAKE_WORD)
        self.assertTrue(control.can_detect_wake)
        self.assertFalse(control.can_capture)
        control.press(2)
        self.assertEqual(control.release(2.1),
                         (Action.LISTENING_STARTED, Action.WAKE_REQUESTED))
        self.assertEqual(control.mode, Mode.CONTINUOUS)
        self.assertTrue(control.can_capture)
        self.assertTrue(control.persistent)
        self.assertEqual(control.tick(10_000), ())
        control.press(10_001)
        self.assertEqual(control.release(10_001.1),
                         (Action.MUTE_CHANGED, Action.LISTENING_ENDED))
        self.assertTrue(control.muted)
        self.assertFalse(control.can_capture)

    def test_unpaired_button_cannot_arm_future_microphone(self):
        control = Controls()
        control.press(0)
        self.assertEqual(control.release(0.1), ())
        control.set_paired(True)
        self.assertTrue(control.muted)
        self.assertFalse(control.can_capture)

    def test_timed_wake_expires_and_rearms_after_six_seconds(self):
        control = Controls(paired=True, mode=Mode.WAKE_WORD)
        self.assertEqual(control.wake(0), (Action.LISTENING_STARTED,))
        self.assertEqual(control.tick(5.9), ())
        self.assertEqual(control.tick(6), (Action.LISTENING_ENDED,))
        self.assertFalse(control.can_capture)
        self.assertTrue(control.can_detect_wake)

    def test_busy_activity_holds_timed_conversation_until_idle(self):
        control = Controls(paired=True, mode=Mode.WAKE_WORD)
        control.wake(0)
        control.set_activity(Indicator.HEARING, 5)
        self.assertEqual(control.tick(20), ())
        control.set_activity(Indicator.PROCESSING, 20)
        self.assertEqual(control.tick(100), ())
        control.set_activity(Indicator.SPEAKING, 100)
        self.assertEqual(control.tick(200), ())
        control.set_activity(Indicator.LISTENING, 200)
        self.assertEqual(control.tick(206), (Action.LISTENING_ENDED,))

    def test_activity_changes_led_without_disabling_full_duplex_capture(self):
        control = Controls(paired=True, mode=Mode.CONTINUOUS)
        control.wake(0)
        for activity in (Indicator.HEARING, Indicator.PROCESSING, Indicator.SPEAKING):
            control.set_activity(activity, 1)
            self.assertEqual(control.indicator, activity)
            self.assertTrue(control.can_capture)
        control.set_activity(Indicator.LISTENING, 2)
        self.assertEqual(control.indicator, Indicator.LISTENING)
        with self.assertRaises(ValueError):
            control.set_activity(Indicator.MUTED, 3)

    def test_remote_mode_cannot_override_button_mute(self):
        control = Controls(paired=True)
        with self.assertRaises(PermissionError):
            control.set_mode(Mode.CONTINUOUS, 1)
        control.set_mode(Mode.WAKE_WORD, 1, from_button=True)
        self.assertEqual(control.set_mode(Mode.CONTINUOUS, 2),
                         (Action.LISTENING_STARTED, Action.WAKE_REQUESTED))
        self.assertEqual(control.set_mode(Mode.MUTED, 3),
                         (Action.MUTE_CHANGED, Action.LISTENING_ENDED))
        self.assertEqual(control.set_mode(Mode.WAKE_WORD, 4),
                         (Action.MUTE_CHANGED,))
        control.set_mode(Mode.CONTINUOUS, 5)
        control.press(6)
        control.release(6.1)
        with self.assertRaises(PermissionError):
            control.set_mode(Mode.CONTINUOUS, 7)

    def test_unpair_mutes_and_ends_conversation(self):
        control = Controls(paired=True, mode=Mode.CONTINUOUS)
        control.wake(0)
        self.assertEqual(control.set_paired(False),
                         (Action.MUTE_CHANGED, Action.LISTENING_ENDED))
        self.assertEqual(control.indicator, Indicator.UNPAIRED)
        control.set_paired(True)
        self.assertTrue(control.muted)


if __name__ == "__main__":
    unittest.main()
