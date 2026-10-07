"""Bounded Pi-local Nova test: no audio file, network send or transcript."""

from __future__ import annotations

import argparse
from array import array
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

from openclaw_voiceassistant.apm import AudioProcessor, BYTES_PER_FRAME
from openclaw_voiceassistant.wake_word import GatedWakeDetector, NovaWakeDetector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--apm-library", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=25)
    parser.add_argument("--mode", choices=("gated", "continuous"), default="gated")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 60:
        parser.error("seconds must be between 5 and 60")

    keyword = NovaWakeDetector(args.model_dir)
    detector = GatedWakeDetector(keyword) if args.mode == "gated" else keyword
    with AudioProcessor(args.apm_library) as processor:
        # The active assistant owns ALSA's shared capture semaphore. Running
        # only arecord as its audio user lets this unprivileged test receive a
        # live PCM pipe without stopping or changing the production service.
        capture = subprocess.Popen(
            ["sudo", "-n", "-u", "openclaw-va", "arecord", "-D", "capture",
             "-f", "S16_LE", "-c", "1", "-r", "16000", "-t", "raw",
             "-d", str(args.seconds), "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            if capture.stdout is None:
                raise RuntimeError("capture pipe unavailable")
            print("READY: say Nova three times, with short pauses", flush=True)
            started = time.monotonic()
            cpu_started = time.process_time()
            hits: list[float] = []
            levels: list[float] = []
            frames_seen = 0
            while time.monotonic() - started < args.seconds + 1:
                pcm = capture.stdout.read(BYTES_PER_FRAME)
                if not pcm:
                    break
                if len(pcm) != BYTES_PER_FRAME:
                    raise RuntimeError("partial capture frame")
                processed = processor.capture(pcm, 40)
                samples = array("h")
                samples.frombytes(processed)
                if sys.byteorder != "little":
                    samples.byteswap()
                levels.append(math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768)
                frames_seen += 1
                if detector.feed(processed):
                    elapsed = time.monotonic() - started
                    hits.append(round(elapsed, 2))
                    print(f"NOVA_DETECTED at={elapsed:.2f}s", flush=True)
            capture.wait(timeout=3)
            if capture.returncode != 0:
                raise RuntimeError(f"microphone capture failed ({capture.returncode})")
            print(f"detections={len(hits)}", flush=True)
            print(f"mode={args.mode}", flush=True)
            print(f"frames_seen={frames_seen}", flush=True)
            print(f"frames_decoded={detector.frames_decoded if args.mode == 'gated' else frames_seen}", flush=True)
            print(f"acoustic_activations={detector.activations if args.mode == 'gated' else 'n/a'}", flush=True)
            print(f"level_rms_peak={max(levels, default=0):.4f}", flush=True)
            print(f"level_rms_median={statistics.median(levels) if levels else 0:.4f}", flush=True)
            print(f"cpu_ms={(time.process_time() - cpu_started) * 1000:.0f}", flush=True)
            print(f"wall_ms={(time.monotonic() - started) * 1000:.0f}", flush=True)
        finally:
            capture.stdout and capture.stdout.close()
            if capture.poll() is None:
                capture.terminate()
                try:
                    capture.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    capture.kill()
                    capture.wait(timeout=2)


if __name__ == "__main__":
    main()
