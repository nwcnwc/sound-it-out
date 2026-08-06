# Sound It Out

A fully offline desktop app (macOS, Windows, Linux) that produces looping, TV-friendly
phonics videos: a letter, blend, or word on screen, sounded out with a highlight moving
across the letters, then spoken in a warm human voice.

Built for an early reader with Down syndrome, to play continuously on a large-screen TV
at home. No internet, no accounts, no subscriptions, no ads.

---

## Two modes

### 1. Learn mode (primary)

A scaffolded progression of **8 levels**. Each is mastered before the next is introduced.

> **Important: sight words come first, not phonics.** This reverses the obvious ordering,
> and the reason is specific to Down syndrome. Children with DS are typically strong visual
> learners with a specific weakness in phonological awareness, so starting with phonics
> starts on their hardest ground. [Down Syndrome Education International](https://www.down-syndrome.org/en-us/library/research-practice/01/1/teaching-down-syndrome-read/)
> recommends a sight vocabulary of **~50 confident words** before phonics is introduced at
> all — and recommends those first words be **personally meaningful**. Reading then builds
> the phonological awareness that phonics needs, rather than requiring it up front.
>
> This is why Level 1 is Paw Patrol: not decoration, but exactly the recommended starting
> point for this particular child.

| Level | Content | Examples |
|---|---|---|
| 1 | Personally meaningful sight words | `Chase`, `Marshall`, `Skye`, `Rubble`, `Rocky` |
| 2 | Sight vocabulary to ~50 words + first phrases | family names, `Mum`, `dog`, `I like…` |
| 3 | Single grapheme → its sound | `s` → /s/, `a` → /æ/, `t` → /t/ |
| 4 | Two-unit blends (CV, VC) | `sa`, `at`, `ip`, `um` |
| 5 | Three-unit blends (CVC) | `sat`, `pin` (real) · `vam`, `zib` (nonsense) |
| 6 | Digraphs as single units | `sh`, `ch`, `th`, `ck` → `ship`, `chat`, `duck` |
| 7 | Consonant clusters | `st`, `bl`, `-nd`, `-mp` → `stop`, `black`, `hand` |
| 8 | Whole words → sentences | the 10k dictionary, then connected text |

Levels 3–8 are synthetic phonics, where items **do not need to be real words** — nonsense
items are used deliberately (see [Why nonsense words](#why-nonsense-words)).

Eight levels is not arbitrary: it maps onto [See and Learn Language and Reading](https://www.seeandlearn.org/en-gb/language-and-reading/)
(7 steps, DS-specific) for the sight-word stages and *Letters and Sounds* (6 phases) for the
phonics stages, with the overlap merged.

**Themes are a skin, not a level.** Paw Patrol styling can decorate any level; the *words* at
each level are set by decoding difficulty. This matters because character names are mostly
undecodable early — `Chase` needs a `ch` digraph and a split digraph, which is Level 6 work.
As a *sight* word at Level 1 it is perfect; as a *phonics* word it is far too hard. Coupling
theme to level would force one of those two things to break.

**From Level 3, letters are introduced in phonics order, not alphabetical order:**
`s a t p i n` → `m d g o c k` → `ck e u r` → `h b f l` → the rest.
This is the standard synthetic-phonics sequence, and the reason for it is motivational:
after just the first six letters he can already decode *sat, pin, tap, nap, pit, tin, sit,
tip*. Alphabetical order makes you wait until `t` before any word is possible.

### 2. Paste mode (advanced)

Paste any text — a favourite book, a birthday card, a list of family names. Each word is
sounded out and blended, and at the end of each sentence the whole sentence is displayed
and read aloud with each word highlighted in time.

---

## Why nonsense words

Real words can be memorized as shapes. Nonsense words cannot — `vum` can only be read by
actually decoding it. This is why they are used in formal phonics assessment (the UK
phonics screening check calls them "alien words"). They also massively expand the practice
space at each level: there are only so many real CVC words, but thousands of decodable CVC
strings.

They are presented as their own thing, never mixed in as if they were real words.

## Why this shape

**Synthetic phonics** — segment, then blend — has the strongest evidence base for early
readers, including readers with Down syndrome. The design leans on known strengths (strong
visual learning, learning through repetition) and reduces known difficulties (working-memory
load, auditory discrimination) by keeping one item on screen at a time, pairing every sound
with a visible letter, and repeating patiently without ever requiring a response.

## Delivery

- **Fullscreen playback** — computer connected to the TV over HDMI. Generate and play
  immediately; easy to change the text on the fly.
- **Export MP4** — render a long looping `.mp4` (e.g. 20 minutes), copy it to a USB stick,
  plug it into the TV. No computer at the TV at all. This is the low-friction path for
  everyday use.

---

## Technical design

### The pre-generated clip library

**Everything below the sentence level ships pre-rendered in the installer.** The end user's
machine never runs a text-to-speech model for letters, blends, or dictionary words — it just
plays and assembles audio clips. This is the central architectural decision: it makes
playback instant, output deterministic, and quality something we control and QC once rather
than something that varies per machine.

Approximate library size:

| Tier | Count |
|---|---|
| Grapheme sounds (incl. digraphs, multi-sound letters) | ~60 |
| Two-unit blends | ~400 |
| CVC strings (real + nonsense) | ~3,500 |
| Cluster words (curated) | ~2,000 |
| Dictionary words | ~10,000 |
| **Total** | **~16,000 clips** |

At Kokoro's CPU throughput this is well under an hour to generate as a one-time build step.
Stored as Opus at ~48kbps, the whole library is roughly **80MB** — small enough to ship.

Only **novel sentences** are synthesized on the user's machine, which is what keeps prosody
natural. (Sentences assembled from concatenated word clips sound robotic; sentences must be
generated whole.)

### Voice

**[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** (Apache-2.0) — 82M parameters,
~330MB, CPU-only, genuinely human rather than robotic. Bundled as ONNX so there is no Python
ML stack to install. Used at build time for the clip library, and at runtime for sentences.

### Critical audio requirement: no schwa

Sounds must be pure. `t` is /t/, **not** "tuh". `c` is /k/, **not** "cuh".

This matters more than it sounds: "cuh-a-tuh" does not blend into "cat", and schwa-polluted
consonants are the single most common reason home phonics attempts fail. Stop consonants
(b, d, g, k, p, t) inherently carry a release burst, so their clips must be trimmed to the
shortest intelligible form.

**Every Level 1 clip is ear-checked by hand before shipping.** ~60 clips; worth the hour.

### Nonsense-word synthesis

TTS driven by spelling will mispronounce or mangle strings like `vum` or `zib`. So nonsense
items are synthesized from **explicit IPA phonemes** rather than orthography — Kokoro is a
phoneme-driven model and accepts phoneme input directly, bypassing its g2p front-end. This
gives exact control over what each nonsense string sounds like.

*Verify early:* confirm phoneme-input works end-to-end before committing to this path. It is
the main technical risk in the pipeline.

### Letter-to-sound alignment

To highlight `ch` in *chair* as one unit, the app needs to know which **letters** produce
which **sound**. In Learn mode this is trivial — the curriculum is built from known units.
For Paste mode's arbitrary text, three tiers falling back in order:

1. **The 10k dictionary**, with hand-checked grapheme-phoneme alignment.
2. **Syllable chunking** via hyphenation dictionaries (Hunspell/`pyphen`) — universal,
   robust, still pedagogically sound.
3. **Letter by letter** — last resort for names and unusual words.

### Rendering

- Highlight is a colour/weight change on the active letter group — not a moving bar — so
  the whole item stays readable throughout.
- Video assembled with a bundled **ffmpeg**, encoded for TV built-in players (H.264 High
  profile, AAC audio, `.mp4`). Static text compresses extremely well; a 20-minute 1080p
  export lands around 100–200MB.

### Cross-platform packaging

One codebase, three installers. A webview-based shell (Tauri or Electron) — text layout and
letter highlighting are exactly what HTML/CSS is good at. Everything vendored: voice model,
clip library, hyphenation dictionaries, ffmpeg. No network calls, ever.

**Open issue — macOS code signing.** An unsigned Mac app is blocked by Gatekeeper and
requires a right-click→Open workaround that is not reasonable to ask of a non-technical user.
Proper notarization needs an Apple Developer account ($99/yr). Decision pending.

---

## Settings

Kept deliberately few, all on one screen:

| Setting | Default |
|---|---|
| Level | Learn mode: current level |
| Repetitions per item | 3 |
| Pause between items | 1.5s |
| Include nonsense words | On (levels 2–5) |
| Read whole sentence at end | On |
| Text size | Extra large |
| Colour theme | High contrast |
| Voice | Kokoro (female, warm) |

## Samples

`./setup.sh` then `.venv/bin/python -m gen.make_samples` regenerates everything in
`samples/`. These are produced by the real pipeline, not mocked up.

| File | What it shows |
|---|---|
| `01-pawpatrol-night.mp4` | Level 1 sight words — navy/cream theme |
| `02-pawpatrol-paper.mp4` | same content — book-page theme |
| `03-pawpatrol-contrast.mp4` | same content — maximum-contrast theme |
| `04-sounding-out.mp4` | Level 5 preview — per-letter highlight and blend |
| `05-sentence.mp4` | Level 8 preview — word-by-word, then whole sentence |
| `phoneme-check/all-sounds.wav` | **needs an ear check** — see below |

Font is **Andika** (SIL, OFL) — designed for literacy learners, with the single-story `a`
and `g` that beginning readers are taught, rather than the two-story forms in most fonts.

## Known issue: schwa on isolated consonants

Kokoro appends a schwa to isolated consonants — asked for /s/ it produces "sss-uh", asked
for /t/, "tuh". Measured on `af_heart`, the tail is unambiguous: spectral centroid collapses
from ~7000 Hz to ~1400 Hz while RMS *rises*. That is a vowel.

This is not cosmetic. "cuh-a-tuh" does not blend into "cat", and schwa-polluted consonants
are the most common reason home phonics stalls.

`trim_schwa()` in `gen/soundout.py` strips it: cut leading silence, find the burst/frication
by spectral centroid, cut where the centroid falls back into vowel territory, with a hard
duration cap as backstop (the centroid test alone missed /k/, /f/ and /g/). Results now sit
at 75–150 ms for stops, ~180 ms for fricatives, vowels untouched — physiologically plausible.

**Still unverified by ear.** Duration and spectrum are proxies; whether a clip *sounds* like
"t" or "tuh" is a perceptual judgement. Every Level 3 clip needs a human listen before it
ships. `samples/phoneme-check/all-sounds.wav` is that check.

## Status

Pipeline working end to end: Kokoro → storyboard → headless Chrome → ffmpeg.
Sample videos generated. App shell not started.

## License

TBD.
