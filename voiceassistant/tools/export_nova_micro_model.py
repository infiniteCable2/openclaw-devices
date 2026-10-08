"""Export a trained *experimental* microWakeWord model without selecting it.

This intentionally omits upstream's ROC step until a separate ambient test set
exists. Do not infer real-world false-accept quality from this export.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import tensorflow as tf
import yaml

from microwakeword import mixednet, utils
from microwakeword.data import FeatureHandler
from microwakeword.layers import modes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    model_dir = args.model_dir.resolve(strict=True)
    config_path = model_dir / "training_config.yaml"
    weights = model_dir / "best_weights.weights.h5"
    output = model_dir / "tflite_stream_state_internal_quant" / "nova.tflite"
    if not config_path.is_file() or not weights.is_file():
        parser.error("training config or best weights are missing")
    if output.exists() or (model_dir / "stream_state_internal").exists():
        parser.error("export target already exists")

    config = yaml.load(config_path.read_text(encoding="utf-8"), Loader=yaml.Loader)
    if Path(config["train_dir"]).resolve() != model_dir:
        parser.error("training config points to a different model directory")
    flags = argparse.Namespace(**config["flags"])
    model = mixednet.model(flags, shape=config["training_input_shape"], batch_size=1)
    model.load_weights(weights)
    processor = FeatureHandler(config)
    utils.convert_model_saved(
        model, config, folder="stream_state_internal", mode=modes.Modes.STREAM_INTERNAL_STATE_INFERENCE
    )
    utils.convert_saved_model_to_tflite(
        config,
        audio_processor=processor,
        path_to_model=str(model_dir / "stream_state_internal"),
        folder=str(output.parent),
        fname=output.name,
        quantize=True,
    )
    interpreter = tf.lite.Interpreter(model_path=str(output))
    interpreter.allocate_tensors()
    print(f"tflite_bytes={output.stat().st_size}")
    print(f"tflite_sha256={hashlib.sha256(output.read_bytes()).hexdigest()}")
    print(f"input_count={len(interpreter.get_input_details())}")
    print(f"output_count={len(interpreter.get_output_details())}")


if __name__ == "__main__":
    main()
