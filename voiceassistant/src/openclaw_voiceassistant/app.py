"""Pi-local controls and reconnect loop around the native Gateway node.

The device has no agent identity or independent session. A paired Gateway
connection is the sole authority that may start its bounded media bridge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Protocol

from .apm import AudioProcessor
from .audio_io import ReSpeakerAudio
from .controls import Action, Controls
from .gateway_identity import DeviceIdentity
from .gateway_node import GatewayNode
from .hardware import ReSpeakerButton, ReSpeakerLeds
from .media_bridge import MediaBridge
from .wake_word import NovaWakeDetector


class Button(Protocol):
    @property
    def pressed(self) -> bool: ...
    def close(self) -> None: ...


class Leds(Protocol):
    def show(self, indicator: Any, brightness: float) -> None: ...
    def close(self) -> None: ...


class WakeDetector(Protocol):
    def feed(self, pcm: bytes) -> bool: ...
    def reset(self) -> None: ...


class AudioInput(Protocol):
    def read(self) -> bytes: ...


def _system_power(operation: str) -> None:
    # A narrow root-owned polkit rule authorizes only these login1 actions for
    # the dedicated device service identity. No shell or general sudo access.
    if operation not in {"restart", "shutdown"}:
        raise ValueError("invalid power operation")
    subprocess.run(
        ["/usr/bin/busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
         "org.freedesktop.login1.Manager", "Reboot" if operation == "restart" else "PowerOff",
         "b", "false"],
        check=True, timeout=5, capture_output=True,
    )


class DeviceApp:
    def __init__(
        self,
        *,
        controls: Controls,
        bridge: MediaBridge,
        button: Button,
        leds: Leds,
        node: GatewayNode | None,
        wake_detector: WakeDetector | None = None,
        audio_input: AudioInput | None = None,
    ) -> None:
        self.controls = controls
        self.bridge = bridge
        self.button = button
        self.leds = leds
        self.node = node
        self.wake_detector = wake_detector
        self.audio_input = audio_input
        self._was_pressed = False

    async def command(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("action") == "power":
            operation = params.get("operation")
            if operation not in {"restart", "shutdown"} or params.get("confirm") is not True:
                raise ValueError("power operation requires explicit confirmation")
            if not self.controls.paired:
                raise PermissionError("device is not paired")
            asyncio.create_task(self._delayed_power(operation))
            return {"accepted": True, "operation": operation}
        return await self.bridge.command(params)

    async def _delayed_power(self, operation: str) -> None:
        # Give the Gateway time to deliver the acknowledgement before teardown.
        await asyncio.sleep(0.5)
        try:
            await asyncio.to_thread(_system_power, operation)
        except Exception as error:
            print(f"Device power operation failed: {type(error).__name__}", flush=True)

    async def connected(self) -> None:
        self.controls.set_paired(True)
        self.leds.show(self.controls.indicator, self.controls.brightness)

    async def disconnected(self) -> None:
        # Fail closed before waiting for an in-flight playback operation.
        self.controls.set_paired(False)
        self.leds.show(self.controls.indicator, self.controls.brightness)
        await self.bridge.stop()

    async def tick_once(self, now: float) -> None:
        pressed = self.button.pressed
        if pressed and not self._was_pressed:
            self.controls.press(now)
        actions: list[Action] = []
        if not pressed and self._was_pressed:
            actions.extend(self.controls.release(now))
        self._was_pressed = pressed
        actions.extend(self.controls.tick(now))
        if Action.WAKE_REQUESTED in actions:
            self.bridge.note_wake()
        if not self.controls.can_capture and self.bridge.bridge_id is not None:
            await self.bridge.stop()
        self.leds.show(self.controls.indicator, self.controls.brightness)

    async def _wake_loop(self) -> None:
        if self.wake_detector is None or self.audio_input is None:
            raise RuntimeError("local wake-word detector is required")
        was_armed = False
        while True:
            if not self.controls.can_detect_wake:
                if was_armed:
                    self.wake_detector.reset()
                    was_armed = False
                await asyncio.sleep(0.02)
                continue
            was_armed = True
            pcm = await asyncio.to_thread(self.audio_input.read)
            detected = await asyncio.to_thread(self.wake_detector.feed, pcm) if self.controls.can_detect_wake else False
            if detected and self.controls.can_detect_wake:
                self.controls.wake(time.monotonic())
                self.bridge.note_wake()
                self.leds.show(self.controls.indicator, self.controls.brightness)

    async def _button_loop(self) -> None:
        while True:
            await self.tick_once(time.monotonic())
            await asyncio.sleep(0.02)

    async def _gateway_loop(self) -> None:
        if self.node is None:
            raise RuntimeError("Gateway node is required")
        delay = 2.0
        while True:
            try:
                await self.node.run_once(
                    on_connected=self.connected,
                    on_disconnected=self.disconnected,
                )
                delay = 2.0
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Never print tokens, frame payloads or a credential-bearing URL.
                print(f"Gateway unavailable: {type(error).__name__}", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 30.0)

    async def run(self) -> None:
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._button_loop())
                tasks.create_task(self._gateway_loop())
                tasks.create_task(self._wake_loop())
        finally:
            await self.disconnected()
            self.button.close()
            self.leds.close()


def _required_path(config: dict[str, Any], name: str) -> Path:
    value = config.get(name)
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return Path(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw Pi voiceassistant")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("gatewayUrl"), str):
        parser.error("configuration requires gatewayUrl")
    identity = DeviceIdentity.load_or_create(_required_path(config, "identityPath"))
    token_path = _required_path(config, "tokenPath")
    gateway_token_path = (
        _required_path(config, "gatewayTokenPath")
        if "gatewayTokenPath" in config
        else None
    )
    connect_host = config.get("gatewayConnectHost")
    if connect_host is not None and not isinstance(connect_host, str):
        parser.error("gatewayConnectHost must be a private IP address")
    with AudioProcessor(_required_path(config, "apmLibraryPath")) as processor:
        audio = ReSpeakerAudio(processor)
        try:
            controls = Controls()
            bridge = MediaBridge(audio, controls)
            detector = NovaWakeDetector(_required_path(config, "wakeModelDirectory"))
            button = ReSpeakerButton()
            try:
                leds = ReSpeakerLeds()
            except BaseException:
                button.close()
                raise
            app = DeviceApp(
                controls=controls, bridge=bridge, button=button, leds=leds, node=None,
                wake_detector=detector, audio_input=audio,
            )
            node = GatewayNode(
                config["gatewayUrl"], identity, app.command,
                token_path=token_path, gateway_token_path=gateway_token_path,
                connect_host=connect_host,
            )
            app.node = node
            asyncio.run(app.run())
        finally:
            audio.close()


if __name__ == "__main__":
    main()
