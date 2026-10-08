"""Write an experimental Nova manifest next to an exported TFLite model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--probability-cutoff", type=float, default=0.5)
    parser.add_argument("--sliding-window-size", type=int, default=5)
    args = parser.parse_args()
    if not args.model.is_file() or args.model.is_symlink() or args.model.suffix != ".tflite":
        parser.error("model must be a regular TFLite file")
    if not 0 < args.probability_cutoff < 1 or not 1 <= args.sliding_window_size <= 20:
        parser.error("invalid detection settings")
    output = args.model.with_suffix(".json")
    if output.exists():
        parser.error("manifest already exists")
    manifest = {
        "type": "micro",
        "wake_word": "Nova",
        "model": args.model.name,
        "trained_languages": ["de"],
        "version": 2,
        "micro": {
            "probability_cutoff": args.probability_cutoff,
            "feature_step_size": 10,
            "sliding_window_size": args.sliding_window_size,
        },
    }
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("experimental_manifest_ready=true")


if __name__ == "__main__":
    main()
