# Nova microWakeWord prototype (not selected)

The existing sherpa-onnx candidate recognized zero of nine real German
"Nova" calls, including continuous decoding without an energy gate. It remains
unselected. This prototype uses the same 10-ms, 16-kHz mono PCM interface but
does not modify the running service or the server-side Meeting engine.

## Candidate and data

- Train a custom **German** `Nova` microWakeWord v2 model off-device. The
  upstream basic notebook uses an English synthetic voice and explicitly warns
  that its first model is unlikely to be production-quality. Do not publish its
  English result as a German Nova model.
- The server Voice Designer can generate small, varied German positive and
  independent evaluation sets using distinct voice descriptions and seeds. Its
  existing web API permits at most six variants per job, one running job, and
  eight queued jobs. It is not a bulk-data training API. Do not alter that
  production service simply to make this experiment convenient.
- More diverse German voices from the Piper sample generator can supply bulk
  synthetic positives. Check each voice's license and keep the source/seed
  provenance. Do not train and evaluate on the same voice or noise clips.
- Include near misses such as "Nora", "Noah", "noch mal", TV speech and the
  assistant's own TTS; include household noise and real-room acoustics as
  negatives. The previous consented real-voice calibration kept PCM in RAM and
  deleted it. New retained human recordings require separate consent.
- Keep training WAVs, model weights, manifests and measurements outside Git.
  A generated model may have dataset-specific redistribution limits.

## Reproducible baseline (experimental)

`tools/generate_nova_piper.py` creates German positive and near-miss WAVs with
two independently licensed Piper voices, recording model hashes and synthesis
settings in an output manifest. The first isolated set has 500 `Nova` clips
and 240 near misses; `tools/audit_wake_wavs.py` checks PCM, levels, clipping,
duplicates and source hashes. Both Piper voices used for this experiment have
CC0 source datasets according to their model cards. The Voice Designer clips
are **held out** and not mixed into training.

`tools/prepare_nova_micro_features.py` verifies the input manifest, builds
separate positive/negative feature sets, and creates a bounded CPU-baseline
configuration. `tools/fork_nova_training_config.py` gives retries a new model
directory without overwriting a partial run. This is intentionally not a
complete background-audio dataset: synthetic near misses cannot establish a
real-world false-activation rate. A trained baseline must remain unselected
until independent voices, room noise, playback echo and actual Pi CPU/RAM
measurements pass. The model is never included in a source release by default.

The first CPU-trained baseline (1,500 steps) is **not usable**: at a 0.5
threshold it detected only 17/26 held-out Voice Designer `Nova` clips and
fired on 110/240 Piper near misses. Raising the threshold to 0.9 reduced the
near-miss hits to 21/240 but also reduced recall to 11/26. These clips are
synthetic, so neither figure predicts a real-room false-activation rate. The
running Pi still uses its previous mode; no custom model was selected.

A second, still isolated experiment mixed *new* Voice Designer training clips
into an immutable dataset via `tools/assemble_nova_training_dataset.py`. The
original 26 evaluation clips remained held out. The negative class weight is
configurable in `tools/prepare_nova_micro_features.py` so that controlled
variants can be compared against the same evaluation set.

That follow-up has now been measured. Raising the negative class weight from
5 to 10 **without changing the baseline data** made false activations worse.
The Voice Designer supplied 36 new positive clips and 12 `Nora`/`Noah` clips;
nine positive clips failed the short-word duration/silence screen. The new
training set therefore contained 527 positives and 252 negatives, with no
SHA-256 overlap against the 26 held-out positives. At a 0.5 threshold, the
new model detected 26/26 held-out `Nova` clips but also fired on **240/240**
Piper near misses. Even at 0.97 it fired on 225/240 near misses while missing
five `Nova` clips. It too is **rejected and unselected**. The likely missing
piece is a much broader, independently licensed negative set of ordinary
speech and ambient audio, plus real-speaker evaluation. The microWakeWord
[microWakeWord](https://github.com/OHF-Voice/micro-wake-word) itself describes
separate ambient negative validation/test sets and warns that its basic
training example is unlikely to produce a usable model.

## Isolated measurements

`pymicro-wakeword` and the native feature library are optional dependencies
for this experiment. After obtaining a custom `nova.json`/`nova.tflite` pair,
run from a Linux Python environment with this package installed:

```text
PYTHONPATH=src python3 tools/bench_micro_wake.py --manifest /private/nova/nova.json --seconds 120
PYTHONPATH=src python3 tools/bench_micro_wake.py --manifest /private/nova/nova.json --wav /private/validation/held-out.wav
```

The benchmark never opens the microphone or sends audio to OpenClaw. It reports
load time, CPU seconds per audio second, peak RSS and hit times, not the WAV
content. Keep the level gate disabled for the first recognition test. Only
consider the gate afterward, if it preserves quiet and noisy wake recall.

Acceptance needs real Pi tests with multiple speakers/distances and playback
echo, plus hours of representative negative audio. Measure false rejects,
false activations per hour, end-to-end wake latency, CPU/RAM alongside the
already running assistant, and the six-second wake conversation timeout.
Compare raw capture with local APM output. A model trained only on synthetic
voices is a candidate, not proof of recognition of the owner's voice.
