"""Bounded PCM command surface consumed by OpenClaw's node meeting transport."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, Protocol
from uuid import uuid4

from .apm import BYTES_PER_FRAME
from .controls import Controls
from .resample import PcmResampler


class AudioDevice(Protocol):
    def read(self) -> bytes: ...
    def write(self, pcm: bytes, volume: float, generation: int) -> None: ...
    def clear_playback(self, generation: int) -> None: ...


class MediaBridge:
    """One live conversation; no authority to select an agent or a session."""

    def __init__(
        self, audio: AudioDevice, controls: Controls, *, idle_timeout_seconds: float = 15.0,
    ) -> None:
        if idle_timeout_seconds <= 0:
            raise ValueError("bridge idle timeout must be positive")
        self.audio = audio
        self.controls = controls
        self.idle_timeout_seconds = idle_timeout_seconds
        self.bridge_id: str | None = None
        self.wake_sequence = 0
        self._input: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._output: asyncio.Queue[tuple[int, bytes]] = asyncio.Queue(maxsize=100)
        self._capture_task: asyncio.Task[None] | None = None
        self._playback_task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._last_media_command_at = time.monotonic()
        self._capture_error: str | None = None
        self._generation = 0
        self._output_remainder = bytearray()
        self._capture_resampler: PcmResampler | None = None
        self._playback_resampler: PcmResampler | None = None
        self._lifecycle = asyncio.Lock()

    def note_wake(self) -> None:
        if self.controls.can_capture:
            self.wake_sequence += 1

    async def command(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action")
        if action == "status":
            return {
                "wakeSequence": self.wake_sequence,
                "muted": self.controls.muted,
                "listening": self.controls.can_capture,
                "active": self.bridge_id is not None,
                "captureError": self._capture_error,
            }
        if action == "holdListening":
            if not self.controls.can_capture:
                return {"held": False}
            self.controls.extend_listening(time.monotonic())
            return {"held": True}
        if action == "start":
            return await self.start()
        if action == "pullAudio":
            return await self.pull(params)
        if action == "pushAudio":
            return await self.push(params)
        if action == "clearAudio":
            return await self.clear(params)
        if action == "stop":
            await self.stop(params.get("bridgeId"))
            return {"closed": True}
        raise ValueError("unknown media action")

    async def start(self) -> dict[str, Any]:
        async with self._lifecycle:
            return await self._start_unlocked()

    async def _start_unlocked(self) -> dict[str, Any]:
        if not self.controls.can_capture:
            raise RuntimeError("microphone is muted or device is not listening")
        if self.bridge_id is not None:
            raise RuntimeError("a device conversation is already active")
        self.bridge_id = uuid4().hex
        self._capture_error = None
        self._generation += 1
        self._capture_resampler = PcmResampler(16_000, 24_000)
        self._playback_resampler = PcmResampler(24_000, 16_000)
        try:
            await asyncio.to_thread(self.audio.clear_playback, self._generation)
        except BaseException:
            self.bridge_id = None
            self._capture_resampler.close()
            self._playback_resampler.close()
            self._capture_resampler = self._playback_resampler = None
            raise
        if not self.controls.can_capture:
            self.bridge_id = None
            self._capture_resampler.close()
            self._playback_resampler.close()
            self._capture_resampler = self._playback_resampler = None
            raise RuntimeError("microphone was muted during bridge startup")
        self._capture_task = asyncio.create_task(self._capture_loop())
        self._playback_task = asyncio.create_task(self._playback_loop())
        self._last_media_command_at = time.monotonic()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop(self.bridge_id))
        return {"bridgeId": self.bridge_id, "audioFormat": "pcm16-24khz",
                "outputGeneration": self._generation}

    def _require_bridge(self, params: dict[str, Any]) -> None:
        if self.bridge_id is None or params.get("bridgeId") != self.bridge_id:
            raise ValueError("unknown bridgeId")
        if self._capture_error:
            raise RuntimeError("audio capture failed")

    async def _capture_loop(self) -> None:
        try:
            while self.bridge_id is not None:
                pcm = await asyncio.to_thread(self.audio.read)
                if not self.controls.can_capture:
                    continue
                encoded = self._capture_resampler.process(pcm) if self._capture_resampler else b""
                if encoded:
                    self._input.put_nowait(encoded)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._capture_error = type(error).__name__

    async def _playback_loop(self) -> None:
        try:
            while True:
                generation, frame = await self._output.get()
                if generation == self._generation and self.bridge_id is not None:
                    await asyncio.to_thread(self.audio.write, frame, self.controls.volume, generation)
        except asyncio.CancelledError:
            raise

    async def _watchdog_loop(self, bridge_id: str) -> None:
        interval = min(1.0, self.idle_timeout_seconds / 2)
        while self.bridge_id == bridge_id:
            await asyncio.sleep(interval)
            if self.bridge_id != bridge_id:
                return
            if time.monotonic() - self._last_media_command_at > self.idle_timeout_seconds:
                # Never await stop() from its own watchdog task.
                asyncio.create_task(self._expire_bridge(bridge_id))
                return

    async def _expire_bridge(self, bridge_id: str) -> None:
        try:
            await self.stop(bridge_id)
        except ValueError:
            pass  # A newer bridge already replaced the expired one.
        except Exception as error:
            self._capture_error = f"watchdog_{type(error).__name__}"

    async def pull(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_bridge(params)
        self._last_media_command_at = time.monotonic()
        if not self.controls.can_capture:
            # A physical mute must also discard frames queued just before the
            # button event, even if a Gateway pull races device-side stop().
            while not self._input.empty():
                self._input.get_nowait()
            return {"base64": "", "closed": False}
        timeout = params.get("timeoutMs", 250)
        if not isinstance(timeout, int) or not 0 <= timeout <= 250:
            raise ValueError("invalid pull timeout")
        try:
            first = await asyncio.wait_for(self._input.get(), timeout=timeout / 1000)
        except TimeoutError:
            return {"base64": "", "closed": False}
        chunks = [first]
        while len(chunks) < 20 and not self._input.empty():
            chunks.append(self._input.get_nowait())
        return {"base64": base64.b64encode(b"".join(chunks)).decode("ascii"), "closed": False}

    async def push(self, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lifecycle:
            return self._push_unlocked(params)

    def _push_unlocked(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_bridge(params)
        self._last_media_command_at = time.monotonic()
        generation = params.get("outputGeneration", self._generation)
        if not isinstance(generation, int) or generation != self._generation:
            return {"dropped": True, "outputGeneration": self._generation}
        encoded = params.get("base64")
        if not isinstance(encoded, str) or len(encoded) > 1_000_000:
            raise ValueError("invalid audio payload")
        pcm = base64.b64decode(encoded, validate=True)
        if len(pcm) > 750_000 or len(pcm) % 2:
            raise ValueError("invalid PCM payload")
        converted = self._playback_resampler.process(pcm) if self._playback_resampler else b""
        self._output_remainder.extend(converted)
        while len(self._output_remainder) >= BYTES_PER_FRAME:
            frame = bytes(self._output_remainder[:BYTES_PER_FRAME])
            del self._output_remainder[:BYTES_PER_FRAME]
            self._output.put_nowait((generation, frame))
        return {"acceptedBytes": len(pcm), "outputGeneration": generation}

    async def clear(self, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lifecycle:
            return await self._clear_unlocked(params)

    async def _clear_unlocked(self, params: dict[str, Any]) -> dict[str, Any]:
        self._require_bridge(params)
        self._last_media_command_at = time.monotonic()
        requested = params.get("outputGeneration")
        if requested is not None and (not isinstance(requested, int) or requested < self._generation):
            raise ValueError("stale output generation")
        self._generation = requested if requested is not None else self._generation + 1
        self._output_remainder.clear()
        while not self._output.empty():
            self._output.get_nowait()
        await asyncio.to_thread(self.audio.clear_playback, self._generation)
        return {"outputGeneration": self._generation}

    async def stop(self, bridge_id: Any = None) -> None:
        async with self._lifecycle:
            await self._stop_unlocked(bridge_id)

    async def _stop_unlocked(self, bridge_id: Any = None) -> None:
        if self.bridge_id is None:
            return
        if bridge_id is not None and bridge_id != self.bridge_id:
            raise ValueError("unknown bridgeId")
        self.bridge_id = None
        self._generation += 1
        tasks = (self._capture_task, self._playback_task, self._watchdog_task)
        for task in tasks:
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in tasks if task is not None),
            return_exceptions=True,
        )
        self._capture_task = self._playback_task = self._watchdog_task = None
        self._output_remainder.clear()
        for queue in (self._input, self._output):
            while not queue.empty():
                queue.get_nowait()
        await asyncio.to_thread(self.audio.clear_playback, self._generation)
        for resampler in (self._capture_resampler, self._playback_resampler):
            resampler and resampler.close()
        self._capture_resampler = self._playback_resampler = None
