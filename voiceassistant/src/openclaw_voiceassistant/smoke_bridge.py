"""Local transport-shape probe without Gateway connection or audio retention."""

from __future__ import annotations

import argparse
import asyncio
import base64
from pathlib import Path
import time

from .apm import AudioProcessor
from .audio_io import ReSpeakerAudio
from .controls import Controls, Mode
from .media_bridge import MediaBridge


async def run(library_path: Path, seconds: float) -> None:
    controls = Controls(paired=True, mode=Mode.CONTINUOUS)
    controls.wake(time.monotonic())
    with AudioProcessor(library_path) as processor:
        audio = ReSpeakerAudio(processor)
        bridge = MediaBridge(audio, controls)
        try:
            started = await bridge.start()
            received_bytes = 0
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                chunk = await bridge.pull({"bridgeId": started["bridgeId"], "timeoutMs": 250})
                received_bytes += len(base64.b64decode(chunk["base64"]))
            await bridge.stop(started["bridgeId"])
            print(f"bridge_pcm_bytes={received_bytes} bridge_closed={bridge.bridge_id is None}")
        finally:
            if bridge.bridge_id is not None:
                await bridge.stop()
            audio.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=1)
    args = parser.parse_args()
    if not 0 < args.seconds <= 3:
        parser.error("probe duration must be in (0, 3] seconds")
    asyncio.run(run(args.library, args.seconds))


if __name__ == "__main__":
    main()
