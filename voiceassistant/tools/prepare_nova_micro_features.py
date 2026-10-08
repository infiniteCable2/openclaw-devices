"""Build a *baseline* microWakeWord feature set from isolated German WAVs.

This is deliberately a small experiment, not a production model recipe. It
requires an isolated micro-wake-word training environment and never selects a
model for the Pi. Independently sourced evaluation audio stays outside this
dataset and must not be passed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

from mmap_ninja.ragged import RaggedMmap
from microwakeword.audio.augmentation import Augmentation
from microwakeword.audio.clips import Clips
from microwakeword.audio.spectrograms import SpectrogramGeneration
import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=1500)
    parser.add_argument("--negative-class-weight", type=int, default=5)
    args = parser.parse_args()
    if not 100 <= args.steps <= 10_000:
        parser.error("steps must be 100..10000")
    if not 1 <= args.negative_class_weight <= 20:
        parser.error("negative-class-weight must be 1..20")
    if args.output_dir.exists():
        parser.error("output directory already exists; never overwrite features or weights")
    for label in ("positive", "negative"):
        if len(list((args.dataset_dir / label).glob("*.wav"))) < 30:
            parser.error(f"{label} needs at least 30 WAVs")
    manifest_path = args.dataset_dir / "manifest.json"
    if not manifest_path.is_file():
        parser.error("dataset manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["file"]: item["sha256"] for item in manifest["samples"]}
    actual = {
        str(path.relative_to(args.dataset_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for label in ("positive", "negative")
        for path in (args.dataset_dir / label).glob("*.wav")
    }
    if len(expected) != len(manifest["samples"]) or expected != actual:
        parser.error("dataset manifest does not match the WAV files")
    args.output_dir.mkdir(parents=True, mode=0o700)
    random.seed(741309)

    for label in ("positive", "negative"):
        clips = Clips(
            input_directory=str(args.dataset_dir / label),
            file_pattern="*.wav",
            remove_silence=False,
            random_split_seed=741309,
            split_count=0.1,
        )
        augmenter = Augmentation(
            augmentation_duration_s=3.2,
            augmentation_probabilities={
                "SevenBandParametricEQ": 0.10,
                "TanhDistortion": 0.05,
                "PitchShift": 0.05,
                "AddColorNoise": 0.50,
                "Gain": 1.0,
            },
            min_gain_db=-30,
            max_gain_db=0,
            color_min_snr_db=8,
            color_max_snr_db=28,
            min_jitter_s=0.195,
            max_jitter_s=0.205,
        )
        feature_root = args.output_dir / "features" / label
        for split, source_split, repetitions, slide_frames in (
            ("training", "train", 2, 10),
            ("validation", "validation", 1, 10),
            ("testing", "test", 1, 1),
        ):
            target = feature_root / split
            target.mkdir(parents=True)
            generator = SpectrogramGeneration(
                clips=clips,
                augmenter=augmenter,
                slide_frames=slide_frames,
                step_ms=10,
            )
            RaggedMmap.from_generator(
                out_dir=str(target / "wakeword_mmap"),
                sample_generator=generator.spectrogram_generator(
                    split=source_split, repeat=repetitions
                ),
                batch_size=100,
                verbose=False,
            )
            print(f"features_ready={label}/{split}", flush=True)

    config = {
        "window_step_ms": 10,
        "train_dir": str(args.output_dir / "model"),
        "features": [
            {
                "features_dir": str(args.output_dir / "features" / label),
                "sampling_weight": 1.0,
                "penalty_weight": 1.0,
                "truth": label == "positive",
                "truncation_strategy": "truncate_start",
                "type": "mmap",
            }
            for label in ("positive", "negative")
        ],
        "training_steps": [args.steps],
        "positive_class_weight": [1],
        "negative_class_weight": [args.negative_class_weight],
        "learning_rates": [0.001],
        "batch_size": 64,
        "time_mask_max_size": [0],
        "time_mask_count": [0],
        "freq_mask_max_size": [0],
        "freq_mask_count": [0],
        "eval_step_interval": 250,
        "clip_duration_ms": 1500,
        "target_minimization": 0.9,
        "minimization_metric": None,
        "maximization_metric": "auc",
    }
    (args.output_dir / "training_parameters.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    print("training_config_ready=true")


if __name__ == "__main__":
    main()
