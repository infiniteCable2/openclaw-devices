"""Audit isolated wake-word WAVs without uploading or playing private audio."""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import sys
import wave


def inspect_wav(path: Path) -> dict[str, float | int | str]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()
        if channels != 1 or width != 2 or rate not in (16_000, 22_050, 24_000, 44_100, 48_000):
            raise ValueError(f"unexpected PCM format: {channels}ch/{width * 8}bit/{rate}Hz")
        pcm = array("h")
        pcm.frombytes(wav.readframes(frames))
    if sys.byteorder != "little":
        pcm.byteswap()
    if len(pcm) != frames or not frames:
        raise ValueError("empty or incomplete PCM")
    peak = max(abs(sample) for sample in pcm) / 32768
    rms = math.sqrt(sum(sample * sample for sample in pcm) / frames) / 32768
    clipped = sum(abs(sample) >= 32767 for sample in pcm) / frames
    active = [index for index, sample in enumerate(pcm) if abs(sample) >= 328]
    if not active:
        raise ValueError("no samples above -40 dBFS")
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rate": rate,
        "duration_s": round(frames / rate, 3),
        "peak_dbfs": round(20 * math.log10(max(peak, 1 / 32768)), 1),
        "rms_dbfs": round(20 * math.log10(max(rms, 1 / 32768)), 1),
        "clipped_pct": round(clipped * 100, 3),
        "leading_quiet_s": round(active[0] / rate, 3),
        "trailing_quiet_s": round((frames - active[-1] - 1) / rate, 3),
        "active_span_s": round((active[-1] - active[0] + 1) / rate, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav_dir", type=Path)
    parser.add_argument("--provenance", type=Path)
    args = parser.parse_args()
    paths = sorted(args.wav_dir.glob("*.wav"))
    if not paths:
        parser.error("no WAV files found")
    entries = []
    for path in paths:
        entries.append({"file": path.name, **inspect_wav(path)})
    hashes = [entry["sha256"] for entry in entries]
    result = {
        "count": len(entries),
        "distinct_sha256": len(set(hashes)),
        "duration_s_range": [min(entry["duration_s"] for entry in entries), max(entry["duration_s"] for entry in entries)],
        "peak_dbfs_range": [min(entry["peak_dbfs"] for entry in entries), max(entry["peak_dbfs"] for entry in entries)],
        "rms_dbfs_range": [min(entry["rms_dbfs"] for entry in entries), max(entry["rms_dbfs"] for entry in entries)],
        "clipped_files": [entry["file"] for entry in entries if entry["clipped_pct"] > 0.1],
        "long_leading_quiet": [entry["file"] for entry in entries if entry["leading_quiet_s"] > 0.5],
        "long_trailing_quiet": [entry["file"] for entry in entries if entry["trailing_quiet_s"] > 0.5],
        "active_span_over_1_5s": [entry["file"] for entry in entries if entry["active_span_s"] > 1.5],
    }
    if args.provenance:
        provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
        if not isinstance(provenance, list):
            raise ValueError("provenance must be a list")
        expected = {item["file"]: item["sha256"] for item in provenance}
        actual = {entry["file"]: entry["sha256"] for entry in entries}
        if len(expected) != len(provenance) or expected != actual:
            raise ValueError("provenance files or SHA-256 checksums do not match")
        result["provenance_verified"] = True
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
