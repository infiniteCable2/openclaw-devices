"""Generate isolated German wake-word training audio with pinned Piper voices.

This does not touch the microphone, Pi, OpenClaw, or server-side speech services.
Keep its output outside Git and validate pronunciation before training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import wave

from piper.config import SynthesisConfig
from piper.voice import PiperVoice


NEAR_MISSES = ("Nora.", "Noah.", "Noch mal.", "Jona.", "Oma.", "Koma.")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthesize(voice: PiperVoice, text: str, path: Path, rng: random.Random) -> dict:
    config = SynthesisConfig(
        length_scale=round(rng.uniform(0.80, 1.25), 3),
        noise_scale=round(rng.uniform(0.45, 0.78), 3),
        noise_w_scale=round(rng.uniform(0.45, 0.85), 3),
        volume=round(rng.uniform(0.60, 1.0), 3),
    )
    with wave.open(str(path), "wb") as wav:
        voice.synthesize_wav(text, wav, syn_config=config)
    return {
        "file": str(path.relative_to(path.parents[1])),
        "text": text,
        "sha256": sha256(path),
        "synthesis": {
            "length_scale": config.length_scale,
            "noise_scale": config.noise_scale,
            "noise_w_scale": config.noise_w_scale,
            "volume": config.volume,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--positive-per-voice", type=int, default=250)
    parser.add_argument("--negative-per-term-voice", type=int, default=20)
    parser.add_argument("--seed", type=int, default=741309)
    args = parser.parse_args()
    if not 1 <= args.positive_per_voice <= 1000:
        parser.error("positive-per-voice must be 1..1000")
    if not 0 <= args.negative_per_term_voice <= 100:
        parser.error("negative-per-term-voice must be 0..100")
    if any(not model.is_file() or model.is_symlink() for model in args.model):
        parser.error("all models must be regular, non-symlink files")
    if args.output_dir.exists():
        parser.error("output directory already exists; never overwrite a dataset")
    args.output_dir.mkdir(parents=True, mode=0o700)
    positive = args.output_dir / "positive"
    negative = args.output_dir / "negative"
    positive.mkdir(mode=0o700)
    negative.mkdir(mode=0o700)

    rng = random.Random(args.seed)
    records = []
    models = []
    for voice_index, model in enumerate(args.model):
        models.append({"path": str(model), "sha256": sha256(model)})
        voice = PiperVoice.load(model, use_cuda=False)
        for sample_index in range(args.positive_per_voice):
            path = positive / f"voice{voice_index + 1:02d}_{sample_index + 1:04d}.wav"
            record = synthesize(voice, "Nova.", path, rng)
            records.append({"class": "positive", "voice": voice_index + 1, **record})
        for term_index, text in enumerate(NEAR_MISSES):
            for sample_index in range(args.negative_per_term_voice):
                path = negative / f"voice{voice_index + 1:02d}_term{term_index + 1:02d}_{sample_index + 1:04d}.wav"
                record = synthesize(voice, text, path, rng)
                records.append({"class": "negative", "voice": voice_index + 1, **record})
    manifest = {
        "purpose": "isolated-nova-wakeword-training-candidate",
        "seed": args.seed,
        "models": models,
        "samples": records,
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"positive_count={sum(item['class'] == 'positive' for item in records)}")
    print(f"negative_count={sum(item['class'] == 'negative' for item in records)}")
    print(f"distinct_sha256={len({item['sha256'] for item in records})}")


if __name__ == "__main__":
    main()
