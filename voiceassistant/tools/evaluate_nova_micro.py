"""Offline-only wake-word recall/false-hit probe; never uses the live mic."""

from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import subprocess

from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures


FRAME_BYTES = 320  # 10 ms, 16 kHz, signed 16-bit mono
PRE_ROLL_FRAMES = 200
POST_ROLL_FRAMES = 100


def decode_pcm(path: Path) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
            "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout[: len(result.stdout) // FRAME_BYTES * FRAME_BYTES]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wav-dir", type=Path, required=True)
    parser.add_argument("--expect", choices=("positive", "negative"), required=True)
    parser.add_argument("--cutoff", type=float)
    args = parser.parse_args()
    paths = sorted(args.wav_dir.glob("*.wav"))
    if not paths:
        parser.error("no WAV files found")
    if args.cutoff is not None and not 0 < args.cutoff < 1:
        parser.error("cutoff must be between zero and one")

    model = MicroWakeWord.from_config(args.manifest)
    if args.cutoff is not None:
        model.probability_cutoff = args.cutoff
    features = MicroWakeWordFeatures()
    hits = []
    try:
        for path in paths:
            features.reset()
            model.reset()
            pcm = bytes(FRAME_BYTES * PRE_ROLL_FRAMES) + decode_pcm(path) + bytes(FRAME_BYTES * POST_ROLL_FRAMES)
            hit_at = None
            for frame_index in range(len(pcm) // FRAME_BYTES):
                start = frame_index * FRAME_BYTES
                for feature_slice in features.process_streaming(pcm[start : start + FRAME_BYTES]):
                    if model.process_streaming(feature_slice):
                        hit_at = round((frame_index - PRE_ROLL_FRAMES) / 100, 2)
                        break
                if hit_at is not None:
                    break
            if hit_at is not None:
                hits.append((path.name, hit_at))
    finally:
        model.close()

    print(f"expect={args.expect}")
    print(f"cutoff={model.probability_cutoff}")
    print(f"clips={len(paths)}")
    print(f"hits={len(hits)}")
    print(f"pre_roll_hits={sum(time < 0 for _, time in hits)}")
    if hits:
        print(f"hit_time_median_s={statistics.median(time for _, time in hits):.2f}")
    if args.expect == "positive":
        missed = sorted({path.name for path in paths} - {name for name, _ in hits})
        print(f"missed_files={missed}")
    else:
        print(f"false_hit_files_first_20={[name for name, _ in hits[:20]]}")


if __name__ == "__main__":
    main()
