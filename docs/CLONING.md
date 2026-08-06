# Voice cloning (optional)

Levels 6–8 — the 10,000-word dictionary and arbitrary sentences — are spoken in a
**cloned** version of the parent's voice. Levels 1–5 are her actual recordings played
back verbatim and have nothing to do with any of this.

**The app ships without this module and is fully functional without it.** `gen/clone.py`
imports with no ML stack present, reports what is missing, and lets the UI grey out
levels 6–8 with a sentence a parent can read. Nothing here is required to install, open
or use the app.

---

## Consent

This models a real person's voice. Read this bit even if you skip the rest.

- The recordings are **hers**. The passage recording, the 20-second excerpt cut from it,
  and the speaker profile derived from it are her property, not the project's.
- Everything happens **on her machine**. No audio is uploaded; the only network access is
  the one-off model download from Hugging Face, and after that the module works offline.
- **Nothing is shipped or shared without her explicit say-so.** Not the recordings, not
  `profile.pt`, not generated audio, not "just for the demo". A speaker profile is a
  usable copy of her voice; treat it like a house key.
- `uninstall(keep_profiles=False)` deletes it all. Profiles are kept by default precisely
  so that deleting them is a decision she makes, not a side effect of clearing a cache.
- Every clip Chatterbox generates carries Resemble's imperceptible **Perth watermark**.
  That is a feature here: audio made from her voice is identifiable as synthetic.

---

## What the clone will and will not sound like

Honest expectations, so the first listen is not a disappointment.

**It will get:** her timbre — the basic colour of the voice; her accent; her general
speaking rate; the broad shape of her intonation on ordinary declarative sentences. On a
plain sentence like *"Chase is on the case."* a listener who knows her should recognise
her.

**It will not get:** her. Specifically —

- **Her warmth on the sentences that matter.** The way she reads to *him* — slower, more
  sing-song, the small emphases she puts on his name — is a performance for one person.
  The clone reads like a competent narrator, not like his mother.
- **Rare words and names.** Anything outside ordinary English — invented Paw Patrol
  spellings, unusual family names — will be pronounced by rule and sometimes wrongly.
- **Isolated words and single sounds.** A clone conditioned on connected speech and then
  asked for one word out of context tends to sound clipped or oddly stressed. This is a
  large part of why the design keeps levels 1–5 on her real recordings — the levels made
  of single words are exactly the levels a cloner is worst at.
- **Consistency.** Chatterbox samples: the same sentence generated twice differs. Generated
  clips are cached on disk, so each sentence is fixed the first time it is made and stays
  that way — but two sentences sharing a word will not share that word's delivery.

The design already assumes this. Cloning fills content Alex will not reach for months;
if it disappoints, it degrades material he is not using yet.

### Why the reference must be connected speech

The passage in [`PASSAGE.md`](../PASSAGE.md) is 716 words of ordinary prose, verified by
`gen/check_passage.py` to contain all 43 English phonemes.

A list of isolated words would cover the same phonemes and still be near-useless, because
the model is not learning a sound inventory. It is learning **prosody** — rhythm, the
melody of a rising question, how long she holds a stressed vowel, where she breathes.
None of that exists inside a single word said on its own; the information is in the
*joins*. Feed it isolated words and you get a voice with her timbre and nobody's rhythm:
a robot wearing her voice.

### Why the passage is six minutes when the model reads fifteen seconds

Chatterbox is zero-shot. It conditions on the **first** slice of the reference and
discards the rest:

| Variant | Vocoder reference | Token prompt |
|---|---|---|
| `english` | first 10 s | first 6 s |
| `nano` | first 10 s | first 15 s |

So six minutes is not six minutes of training data. It is a six-minute pool to choose
twenty clean seconds from — and choosing deliberately matters more than length, because
whatever happens to be at the front of the file *is* the voice. `_best_window()` in
`gen/clone.py` scores 20-second windows on how much of them is continuous speech,
penalises clipping hard, and starts the excerpt on a speech onset, so the clone is not
built from throat-clearing and the microphone being adjusted.

The excerpt is written to `reference.wav` inside the profile, so a profile can be rebuilt
if the model is ever upgraded — and so there is one obvious file to delete.

---

## Install

```python
from gen import clone

clone.capabilities()            # what the UI asks; never raises
clone.is_available()            # engine ready?
clone.install(print_progress)   # ~3.2 GB, resumable, safe to re-run
clone.uninstall()               # keeps her profiles unless told otherwise
```

`install(progress_cb)` calls `progress_cb(fraction, message)` with a 0.0–1.0 fraction and
a line fit to show a user. It **checks free disk space before writing anything** and
refuses with a plain-English message if there is not enough. It resumes: every file is
fetched with an HTTP range request against a `.part` file, so an interrupted 2 GB download
picks up where it stopped, and a truncated file is caught at download time rather than
surfacing as an incomprehensible error while loading weights.

### Measured sizes

Exact Hugging Face blob sums, measured 2026-08-06.

| What | Size |
|---|---|
| `english` weights (5 files, default) | **3.19 GB** (2.97 GiB) |
| `nano` weights (9 files) | **1.94 GB** (1.81 GiB) |
| PyTorch 2.6.0 CPU wheel, cp311 linux | 179 MB |
| *PyTorch 2.6.0 from PyPI's default index* | *767 MB + 13 CUDA packages, ~2.5 GB* |
| Rest of the Python stack (transformers, diffusers, librosa, gradio…) | **estimated ~2 GB — not measured** |
| **Total, first install** | **~5.5–6 GB** |

Two things follow from that table:

1. **Torch must come from the CPU index.** `install()` runs
   `pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu` *first*, so
   that `chatterbox-tts`'s `torch==2.6.0` pin is already satisfied and pip does not go and
   fetch 2.5 GB of CUDA libraries that no target laptop can use. (`2.6.0+cpu` satisfies
   `==2.6.0` under PEP 440.)
2. **10 GB free is enough, but not by a lot.** Check before, not after.

### Why a separate virtualenv

`install()` builds a sidecar environment at `.venv-clone/`, and the model runs in a child
interpreter that talks JSON over a pipe.

This is not fastidiousness. `chatterbox-tts` pins **`numpy<2.0.0`** on Python < 3.13, and
this project's environment runs numpy 2.4 under `kokoro-onnx` and `soundfile`. Installing
the cloning stack into `.venv` would silently downgrade numpy underneath the working
pipeline. The sidecar keeps the app's dependency set at exactly `kokoro-onnx`, `soundfile`
and `numpy`, which is also what makes "optional" true rather than aspirational.

The child process is **persistent**: loading the weights takes tens of seconds, and the
dictionary tier is thousands of items, so a process per call would spend all its time in
`torch.load`. It also means an out-of-memory kill in a 3 GB model takes down a subprocess
rather than the app.

---

## CPU-only performance

The target machines are ordinary laptops with no GPU. This is the module's real cost.

| Variant | Speed | Source |
|---|---|---|
| `english` (0.5B) | ~90 s for a short phrase; ~5 min for a paragraph | third-party report, **not measured here** |
| `nano` (110M) | ~3× faster than realtime on 8 CPU threads | Resemble's own figure, **not measured here** |

`english` on CPU is roughly 10–30× slower than realtime. That is tolerable *because of how
it is used*: sentences are generated once, cached on disk by content hash, and the
dictionary tier is a one-off build step, not something the child waits on. It is not
tolerable for Paste mode with a fresh paragraph — expect a visible wait there, and put a
progress indicator on it.

`nano` is the variant that makes this comfortable, at some cost in richness. Its loader
landed **after** the pinned 0.1.7 release, so `install(variant="nano")` refuses with a
clear message until the released package catches up; `capabilities()` will report which
variant is in use.

A GPU is used automatically if one is present (`cuda`, then Apple `mps`), but nothing
assumes one.

---

## Cloning and speaking

```python
from gen.clone import clone_voice, ClonedVoice

clone_voice("recordings/passage.wav", "models/voices/mum")   # once
v = ClonedVoice("models/voices/mum")
audio = v.say("Chase is on the case.")                        # float32, 24000 Hz
```

`ClonedVoice.say(text, speed=None)` is deliberately the same shape as `Voice.say()` in
`gen/soundout.py` — text in, mono float32 at `SR` out, cached on disk by content hash — so
the storyboard code does not care which one it is holding. `synthesize(text, profile)` is
the same thing without the caching layer.

Two differences, both intentional:

- **`phonemes=True` raises.** Chatterbox is grapheme-driven and has no IPA back door.
  Levels 3–5 use her recorded phonemes, so this should never be reached; it raises rather
  than silently spelling out `æ`.
- **`speed` is applied afterwards** with the same rubberband stretch `slower()` uses,
  because the model has no speed control of its own.

Chatterbox's output sample rate (`S3GEN_SR`) is **24000 Hz**, which is already `SR` in
`gen/soundout.py`. The worker asserts it rather than trusting it.

A profile directory contains:

| File | What |
|---|---|
| `profile.pt` | the conditioning tensors — **this is the voice** |
| `reference.wav` | the 20 s excerpt it was built from |
| `profile.json` | plain-text provenance: date, source filename, excerpt offset, versions |

---

## Licensing

Checked, because the licence is the reason this model was chosen over the more popular one.

| | |
|---|---|
| Package | `chatterbox-tts` **0.1.7** (PyPI, released 2026-03-26, Python ≥ 3.10) |
| Code licence | **MIT** — "Copyright (c) 2025 Resemble AI" |
| Weights licence | **MIT** — `ResembleAI/chatterbox`, `-nano` and `-turbo` all carry `license: mit` on Hugging Face |
| Dependencies | torch/torchaudio (BSD), transformers & diffusers (Apache-2.0), librosa (ISC), `resemble-perth` (MIT), `conformer` (MIT), `s3tokenizer` (Apache-2.0) |

The trap this avoids: **XTTS-v2**, the most widely deployed open voice cloner, ships MIT-ish
code with weights under the Coqui Public Model Licence, which forbids commercial use. MIT
code alone is not enough — the weights carry their own licence, and here both are MIT.

If Chatterbox ever becomes unusable, the replacement must be checked the same way, on both
halves. Permissively-licensed alternatives worth looking at first: **Kokoro-82M**
(Apache-2.0, already bundled, but *not* a voice cloner — it has fixed voices) and
**Piper** (MIT, requires fine-tuning on ~30 minutes of audio rather than zero-shot cloning).

---

## Known risks

- **The install path is unverified.** The multi-gigabyte stack was deliberately not
  installed on the development machine (9.5 GB free). The download, resume, truncation
  check and disk precheck are tested against the real Hugging Face endpoint; the pip step,
  the model load, `clone_voice()` and `synthesize()` are written against the 0.1.7 source
  and have not been executed. Expect to shake bugs out of the first real install.
- **`~2 GB` for the Python stack is an estimate.** Measure it on the first real install and
  correct `STACK_BYTES` in `gen/clone.py` and the table above.
- **`pip install chatterbox-tts` has a history of failing** on its Chinese-segmentation
  dependency (`pkuseg`, now `spacy-pkuseg`) on some platforms. If the install step fails,
  that is the first thing to look at.
- **Quality is unheard.** Everything above about how the clone will sound is reasoning from
  the model's design, not a listen. Before levels 6–8 are enabled for real, generate a
  dozen sentences and have *her* listen to them. She is the only person who can say whether
  it is close enough, and she gets a veto.
