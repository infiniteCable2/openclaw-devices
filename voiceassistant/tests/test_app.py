import unittest
import asyncio
import time
from unittest.mock import AsyncMock, patch

from openclaw_voiceassistant.app import (
    DeviceApp, _system_power, _wake_detector_from_config, _wake_enabled_from_config,
)
from openclaw_voiceassistant.controls import Controls, Indicator, Mode
from openclaw_voiceassistant.wake_word import GatedWakeDetector


class FakeButton:
    pressed = False

    def close(self):
        pass


class FakeLeds:
    def __init__(self):
        self.last = None

    def show(self, indicator, brightness):
        self.last = (indicator, brightness)

    def close(self):
        pass


class FakeBridge:
    def __init__(self):
        self.bridge_id = None
        self.wakes = 0
        self.stops = 0
        self.wake_audio = []

    def note_wake(self):
        self.wakes += 1

    def queue_wake_audio(self, frames):
        self.wake_audio = frames

    def discard_wake_audio(self):
        self.wake_audio = []

    async def stop(self):
        self.bridge_id = None
        self.stops += 1


class DeviceAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_wake_skips_engine_and_rejects_non_boolean(self):
        self.assertFalse(_wake_enabled_from_config({"wakeWordEnabled": False}))
        self.assertTrue(_wake_enabled_from_config({}))
        with self.assertRaisesRegex(ValueError, "wakeWordEnabled"):
            _wake_enabled_from_config({"wakeWordEnabled": "false"})

    async def test_wake_engine_requires_explicit_selection(self):
        with self.assertRaisesRegex(ValueError, "wakeEngine"):
            _wake_detector_from_config({})
        with self.assertRaisesRegex(ValueError, "wakeEngine"):
            _wake_detector_from_config({"wakeEngine": "other"})

    async def test_micro_wake_engine_uses_manifest_without_sherpa_fallback(self):
        with patch("openclaw_voiceassistant.app.MicroWakeDetector") as micro, \
                patch("openclaw_voiceassistant.app.NovaWakeDetector") as sherpa:
            result = _wake_detector_from_config({
                "wakeEngine": "micro", "wakeModelManifest": "/private/nova.json",
            })
            self.assertIsInstance(result, GatedWakeDetector)
            micro.assert_called_once()
            self.assertEqual(str(micro.call_args.args[0]), "/private/nova.json")
            sherpa.assert_not_called()

    async def test_second_press_enters_continuous_after_wake_mode(self):
        controls = Controls()
        button, leds, bridge = FakeButton(), FakeLeds(), FakeBridge()
        app = DeviceApp(
            controls=controls, bridge=bridge, button=button, leds=leds, node=None,
        )
        await app.tick_once(0.0)
        self.assertEqual(leds.last[0], Indicator.UNPAIRED)
        await app.connected()
        self.assertTrue(controls.muted)
        button.pressed = True
        await app.tick_once(1.0)
        button.pressed = False
        await app.tick_once(1.05)
        self.assertEqual(controls.mode, Mode.WAKE_WORD)
        self.assertEqual(bridge.wakes, 0)
        button.pressed = True
        await app.tick_once(1.15)
        button.pressed = False
        await app.tick_once(1.20)
        self.assertTrue(controls.can_capture)
        self.assertEqual(bridge.wakes, 1)
        self.assertEqual(leds.last[0], Indicator.LISTENING)
        bridge.bridge_id = "active"
        await app.tick_once(25.0)
        self.assertTrue(controls.can_capture)
        await app.disconnected()
        self.assertTrue(controls.muted)
        self.assertEqual(bridge.stops, 1)
        self.assertEqual(leds.last[0], Indicator.UNPAIRED)

    async def test_button_mute_stops_active_bridge(self):
        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        button, leds, bridge = FakeButton(), FakeLeds(), FakeBridge()
        bridge.bridge_id = "active"
        app = DeviceApp(
            controls=controls, bridge=bridge, button=button, leds=leds, node=None,
        )
        button.pressed = True
        await app.tick_once(1.0)
        button.pressed = False
        await app.tick_once(1.05)
        await app.tick_once(1.5)
        self.assertTrue(controls.muted)
        self.assertEqual(bridge.stops, 1)

    async def test_local_wake_detector_opens_timed_conversation(self):
        class Audio:
            def read(self):
                return bytes(320)

        class Detector:
            calls = 0

            def feed(self, _pcm):
                self.calls += 1
                return self.calls == 1

            def reset(self):
                pass

        controls = Controls(paired=True, mode=Mode.WAKE_WORD)
        bridge = FakeBridge()
        app = DeviceApp(
            controls=controls, bridge=bridge, button=FakeButton(), leds=FakeLeds(),
            node=None, wake_detector=Detector(), audio_input=Audio(),
        )
        task = asyncio.create_task(app._wake_loop())
        try:
            await asyncio.wait_for(self._wait_for_wake(bridge), 1)
            self.assertEqual(controls.mode, Mode.WAKE_WORD)
            self.assertTrue(controls.can_capture)
            self.assertEqual(bridge.wakes, 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_capture_keeps_running_while_keyword_pre_roll_is_decoded(self):
        class Audio:
            def read(self):
                time.sleep(0.01)
                return bytes(320)

        class SlowDetector:
            def feed(self, _pcm):
                time.sleep(0.12)
                return True

            def reset(self):
                pass

        controls = Controls(paired=True, mode=Mode.WAKE_WORD)
        bridge = FakeBridge()
        app = DeviceApp(
            controls=controls, bridge=bridge, button=FakeButton(), leds=FakeLeds(),
            node=None, wake_detector=SlowDetector(), audio_input=Audio(),
        )
        task = asyncio.create_task(app._wake_loop())
        try:
            await asyncio.wait_for(self._wait_for_wake(bridge), 1)
            self.assertGreaterEqual(len(bridge.wake_audio), 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _wait_for_wake(self, bridge):
        while not bridge.wakes:
            await asyncio.sleep(0.01)

    async def test_power_needs_explicit_confirmation(self):
        app = DeviceApp(
            controls=Controls(paired=True), bridge=FakeBridge(), button=FakeButton(),
            leds=FakeLeds(), node=None,
        )
        with self.assertRaises(ValueError):
            await app.command({"action": "power", "operation": "shutdown"})
        with patch.object(app, "_delayed_power", new_callable=AsyncMock) as power:
            self.assertEqual(await app.command({
                "action": "power", "operation": "restart", "confirm": True,
            }), {"accepted": True, "operation": "restart"})
            await asyncio.sleep(0)
            power.assert_awaited_once_with("restart")

    async def test_power_uses_only_login_manager_methods(self):
        with patch("openclaw_voiceassistant.app.subprocess.run") as run:
            _system_power("restart")
            self.assertEqual(run.call_args.args[0][-3:], ["Reboot", "b", "false"])
            _system_power("shutdown")
            self.assertEqual(run.call_args.args[0][-3:], ["PowerOff", "b", "false"])
            self.assertEqual(run.call_count, 2)
        with self.assertRaises(ValueError):
            _system_power("sleep")


if __name__ == "__main__":
    unittest.main()
