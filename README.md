# Sound It Out

A fully offline desktop app (macOS, Windows, Linux) that produces looping, TV-friendly
phonics videos: a letter, blend, or word on screen, sounded out with a highlight moving
across the letters, then spoken in a warm human voice.

Built for early readers with Down syndrome, to play continuously on a large-screen TV. No internet, no accounts, no subscriptions, no ads.

**[Installing it](INSTALL.md)** — no GitHub account needed, just a browser.

---

## Glossary

Standard phonics vocabulary is used wherever a standard term exists, and where one
doesn't the invented name says what the thing is rather than borrowing a word that
already means something else. These meanings hold in the code, the comments and the
UI alike.

### Standard terms

| term | what it means | examples |
|---|---|---|
| **phoneme** | one distinct **sound**. Spoken, never written. | `/k/` `/æ/` `/t/` `/ʃ/` |
| **grapheme** | the letter *or letters* spelling **exactly one** phoneme. Written, never spoken. | `c` `a` `t` `sh` `ck` `igh` |
| **digraph** | a two-letter grapheme — two letters, **one** sound | `sh` `ch` `th` `ck` `ng` `ai` |
| **trigraph** | a three-letter grapheme | `igh` `tch` `air` |
| **blend** (cluster) | adjacent consonants that each keep their **own** sound — *not* a digraph | `st` in stop = `/s/`+`/t/` |
| **onset** | the consonant(s) before the vowel of a syllable | `c` in cat, `str` in strap |
| **rime** | the vowel and everything after it, in a syllable | `at` in cat, `ap` in strap |
| **magic e** (split digraph) | vowel–consonant–`e`, where the `e` makes the vowel say its name | `a_e` in cake, `i_e` in like |
| **continuant** | a sound that can be held for as long as your breath lasts | `/s/` `/m/` `/f/`, every vowel |
| **stop** | a sound that is a burst and cannot be held at all | `/p/` `/t/` `/k/` `/b/` `/d/` `/ɡ/` |
| **CVC** | a consonant–vowel–consonant word shape | cat, sun, big |

The pair most often confused is **digraph vs blend**. `sh` is one sound spelled with
two letters, so it is one grapheme. `st` is two sounds spelled with two letters, so it
is two graphemes standing next to each other. The app must never split a digraph and
must always split a blend.

### Terms this codebase invents

**Alignment unit** — some letters plus the sound they make, as one row of a word's
entry in the dictionary. Every unit is either a grapheme (one phoneme) or a grapheme
pair (two). "Unit" is the umbrella word when it doesn't matter which.

**Grapheme pair** — an alignment unit carrying **two** phonemes: `at` = /æt/,
`ca` = /kæ/, `ing` = /ɪŋ/.

Phonics has no name for this, because it is not a unit anyone teaches. Depending on
the word, one may happen to land on a rime (`at` in cat), on an onset plus its vowel
(`ca` in cat), or on a blend (`st` in stop). They exist for exactly one reason: a
recording of /kæ/ is a **single human breath**, where /k/ + /æ/ is two clips with a
seam between them. They are an audio-smoothness device, not curriculum.

Every one of them is exactly two *adjacent graphemes merged*, which is where the name
comes from.

### One word, every term

```
cat            c    =  /k/     grapheme  (onset)
               a    =  /æ/     grapheme  (the rime's vowel)
               t    =  /t/     grapheme  (the rime's coda)

               at   =  /æt/    grapheme pair — and here also the rime
               ca   =  /kæ/    grapheme pair — and here nothing at all
```

### Where each lives

| term | in the code | count |
|---|---|---|
| phoneme | `recordings.PHONEME_ROWS` | 42 |
| grapheme (single letter) | `levels.SINGLE_LETTER_GRAPHEMES` | 26 |
| grapheme (multi-letter) | `levels.MULTI_LETTER_GRAPHEMES` | 39 |
| magic e | `starter.all_magic_e()` | 65 |
| grapheme pair | `dictionary.pair_catalog()` | 398 |
| a word's alignment | `dictionary.alignment()`, `levels.word_alignment()` | — |
| continuant / stop | `recordings.CONTINUANT`, `recordings.STOP`, `phoneme_class()` | — |

Recording parts are named for what they hold: `phonemes`, `magic-e`, `pairs`, `words`,
`sentences`.

### Renamed, if you are reading old commits

Two words used to mean something here that they do not mean in phonics, which made a
real bug hard to see:

- **"chunk"** meant both *any* alignment unit and, elsewhere, specifically the
  two-phoneme ones. Now: **unit** for the umbrella, **grapheme pair** for the
  two-phoneme kind.
- **"rime"** was used only for the magic-e set (`ake`, `ice`, `ome`), which is far
  narrower than the standard meaning. Now: **magic e** for those, and **rime** kept
  for its real meaning.

---

## The shape of the app (0.4.0)

The UI is two screens:

- **Sentences** — one list holding everything that gets read: single letters,
  single words, whole sentences. Add anything, record it in a short
  walk-through (each word once, then the line - already-recorded words are
  skipped), tick what to include, pick length/look/pace, make the video.
  Every video is the same journey: sounds close into words pass by pass,
  words grow into sentences, ending in the parent's own read with the
  highlight following her voice.
- **Setup** — the one recording session that matters (the 42 sounds; a
  shipped human starter voice fills in until then), the optional voice pack +
  reading passage for stories, where videos go, and backup.

The curriculum below survives as **starter packs** - one tap adds a level's
content to the list as ordinary entries - and as the pipeline's internal
generators. The research ordering did not change; only where it lives.

## The curriculum (now starter packs)

### 1. Learn mode (primary)

A scaffolded progression of **9 levels**. Each is mastered before the next is introduced.

> **Important: sight words come first, not phonics.** This reverses the obvious ordering,
> and the reason is specific to Down syndrome. Children with DS are typically strong visual
> learners with a specific weakness in phonological awareness, so starting with phonics
> starts on their hardest ground. [Down Syndrome Education International](https://www.down-syndrome.org/en-us/library/research-practice/01/1/teaching-down-syndrome-read/)
> recommends a sight vocabulary of **~50 confident words** before phonics is introduced at
> all — and recommends those first words be **personally meaningful**. Reading then builds
> the phonological awareness that phonics needs, rather than requiring it up front.
>
> This is why the shipped Level 1 is a favourite TV show: not decoration, but exactly the
> recommended starting point.

| Level | Content | Examples |
|---|---|---|
| 1 | Personally meaningful sight words | `Chase`, `Marshall`, `Skye`, `Rubble`, `Rocky` |
| 2 | Sight vocabulary to ~50 words + first phrases | family names, `Mum`, `dog`, `I like…` |
| 3 | Single grapheme → its sound | `s` → /s/, `a` → /æ/, `t` → /t/ |
| 4 | Two-unit blends (CV, VC) | `sa`, `at`, `ip`, `um` |
| 5 | Three-unit blends (CVC) | `sat`, `pin` (real) · `vam`, `zib` (nonsense) |
| 6 | **Building up** — the whole arc in one video | `s` → `sa` → `sat` → *Sam sat on a mat.* |
| 7 | Digraphs as single units | `sh`, `ch`, `th`, `ck` → `ship`, `chat`, `duck` |
| 8 | Consonant clusters | `st`, `bl`, `-nd`, `-mp` → `stop`, `black`, `hand` |
| 9 | Whole words → sentences | the 10k dictionary, then connected text |

**Level 6 is the join.** Letters grow into words and words grow into a sentence in one
continuous video, with each newly added letter highlighted. Separate levels teach letters
and words as different things; this one shows the first becoming the second. Four chapters,
each introducing new letters and ending on a sentence built only from letters already
taught — a check that runs at import refuses to start if that rule is ever broken.

Levels 3–9 are synthetic phonics, where items **do not need to be real words** — nonsense
items are used deliberately (see [Why nonsense words](#why-nonsense-words)).

The level count is not arbitrary: it maps onto [See and Learn Language and Reading](https://www.seeandlearn.org/en-gb/language-and-reading/)
(7 steps, DS-specific) for the sight-word stages and *Letters and Sounds* (6 phases) for the
phonics stages, with the overlap merged.

**Themes are a skin, not a level.** Paw Patrol styling can decorate any level; the *words* at
each level are set by decoding difficulty. This matters because character names are mostly
undecodable early — `Chase` needs a `ch` digraph and a split digraph, which is Level 7 work.
As a *sight* word at Level 1 it is perfect; as a *phonics* word it is far too hard. Coupling
theme to level would force one of those two things to break.

**From Level 3, letters are introduced in phonics order, not alphabetical order:**
`s a t p i n` → `m d g o c k` → `ck e u r` → `h b f l` → the rest.
This is the standard synthetic-phonics sequence, and the reason for it is motivational:
after just the first six letters a child can already decode *sat, pin, tap, nap, pit, tin, sit,
tip*. Alphabetical order makes you wait until `t` before any word is possible.

### 2. Paste mode (advanced)

Paste any text — a favourite book, a birthday card, a list of family names. Each word is
sounded out and blended, and at the end of each sentence the whole sentence is displayed
and read aloud with each word highlighted in time.

### 3. The sentence library

The simplified flow the app is growing toward: the parent adds any sentence, records it
in a short walk-through — each word once, then the whole line — and it becomes a video
that travels the entire arc: sounds build into words (with the gaps closing pass by
pass), words build into the sentence, and it ends with the parent's own read of the
line, each word highlighted in time with their voice.

Words are saved to the shared word bank, so every sentence gets cheaper to record than
the last. The read-along timing needs no aligner: the isolated word clips give each
word's relative length (same speaker, same words), the line recording gives the total,
and the word boundaries are the cumulative product of the two — with grammar words
discounted, because "the" said alone is a full syllable and "the" mid-sentence is not.

Words the grapheme table would sound out *wrong* — `said`, `one`, irregular names — are
shown and spoken whole instead, the way the sight-word levels treat every word: a wrong
buildup teaches worse than none.

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

### Voice: the parent's, two ways

The voice is a parent's, sourced two different ways depending on the level. This is
the central decision, and it puts the quality risk where it does least harm.

| Levels | Content | Source |
|---|---|---|
| 1–2 | ~50 sight words | **recorded, used verbatim** |
| 3–6 | ~44 phoneme sounds | **recorded, used verbatim** |
| 7–9 | 10k dictionary, arbitrary sentences | **cloned from their voice** |

Levels 1–5 are where a new reader stays for a year or more, and every sound there is
genuinely theirs — nothing synthesised. Cloning only fills the long tail, which the child will
not reach for months, and which could never be recorded by hand anyway. If the clone
disappoints, it degrades content the child isn't using yet.

**Cloning model: [Chatterbox](https://www.resemble.ai/resources/best-open-source-ai-voice-cloning-tools)**
(Resemble AI, **MIT licensed**, zero-shot from a 5–20 s reference, runs offline).
MIT matters here — XTTS-v2 is the most widely deployed but is non-commercial licensed,
and this should stay unencumbered.

**The recording session must include connected speech.** Isolated words and phonemes
carry almost no prosody, and prosody is precisely what a cloner needs to learn. Five to
ten minutes of them reading ordinary prose aloud is the difference between the later
levels sounding like them and sounding like a robot wearing their voice. See
[RECORDING.md](RECORDING.md).

**Consent is not an afterthought.** This is a real person's voice being modelled. It is
their own child, their own recording, their own machine, and it never leaves the house — but
the recordings and the cloned model belong to them, and nothing here should ever be
shipped or shared without their say-so.

**Cost:** bundling a cloning model adds roughly 2–4 GB to the installer on top of the
~500 MB baseline. Worth it; worth knowing.

### Fallback voice

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

But cutting the schwa is only half the problem, and over-correcting for it breaks the other
half: **a sound that is merely short is useless for teaching.** Phonics instruction stretches
sounds out — "ssssss", "mmmmm" — so the child can hear each one and join them. A clipped
75 ms /t/ is technically schwa-free and pedagogically dead.

`shape_phoneme()` in `gen/soundout.py` does both: strip the schwa, then stretch what remains.

**Getting the length from the right place matters.** The first working version looped a ~100 ms
core with crossfades, which repeats the same waveform over and over — the ear hears that
periodicity as a hard robotic stutter. Two changes fixed it:

1. **Ask Kokoro for the length first.** Repeating the IPA symbol (`ssssss`) makes the model
   *hold* the sound instead of releasing it: /s/ goes from 298 ms to 640 ms, /m/ to 1024 ms.
   Vowels use the IPA length mark (`æː`). This is the "trick" — the model will sustain a
   phoneme if you ask it to, and it sounds natural because it *is* natural.
2. **Stretch the remainder with a phase vocoder**, not by splicing. ffmpeg's `rubberband`
   filter stretches continuously with formants preserved, so there is no repeating period to
   hear. `slower()` uses the same mechanism for whole sentences.

Together these drop the stretch factor from ~6.8× to near 1.0×, which is why the artefacts
disappear — most of the length is now real audio, not processing.

Stops are excluded from step 1: repeating a stop just gives "t-t-t".

| Class | Result |
|---|---|
| Fricatives `s f ʃ v z` | 680 ms sustained |
| Nasals / liquids `m n l r` | 680 ms sustained |
| Vowels | 800 ms sustained |
| **Stops `p t k b d g`** | **~150–200 ms — cannot be sustained** |

**Stops are a hard physical limit, not an engineering gap.** A stop consonant is defined by a
closure and a release with no sustainable phase in between — no human teacher can hold a /t/
either. Standard practice is to keep them crisp and teach continuants first, which is why the
`s a t p i n` order front-loads sounds that *can* be stretched.

**Still unverified by ear.** Duration and spectrum are proxies; whether a clip *sounds* like
"t" or "tuh" is a perceptual judgement. Every Level 3 clip needs a human listen before it
ships. `samples/phoneme-check/all-sounds.wav` is that check.

## Known open question: sentence line breaks

Sentences currently auto-fit to the largest size that fits, which puts "Chase is on the case."
on two lines at large type. One line at smaller type may be better for a beginning reader —
line returns add a tracking demand — but it trades away size on a TV viewed from a sofa.
Undecided; it is a one-line change in `_font_size` handling either way.

## How the app is put together

Generation is three phases, split along what each runtime is actually good at:

| # | Phase | Runs in | Does |
|---|---|---|---|
| 1 | `plan` | Python | synthesis, storyboard, timing, `audio.wav` + `frames.json` |
| 2 | `frames` | Electron | `frames.json` → PNGs, via this app's own Chromium |
| 3 | `encode` | Python | ffmpeg mux to `.mp4` |

Phase 2 lives in Electron deliberately. It means the packaged app has **no external
Chrome dependency**, and every install rasterises with the same bundled Chromium — so a
frame is pixel-identical on every machine. For an app whose entire job is
precisely-rendered letterforms, that is the point, and it is why Electron was chosen
over Tauri (which uses each OS's own webview, and would render differently per machine).

Electron talks to Python over JSON lines on stdio (`app/sidecar.js` ↔ `gen/service.py`).
In development that is the venv; once packaged it is a PyInstaller-frozen binary. Nothing
else in the app knows the difference.

```
app/main.js        orchestration, IPC, fullscreen player
app/frames.js      HTML -> PNG via capturePage
app/sidecar.js     spawns and talks to Python
app/renderer/      the UI
gen/service.py     JSON-lines sidecar - Electron's only way in
gen/paths.py       read-only RESOURCES vs writable per-user DATA
gen/levels.py      the curriculum
gen/voice.py       recordings -> clone -> built-in voice
gen/recordings.py  splits the recordings into clips, with QC
gen/clone.py       optional Chatterbox cloning
```

Run it in development with `npm start` (after `./setup.sh`).

## Status

**Working end to end**, verified by generating real videos through the service:
levels 1–5, all three themes, both playback and file export.

- Levels 1–5 implemented. 6–8 designed and specified but not built — they need the
  grapheme-phoneme alignment lexicon, not just more word lists, and the UI correctly
  reports them as unavailable rather than failing mid-generation.
- 51 tests passing (`.venv/bin/python -m pytest tests/ -q`).
- Voice cloning is genuinely optional: the app is fully usable for levels 1–5 with it
  absent, and never hard-imports torch.

**Not yet verified:**

- **The Electron frame renderer has never been run.** Chromium's multi-process model is
  blocked in the development container (`/dev/shm` access returns `ESRCH`; single-process
  mode aborts with `SIGTRAP`). The code is written and the HTML is identical to what the
  verified Chrome path renders, but phase 2 needs one run on a real desktop. The Chrome
  path (`render_job_chrome`) is verified and remains as the fallback.
- No build has been produced on any platform.
- Nothing has been heard by ear — every audio decision so far rests on measurement.

## License

TBD.
