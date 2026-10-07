"""Pi-local controls and reconnect loop around the native Gateway node.

The device has no agent identity or independent session. A paired Gateway
connection is the sole authority that may start its bounded media bridge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time
from typing import Any, Protocol

from .apm import AudioProcessor
from .audio_io import ReSpeakerAudio
from .controls import Action, Controls
from .gateway_identity import DeviceIdentity
from .gateway_node import GatewayNode
from .hardware import ReSpeakerButton, ReSpeakerLeds
from .media_bridge import MediaBridge


class Button(Protocol):
    @property
    def pressed(self) -> bool: ...
    def close(self) -> None: ...


class Leds(Protocol):
    def show(self, indicator: Any, volume: float) -> None: ...
    def close(self) -> None: ...


class DeviceApp:
    def __init__(
        self,
        *,
        controls: Controls,
        bridge: MediaBridge,
        button: Button,
        leds: Leds,
        node: GatewayNode,
    ) -> None:
        self.controls = controls
        self.bridge = bridge
        self.button = button
        self.leds = leds
        self.node = node
        self._was_pressed = False

    async def connected(self) -> None:
        self.controls.set_paired(True)
        self.leds.show(self.controls.indicator, self.controls.volume)

    async def disconnected(self) -> None:
        # Fail closed before waiting for an in-flight playback operation.
        self.controls.set_paired(False)
        self.leds.show(self.controls.indicator, self.controls.volume)
        await self.bridge.stop()

    async def tick_once(self, now: float) -> None:
        pressed = self.button.pressed
        if pressed and not self._was_pressed:
            self.controls.press(now)
        actions: list[Action] = []
        if not pressed and self._was_pressed:
            actions.extend(self.controls.release(now))
        self._was_pressed = pressed
        # A live bridge retains the window so subsequent utterances and
        # barge-in are not cut off by an arbitrary 20-second button timer.
        if self.bridge.bridge_id is not None:
            self.controls.extend_listening(now)
        actions.extend(self.controls.tick(now))
        if Action.WAKE_REQUESTED in actions:
            self.bridge.note_wake()
        if self.controls.muted and self.bridge.bridge_id is not None:
            await self.bridge.stop()
        self.leds.show(self.controls.indicator, self.controls.volume)

    async def _button_loop(self) -> None:
        while True:
            await self.tick_once(time.monotonic())
            await asyncio.sleep(0.02)

    async def _gateway_loop(self) -> None:
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
            node = GatewayNode(
                config["gatewayUrl"], identity, bridge.command,
                token_path=token_path, gateway_token_path=gateway_token_path,
                connect_host=connect_host,
            )
            button = ReSpeakerButton()
            try:
                leds = ReSpeakerLeds()
            except BaseException:
                button.close()
                raise
            asyncio.run(DeviceApp(
                controls=controls, bridge=bridge, button=button, leds=leds, node=node,
            ).run())
        finally:
            audio.close()


if __name__ == "__main__":
    main()
