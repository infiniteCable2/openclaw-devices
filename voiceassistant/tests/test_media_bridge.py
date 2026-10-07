import asyncio
import base64
from threading import Event
import time
import unittest
from unittest.mock import patch

from openclaw_voiceassistant.controls import Controls
from openclaw_voiceassistant.media_bridge import MediaBridge


class FakeResampler:
    def __init__(self, *_args):
        pass

    def process(self, pcm):
        return pcm

    def close(self):
        pass


class FakeAudio:
    def __init__(self):
        self.generation = 0
        self.played = []

    def read(self):
        time.sleep(0.01)
        return bytes(320)

    def write(self, pcm, _volume, generation):
        if generation == self.generation:
            self.played.append(pcm)

    def clear_playback(self, generation):
        self.generation = generation
        self.played.clear()


class MediaBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mute_admission_and_bounded_lifecycle(self):
        audio = FakeAudio()
        controls = Controls(paired=True)
        bridge = MediaBridge(audio, controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            with self.assertRaises(RuntimeError):
                await bridge.start()
            controls.muted = False
            controls.wake(0)
            bridge.note_wake()
            self.assertEqual((await bridge.command({"action": "status"}))["wakeSequence"], 1)
            self.assertTrue((await bridge.command({"action": "holdListening"}))["held"])
            started = await bridge.start()
            identity = started["bridgeId"]
            received = await bridge.pull({"bridgeId": identity, "timeoutMs": 250})
            self.assertTrue(base64.b64decode(received["base64"]))
            generation = started["outputGeneration"]
            await bridge.push({"bridgeId": identity, "outputGeneration": generation,
                               "base64": base64.b64encode(bytes(320)).decode()})
            await asyncio.sleep(0.02)
            self.assertTrue(audio.played)
            await bridge.clear({"bridgeId": identity, "outputGeneration": generation + 1})
            self.assertEqual(audio.played, [])
            dropped = await bridge.push({"bridgeId": identity, "outputGeneration": generation,
                                         "base64": base64.b64encode(bytes(320)).decode()})
            self.assertTrue(dropped["dropped"])
            await bridge.stop(identity)
            self.assertIsNone(bridge.bridge_id)

    async def test_muted_capture_does_not_leave_device(self):
        controls = Controls(paired=True, muted=False)
        controls.wake(0)
        bridge = MediaBridge(FakeAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            await asyncio.sleep(0.03)
            controls.muted = True
            received = await bridge.pull({"bridgeId": started["bridgeId"], "timeoutMs": 0})
            self.assertEqual(received["base64"], "")
            await bridge.stop(started["bridgeId"])

    async def test_start_rolls_back_if_playback_cannot_initialize(self):
        class BrokenAudio(FakeAudio):
            def clear_playback(self, generation):
                raise OSError("playback unavailable")

        controls = Controls(paired=True, muted=False)
        controls.wake(0)
        bridge = MediaBridge(BrokenAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            with self.assertRaises(OSError):
                await bridge.start()
        self.assertIsNone(bridge.bridge_id)
        self.assertIsNone(bridge._capture_resampler)
        self.assertIsNone(bridge._playback_resampler)

    async def test_mute_during_start_never_opens_capture(self):
        entered, release = Event(), Event()

        class SlowAudio(FakeAudio):
            def clear_playback(self, generation):
                entered.set()
                release.wait(timeout=2)
                super().clear_playback(generation)

        controls = Controls(paired=True, muted=False)
        controls.wake(0)
        bridge = MediaBridge(SlowAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            opening = asyncio.create_task(bridge.start())
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            controls.muted = True
            release.set()
            with self.assertRaises(RuntimeError):
                await opening
        self.assertIsNone(bridge.bridge_id)

    async def test_local_watchdog_closes_orphaned_media(self):
        controls = Controls(paired=True, muted=False)
        controls.wake(0)
        bridge = MediaBridge(FakeAudio(), controls, idle_timeout_seconds=0.03)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            await bridge.start()
            await asyncio.sleep(0.1)
        self.assertIsNone(bridge.bridge_id)


if __name__ == "__main__":
    unittest.main()
