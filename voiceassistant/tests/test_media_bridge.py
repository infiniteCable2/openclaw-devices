import asyncio
import base64
from threading import Event
import time
import unittest
from unittest.mock import patch

from openclaw_voiceassistant.controls import Controls, Mode
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
    async def test_post_keyword_audio_is_delivered_before_new_capture(self):
        controls = Controls(paired=True, mode=Mode.WAKE_WORD)
        controls.wake(0)
        bridge = MediaBridge(FakeAudio(), controls)
        tail = bytes([1, 0]) * 160
        bridge.queue_wake_audio([tail] * 15)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            received = await bridge.pull({"bridgeId": started["bridgeId"], "timeoutMs": 250})
            decoded = base64.b64decode(received["base64"])
            self.assertTrue(decoded.startswith(tail * 15), (len(decoded), decoded[:20]))
            self.assertEqual(bridge._wake_audio, [])
            await bridge.stop(started["bridgeId"])

    async def test_pending_wake_audio_is_discarded_on_mute(self):
        controls = Controls(paired=True, mode=Mode.WAKE_WORD)
        controls.wake(0)
        bridge = MediaBridge(FakeAudio(), controls)
        bridge.queue_wake_audio([bytes(320)])
        controls.mode = Mode.MUTED
        await bridge.stop()
        self.assertEqual(bridge._wake_audio, [])

    async def test_mute_admission_and_bounded_lifecycle(self):
        audio = FakeAudio()
        controls = Controls(paired=True)
        bridge = MediaBridge(audio, controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            with self.assertRaises(RuntimeError):
                await bridge.start()
            controls.mode = Mode.CONTINUOUS
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
                               "base64": base64.b64encode(bytes(480)).decode()})
            await asyncio.sleep(0.02)
            self.assertTrue(audio.played)
            await bridge.clear({"bridgeId": identity, "outputGeneration": generation + 1})
            self.assertEqual(audio.played, [])
            dropped = await bridge.push({"bridgeId": identity, "outputGeneration": generation,
                                         "base64": base64.b64encode(bytes(480)).decode()})
            self.assertTrue(dropped["dropped"])
            await bridge.stop(identity)
            self.assertIsNone(bridge.bridge_id)

    async def test_muted_capture_does_not_leave_device(self):
        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(FakeAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            await asyncio.sleep(0.03)
            controls.mode = Mode.MUTED
            received = await bridge.pull({"bridgeId": started["bridgeId"], "timeoutMs": 0})
            self.assertEqual(received["base64"], "")
            await bridge.stop(started["bridgeId"])

    async def test_large_audio_push_uses_bounded_playout_backpressure(self):
        audio = FakeAudio()
        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(audio, controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            pcm = bytes(480 * 200)  # Two seconds; larger than the one-second queue.
            result = await bridge.push({
                "bridgeId": started["bridgeId"],
                "outputGeneration": started["outputGeneration"],
                "base64": base64.b64encode(pcm).decode(),
            })
            self.assertEqual(result["acceptedBytes"], len(pcm))
            await bridge.stop(started["bridgeId"])

    async def test_clear_preempts_backpressured_push(self):
        writing = Event()
        release = Event()

        class BlockedAudio(FakeAudio):
            def write(self, pcm, volume, generation):
                writing.set()
                release.wait(timeout=2)
                super().write(pcm, volume, generation)

        audio = BlockedAudio()
        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(audio, controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            generation = started["outputGeneration"]
            pushing = asyncio.create_task(bridge.push({
                "bridgeId": started["bridgeId"],
                "outputGeneration": generation,
                "base64": base64.b64encode(bytes(480 * 200)).decode(),
            }))
            try:
                self.assertTrue(await asyncio.to_thread(writing.wait, 2))
                clearing = asyncio.create_task(bridge.clear({
                    "bridgeId": started["bridgeId"],
                    "outputGeneration": generation + 1,
                }))
                await asyncio.sleep(0)
            finally:
                release.set()
            await clearing
            self.assertTrue((await pushing)["dropped"])
            await bridge.stop(started["bridgeId"])

    async def test_playback_recovers_once_from_a_transient_driver_failure(self):
        class FlakyAudio(FakeAudio):
            failed = False

            def write(self, pcm, volume, generation):
                if not self.failed:
                    self.failed = True
                    raise OSError("simulated driver xrun")
                super().write(pcm, volume, generation)

        audio = FlakyAudio()
        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(audio, controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            await bridge.push({
                "bridgeId": started["bridgeId"],
                "outputGeneration": started["outputGeneration"],
                "base64": base64.b64encode(bytes(480 * 2)).decode(),
            })
            await asyncio.sleep(0.02)
            self.assertEqual(len(audio.played), 2)
            self.assertIsNone((await bridge.command({"action": "status"}))["playbackError"])
            await bridge.stop(started["bridgeId"])

    async def test_persistent_playback_failure_fails_push_instead_of_stalling(self):
        class BrokenAudio(FakeAudio):
            def write(self, pcm, volume, generation):
                raise OSError("simulated persistent driver error")

        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(BrokenAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            with self.assertRaisesRegex(RuntimeError, "playback worker unavailable"):
                await bridge.push({
                    "bridgeId": started["bridgeId"],
                    "outputGeneration": started["outputGeneration"],
                    "base64": base64.b64encode(bytes(480 * 200)).decode(),
                })
            self.assertEqual((await bridge.command({"action": "status"}))["playbackError"], "OSError")
            await bridge.stop(started["bridgeId"])

    async def test_activity_keeps_capture_available(self):
        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(FakeAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            started = await bridge.start()
            result = await bridge.command({
                "action": "setActivity", "bridgeId": started["bridgeId"], "activity": "processing",
            })
            self.assertTrue(result["activitySet"])
            self.assertTrue(controls.can_capture)
            self.assertEqual(controls.indicator.value, "processing")
            await bridge.stop(started["bridgeId"])

    async def test_start_rolls_back_if_playback_cannot_initialize(self):
        class BrokenAudio(FakeAudio):
            def clear_playback(self, generation):
                raise OSError("playback unavailable")

        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(BrokenAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            with self.assertRaises(OSError):
                await bridge.start()
        self.assertIsNone(bridge.bridge_id)
        self.assertIsNone(bridge._capture_resampler)

    async def test_mute_during_start_never_opens_capture(self):
        entered, release = Event(), Event()

        class SlowAudio(FakeAudio):
            def clear_playback(self, generation):
                entered.set()
                release.wait(timeout=2)
                super().clear_playback(generation)

        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(SlowAudio(), controls)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            opening = asyncio.create_task(bridge.start())
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            controls.mode = Mode.MUTED
            release.set()
            with self.assertRaises(RuntimeError):
                await opening
        self.assertIsNone(bridge.bridge_id)

    async def test_local_watchdog_closes_orphaned_media(self):
        controls = Controls(paired=True, mode=Mode.CONTINUOUS)
        controls.wake(0)
        bridge = MediaBridge(FakeAudio(), controls, idle_timeout_seconds=0.03)
        with patch("openclaw_voiceassistant.media_bridge.PcmResampler", FakeResampler):
            await bridge.start()
            await asyncio.sleep(0.1)
        self.assertIsNone(bridge.bridge_id)

    async def test_device_settings_are_bounded_and_mute_cannot_be_undone_remotely(self):
        controls = Controls(paired=True)
        bridge = MediaBridge(FakeAudio(), controls)
        with self.assertRaises(PermissionError):
            await bridge.command({"action": "configure", "mode": "continuous"})
        controls.mode = Mode.WAKE_WORD
        self.assertEqual((await bridge.command({"action": "configure", "volumePercent": 70}))[
            "volumePercent"], 70)
        self.assertEqual((await bridge.command({"action": "configure", "brightnessPercent": 20}))[
            "brightnessPercent"], 20)
        self.assertEqual((await bridge.command({"action": "configure", "mode": "continuous"}))[
            "mode"], "continuous")
        self.assertEqual(bridge.wake_sequence, 1)
        with self.assertRaises(ValueError):
            await bridge.command({"action": "configure", "volumePercent": 101})
        with self.assertRaises(ValueError):
            await bridge.command({"action": "configure", "mode": "muted", "volumePercent": 5})


if __name__ == "__main__":
    unittest.main()
