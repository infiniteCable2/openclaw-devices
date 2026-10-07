"""Bounded on-device hardware probe; never saves or transmits captured audio."""

from __future__ import annotations

import argparse
from array import array
import math
from pathlib import Path
import statistics
import time

from .apm import AudioProcessor, SAMPLES_PER_FRAME
from .audio_io import ReSpeakerAudio, SAMPLE_RATE
from .controls import Indicator
from .hardware import ReSpeakerButton, ReSpeakerLeds


def capture_metrics(audio: ReSpeakerAudio, seconds: float) -> dict[str, float | int]:
    peaks: list[float] = []
    powers: list[float] = []
    frames = max(1, round(seconds * 100))
    for _ in range(frames):
        samples = array("h")
        samples.frombytes(audio.read())
        peaks.append(max(abs(value) for value in samples) / 32768)
        powers.append(sum(value * value for value in samples) / len(samples))
    return {
        "frames": frames,
        "peak": round(max(peaks), 4),
        "rms": round(math.sqrt(statistics.mean(powers)) / 32768, 4),
    }


def play_probe(audio: ReSpeakerAudio) -> None:
    # A short, intentionally quiet 440-Hz check; not a speaker stress test.
    for frame_index in range(30):
        frame = array(
            "h",
            (
                round(32767 * 0.1 * math.sin(2 * math.pi * 440 * (frame_index * SAMPLES_PER_FRAME + i) / SAMPLE_RATE))
                for i in range(SAMPLES_PER_FRAME)
            ),
        )
        audio.write(frame.tobytes(), 0.4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--capture-seconds", type=float, default=0)
    parser.add_argument("--play-tone", action="store_true")
    parser.add_argument("--leds", action="store_true")
    parser.add_argument("--button-seconds", type=float, default=0)
    args = parser.parse_args()
    if not 0 <= args.capture_seconds <= 5 or not 0 <= args.button_seconds <= 10:
        parser.error("probe duration exceeds limit")
    if args.leds:
        leds = ReSpeakerLeds()
        try:
            for indicator in (Indicator.UNPAIRED, Indicator.MUTED, Indicator.LISTENING):
                leds.show(indicator, 0.5)
                time.sleep(0.5)
        finally:
            leds.close()
        print("led_probe=complete")
    if args.button_seconds:
        button = ReSpeakerButton()
        try:
            seen = set()
            deadline = time.monotonic() + args.button_seconds
            while time.monotonic() < deadline:
                seen.add(button.pressed)
                time.sleep(0.02)
        finally:
            button.close()
        print(f"button_states={','.join(str(value).lower() for value in sorted(seen))}")
    if args.capture_seconds or args.play_tone:
        with AudioProcessor(args.library) as processor:
            audio = ReSpeakerAudio(processor)
            try:
                if args.capture_seconds:
                    print(capture_metrics(audio, args.capture_seconds))
                if args.play_tone:
                    play_probe(audio)
                    print("tone_probe=complete")
            finally:
                audio.close()


if __name__ == "__main__":
    main()
