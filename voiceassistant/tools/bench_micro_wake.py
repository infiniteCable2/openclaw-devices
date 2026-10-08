"""Isolated microWakeWord benchmark. Never opens a mic or contacts a gateway."""

from __future__ import annotations

import argparse
from pathlib import Path
import resource
import time
import wave

from openclaw_voiceassistant.micro_wake_word import MicroWakeDetector

FRAME_BYTES = 320


def pcm_frames(wav_path: Path | None, seconds: int):
    if wav_path is None:
        for _ in range(seconds * 100):
            yield bytes(FRAME_BYTES)
        return
    with wave.open(str(wav_path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16_000):
            raise ValueError("WAV must be 16-kHz mono 16-bit PCM")
        while frame := wav.readframes(160):
            if len(frame) == FRAME_BYTES:
                yield frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wav", type=Path, help="16-kHz mono 16-bit PCM file; no audio is logged")
    parser.add_argument("--seconds", type=int, default=30, help="silence duration without --wav")
    args = parser.parse_args()
    if args.wav is None and not 1 <= args.seconds <= 3600:
        parser.error("seconds must be between 1 and 3600")

    started = time.perf_counter()
    detector = MicroWakeDetector(args.manifest)
    load_seconds = time.perf_counter() - started
    detections = []
    frames = 0
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    try:
        for frame in pcm_frames(args.wav, args.seconds):
            frames += 1
            if detector.feed(frame):
                detections.append(round(frames / 100, 2))
    finally:
        detector.close()
    cpu_seconds = time.process_time() - cpu_started
    wall_seconds = time.perf_counter() - wall_started
    print(f"model_load_s={load_seconds:.3f}")
    print(f"audio_s={frames / 100:.2f}")
    print(f"feed_wall_s={wall_seconds:.3f}")
    print(f"feed_cpu_s={cpu_seconds:.3f}")
    print(f"cpu_s_per_audio_s={cpu_seconds / max(frames / 100, 0.01):.3f}")
    print(f"peak_rss_kb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}")
    print(f"detections={detections}")


if __name__ == "__main__":
    main()
