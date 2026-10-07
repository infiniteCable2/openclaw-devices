import unittest

from openclaw_voiceassistant.app import DeviceApp
from openclaw_voiceassistant.controls import Controls, Indicator


class FakeButton:
    pressed = False

    def close(self):
        pass


class FakeLeds:
    def __init__(self):
        self.last = None

    def show(self, indicator, volume):
        self.last = (indicator, volume)

    def close(self):
        pass


class FakeBridge:
    def __init__(self):
        self.bridge_id = None
        self.wakes = 0
        self.stops = 0

    def note_wake(self):
        self.wakes += 1

    async def stop(self):
        self.bridge_id = None
        self.stops += 1


class DeviceAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_double_press_wakes_only_after_paired_connection(self):
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
        controls = Controls(paired=True, muted=False)
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


if __name__ == "__main__":
    unittest.main()
