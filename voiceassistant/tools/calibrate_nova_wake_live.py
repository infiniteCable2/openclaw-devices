"""One consented Pi capture, held only in RAM, for offline Nova KWS comparison."""

from __future__ import annotations

import argparse
from array import array
import gc
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import wave

from openclaw_voiceassistant.apm import AudioProcessor, BYTES_PER_FRAME


VARIANTS = """\
N OW1 V AA1 :2.0 #0.05 @NOVA_OW_AA
N AO1 V AA1 :2.0 #0.05 @NOVA_AO_AA
N AO1 V AH0 :2.0 #0.05 @NOVA_AO_AH
N OW1 V AH1 :2.0 #0.05 @NOVA_OW_AH
"""


def level(pcm: bytes) -> float:
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768


def spotter_for(model_dir: Path, keywords_file: Path):
    import sherpa_onnx

    return sherpa_onnx.KeywordSpotter(
        tokens=str(model_dir / "tokens.txt"),
        encoder=str(model_dir / "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx"),
        decoder=str(model_dir / "decoder-epoch-13-avg-2-chunk-8-left-64.onnx"),
        joiner=str(model_dir / "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx"),
        keywords_file=str(keywords_file), num_threads=1, provider="cpu",
    )


def recognize(spotter, pcm: bytes) -> list[tuple[float, str]]:
    import numpy as np

    stream = spotter.create_stream()
    hits: list[tuple[float, str]] = []
    padded = pcm + bytes(16_000)  # 0.5 s trailing silence
    for offset in range(0, len(padded), BYTES_PER_FRAME * 10):
        chunk = padded[offset:offset + BYTES_PER_FRAME * 10]
        samples = np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768
        stream.accept_waveform(16_000, samples)
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
        result = spotter.get_result(stream)
        if result:
            hits.append((round((offset + len(chunk)) / 32_000, 2), str(result)))
            spotter.reset_stream(stream)
    return hits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--apm-library", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=18)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 30:
        parser.error("seconds must be between 5 and 30")

    if args.self_test:
        sample = args.model_dir / "test_wavs/en_0.wav"
        with wave.open(str(sample), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16_000):
                raise RuntimeError("model self-test sample must be 16-kHz mono PCM16")
            audio = wav.readframes(wav.getnframes())
        spotter = spotter_for(args.model_dir, args.model_dir / "test_wavs/keywords.txt")
        hits = recognize(spotter, audio)
        print(f"model_example_hits={hits}", flush=True)
        if not any("LIGHT_UP" in text for _, text in hits):
            raise RuntimeError("Python KWS path missed the model's reference keyword")
        return

    raw = bytearray()
    processed = bytearray()
    raw_levels: list[float] = []
    processed_levels: list[float] = []
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
        with AudioProcessor(args.apm_library) as processor:
            print("READY: say Nova three times, with short pauses", flush=True)
            while True:
                frame = capture.stdout.read(BYTES_PER_FRAME)
                if not frame:
                    break
                if len(frame) != BYTES_PER_FRAME:
                    raise RuntimeError("partial capture frame")
                adjusted = processor.capture(frame, 40)
                raw.extend(frame)
                processed.extend(adjusted)
                raw_levels.append(level(frame))
                processed_levels.append(level(adjusted))
        capture.wait(timeout=3)
        if capture.returncode != 0:
            raise RuntimeError(f"microphone capture failed ({capture.returncode})")
        print("CAPTURE_COMPLETE: offline checks running; no audio file was written", flush=True)
        print(f"raw_rms_peak={max(raw_levels, default=0):.4f}", flush=True)
        print(f"processed_rms_peak={max(processed_levels, default=0):.4f}", flush=True)
        print(f"raw_rms_median={statistics.median(raw_levels) if raw_levels else 0:.4f}", flush=True)
        print(f"processed_rms_median={statistics.median(processed_levels) if processed_levels else 0:.4f}", flush=True)

        canonical = spotter_for(args.model_dir, args.model_dir / "keywords.txt")
        print(f"canonical_raw={recognize(canonical, raw)}", flush=True)
        print(f"canonical_processed={recognize(canonical, processed)}", flush=True)
        del canonical
        gc.collect()

        # Only the phoneme recipe is a short-lived tmpfs file. Audio remains
        # solely in the process's bytearrays and vanishes when it exits.
        with tempfile.NamedTemporaryFile(mode="w", dir="/dev/shm", prefix="nova-phones-",
                                         suffix=".txt", delete=False) as keywords:
            keywords.write(VARIANTS)
            variant_path = Path(keywords.name)
        try:
            variants = spotter_for(args.model_dir, variant_path)
            print(f"variants_raw={recognize(variants, raw)}", flush=True)
            print(f"variants_processed={recognize(variants, processed)}", flush=True)
            del variants
        finally:
            variant_path.unlink(missing_ok=True)
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
