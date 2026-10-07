import unittest

from openclaw_voiceassistant.controls import Action, Controls, Indicator, Phase


class ControlsTests(unittest.TestCase):
    def test_initial_mute_and_pairing_gate(self):
        control = Controls()
        self.assertTrue(control.muted)
        self.assertEqual(control.indicator, Indicator.UNPAIRED)
        self.assertEqual(control.wake(0), ())
        control.set_paired(True)
        self.assertEqual(control.indicator, Indicator.MUTED)
        control.press(1)
        self.assertEqual(control.release(1.1), ())
        self.assertEqual(control.tick(1.5), (Action.MUTE_CHANGED,))
        self.assertEqual(control.wake(2), (Action.LISTENING_STARTED,))
        self.assertTrue(control.can_capture)

    def test_unpaired_button_cannot_arm_future_microphone(self):
        control = Controls()
        control.press(0)
        self.assertEqual(control.release(0.1), ())
        control.set_paired(True)
        self.assertTrue(control.muted)
        self.assertFalse(control.can_capture)

    def test_timeout_and_extension(self):
        control = Controls(paired=True, muted=False)
        control.wake(0)
        control.extend_listening(15)
        self.assertEqual(control.tick(21), ())
        self.assertEqual(control.tick(36), (Action.LISTENING_ENDED,))
        self.assertFalse(control.can_capture)

    def test_stop_cancels_playback_not_agent_work(self):
        control = Controls(paired=True, muted=False)
        control.set_phase(Phase.SPEAKING)
        self.assertEqual(control.stop(), (Action.PLAYBACK_CANCEL,))
        self.assertEqual(control.phase, Phase.IDLE)

    def test_mute_stops_capture_but_not_playback(self):
        control = Controls(paired=True, muted=False)
        control.set_phase(Phase.SPEAKING)
        control.press(0)
        self.assertEqual(control.release(0.1), ())
        self.assertEqual(control.tick(0.5), (Action.MUTE_CHANGED,))
        self.assertTrue(control.muted)
        self.assertEqual(control.phase, Phase.SPEAKING)
        self.assertEqual(control.wake(2), ())

    def test_mute_ends_listening(self):
        control = Controls(paired=True, muted=False)
        control.wake(0)
        control.press(1)
        self.assertEqual(control.release(1.1), ())
        self.assertEqual(
            control.tick(1.5),
            (Action.MUTE_CHANGED, Action.LISTENING_ENDED),
        )
        self.assertFalse(control.can_capture)

    def test_hold_adjusts_bounded_volume_without_toggling_mute(self):
        control = Controls(paired=True, muted=False)
        control.press(0)
        self.assertIn(Action.VOLUME_CHANGED, control.tick(0.7))
        self.assertGreater(control.volume, 0.5)
        self.assertEqual(control.indicator, Indicator.VOLUME)
        control.release(0.8)
        self.assertFalse(control.muted)
        control.press(2)
        self.assertIn(Action.VOLUME_CHANGED, control.tick(2.7))
        self.assertLessEqual(control.volume, 0.6)

    def test_unpair_closes_listening(self):
        control = Controls(paired=True, muted=False)
        control.wake(0)
        self.assertEqual(
            control.set_paired(False),
            (Action.MUTE_CHANGED, Action.LISTENING_ENDED),
        )
        self.assertFalse(control.can_capture)
        self.assertEqual(control.indicator, Indicator.UNPAIRED)
        control.set_paired(True)
        self.assertTrue(control.muted)

    def test_large_time_jump_does_not_require_one_iteration_per_tick(self):
        control = Controls(paired=True, muted=False)
        control.press(0)
        self.assertEqual(control.tick(100000), (Action.VOLUME_CHANGED,))
        self.assertEqual(control.volume, control.config.max_volume)

    def test_double_press_wakes_without_intermediate_mute(self):
        control = Controls(paired=True, muted=False)
        control.press(0)
        self.assertEqual(control.release(0.05), ())
        control.press(0.2)
        self.assertEqual(control.release(0.25), (Action.LISTENING_STARTED, Action.WAKE_REQUESTED))
        self.assertFalse(control.muted)
        self.assertEqual(control.tick(0.6), ())
        self.assertTrue(control.can_capture)

    def test_double_press_from_muted_unmutes_and_wakes(self):
        control = Controls(paired=True)
        control.press(0)
        control.release(0.05)
        control.press(0.2)
        self.assertEqual(
            control.release(0.25),
            (Action.MUTE_CHANGED, Action.LISTENING_STARTED, Action.WAKE_REQUESTED),
        )
        self.assertTrue(control.can_capture)

    def test_second_double_press_requests_retry_while_listening(self):
        control = Controls(paired=True, muted=False)
        control.wake(0)
        control.press(1)
        control.release(1.05)
        control.press(1.2)
        self.assertEqual(control.release(1.25), (Action.WAKE_REQUESTED,))


if __name__ == "__main__":
    unittest.main()
