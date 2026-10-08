"""Make an immutable training set from the Piper baseline and new held-in voices.

The independent Voice Designer holdout must never be passed as an extra input.
The command does not touch the Pi, OpenClaw, or the running assistant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from audit_wake_wavs import inspect_wav


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_wavs(directory: Path) -> list[Path]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"not a regular input directory: {directory}")
    paths = sorted(directory.glob("*.wav"))
    if not paths or any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError(f"no valid WAV files in {directory}")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dataset-dir", type=Path, required=True)
    parser.add_argument("--extra-positive-dir", type=Path, required=True)
    parser.add_argument("--extra-negative-dir", type=Path, required=True)
    parser.add_argument("--holdout-provenance", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output already exists; never overwrite a dataset")
    base_manifest_path = args.base_dataset_dir / "manifest.json"
    if not base_manifest_path.is_file() or base_manifest_path.is_symlink():
        parser.error("base dataset manifest is missing or a symlink")
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    expected = {item["file"]: item["sha256"] for item in base_manifest["samples"]}
    actual = {
        str(path.relative_to(args.base_dataset_dir)): sha256(path)
        for label in ("positive", "negative")
        for path in checked_wavs(args.base_dataset_dir / label)
    }
    if len(expected) != len(base_manifest["samples"]) or expected != actual:
        parser.error("base dataset manifest does not match its WAV files")
    extra = {
        "positive": checked_wavs(args.extra_positive_dir),
        "negative": checked_wavs(args.extra_negative_dir),
    }
    skipped_positive = []
    screened_positive = []
    for path in extra["positive"]:
        stats = inspect_wav(path)
        if (
            stats["duration_s"] > 2.0
            or stats["leading_quiet_s"] > 0.5
            or stats["trailing_quiet_s"] > 0.5
            or stats["active_span_s"] > 1.5
            or stats["clipped_pct"] > 0.1
        ):
            skipped_positive.append(path.name)
        else:
            screened_positive.append(path)
    if len(screened_positive) < 18:
        parser.error("too few clean extra positive clips after screening")
    extra["positive"] = screened_positive
    holdout = json.loads(args.holdout_provenance.read_text(encoding="utf-8"))
    if not isinstance(holdout, list) or not holdout:
        parser.error("holdout provenance must be a nonempty list")
    holdout_hashes = {item["sha256"] for item in holdout}
    if holdout_hashes.intersection(actual.values()) or any(
        sha256(path) in holdout_hashes for paths in extra.values() for path in paths
    ):
        parser.error("holdout audio overlaps with the training dataset")
    args.output_dir.mkdir(parents=True, mode=0o700)
    records = []
    for label in ("positive", "negative"):
        target_dir = args.output_dir / label
        target_dir.mkdir(mode=0o700)
        sources = [
            ("base", path)
            for path in checked_wavs(args.base_dataset_dir / label)
        ] + [("voice_designer", path) for path in extra[label]]
        for index, (origin, source) in enumerate(sources, start=1):
            target = target_dir / f"{origin}_{index:04d}.wav"
            shutil.copyfile(source, target)
            records.append({
                "class": label,
                "file": str(target.relative_to(args.output_dir)),
                "sha256": sha256(target),
                "origin": origin,
                "source_name": source.name,
            })
    manifest = {
        "purpose": "isolated-nova-wakeword-training-candidate",
        "base_manifest_sha256": sha256(base_manifest_path),
        "holdout_manifest_sha256": sha256(args.holdout_provenance),
        "skipped_extra_positive": skipped_positive,
        "samples": records,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for label in ("positive", "negative"):
        print(f"{label}_count={sum(item['class'] == label for item in records)}")
    print(f"distinct_sha256={len({item['sha256'] for item in records})}")
    print(f"skipped_extra_positive={len(skipped_positive)}")


if __name__ == "__main__":
    main()
