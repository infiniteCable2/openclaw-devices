"""Create an immutable retry config for an isolated microWakeWord experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--negative-class-weight", type=int)
    args = parser.parse_args()
    if args.output.exists() or args.model_dir.exists():
        parser.error("output config and model directory must be new")
    config = yaml.safe_load(args.source.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("features"), list):
        parser.error("invalid source config")
    if args.negative_class_weight is not None:
        if not 1 <= args.negative_class_weight <= 20:
            parser.error("negative-class-weight must be 1..20")
        config["negative_class_weight"] = [args.negative_class_weight]
    config["train_dir"] = str(args.model_dir)
    args.output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print("retry_config_ready=true")


if __name__ == "__main__":
    main()
