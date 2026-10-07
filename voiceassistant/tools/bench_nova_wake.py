"""Offline Pi KWS resource probe; feeds silence and never accesses the microphone."""

from __future__ import annotations

import argparse
from pathlib import Path
import resource
import statistics
import time

from openclaw_voiceassistant.wake_word import NovaWakeDetector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("seconds must be between 1 and 60")
    started = time.perf_counter()
    detector = NovaWakeDetector(args.model_dir)
    load_ms = (time.perf_counter() - started) * 1_000
    frame = bytes(320)
    latencies = []
    detections = 0
    feed_started = time.perf_counter()
    cpu_started = time.process_time()
    for _ in range(args.seconds * 100):
        tick = time.perf_counter()
        detections += int(detector.feed(frame))
        latencies.append((time.perf_counter() - tick) * 1_000)
    print(f"model_load_ms={load_ms:.1f}")
    print(f"silence_feed_mean_ms={statistics.mean(latencies):.2f}")
    print(f"silence_feed_max_ms={max(latencies):.2f}")
    print(f"silence_feed_wall_ms={(time.perf_counter() - feed_started) * 1_000:.1f}")
    print(f"silence_feed_cpu_ms={(time.process_time() - cpu_started) * 1_000:.1f}")
    print(f"silence_detections={detections}")
    print(f"peak_rss_kb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}")
    detector.reset()
    print("stream_reset_ok=true")


if __name__ == "__main__":
    main()
