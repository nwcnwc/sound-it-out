# Sound It Out

A fully offline Windows app that turns any pasted text into a looping, TV-friendly
reading video: one word at a time, sounded out with a highlight moving across the
letters, then read aloud in a warm human voice.

Built for an early reader with Down syndrome, to play continuously on a large-screen
TV at home. No internet, no accounts, no subscriptions, no ads.

---

## The idea

Paste in any text — a favourite book, a birthday card, a list of family names. The app
pre-generates all the audio (this may take a few minutes), then plays an endless loop:

1. **Show the word.** Large, high-contrast, centred on the screen.
2. **Sound it out.** The word is spoken in parts. As each part is sounded, the matching
   letters are highlighted — so the eye learns which letters make which sound.
3. **Blend it.** The whole word is read aloud at natural speed.
4. **Repeat.** Steps 2–3 repeat a configurable number of times (default 3).
5. **Next word.** Move on.
6. **End of sentence.** When the last word of a sentence finishes, the whole sentence is
   displayed and read aloud, with each word highlighted as it is spoken.

Then the loop starts over, forever.

## Why this shape

This is **synthetic phonics** — segment, then blend — which is the approach with the
strongest evidence base for early readers, including readers with Down syndrome.
The design leans on known strengths (strong visual learning, learning through repetition)
and avoids known difficulties (working-memory load, auditory discrimination) by keeping
one word on screen at a time, pairing every sound with a visible letter, and repeating
patiently without ever rushing or requiring a response.

## Delivery

Two ways to get it onto the TV, because both are useful:

- **Fullscreen playback** — PC connected to the TV over HDMI. Generate and play
  immediately; easy to change the text on the fly.
- **Export MP4** — generate a looping `.mp4`, copy it to a USB stick, plug it into the
  TV. No PC at the TV at all. This is the low-friction path for everyday use.

---

## Technical design

### Voice

**[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** (Apache-2.0) for word and
sentence reading. 82M parameters, ~330MB, runs on CPU at faster-than-realtime, and
sounds genuinely human rather than robotic. Bundled as ONNX so there is no Python ML
stack to install.

**Piper** is the fallback / low-spec option — smaller and faster, noticeably more
synthetic.

Generation is fully ahead-of-time, so quality is the only thing that matters; a few
minutes of up-front render is acceptable by design.

### The hard problem: letter-to-sound alignment

To highlight `ch` as a single unit in *chair*, the app needs to know which **letters**
produce which **sound** — grapheme-to-phoneme *alignment*. Standard TTS does not expose
this. Three tiers, falling back in order:

1. **Curated phonics lexicon.** A hand-checked alignment table for high-frequency words
   and common phonics patterns (digraphs `ch/sh/th/ck`, split digraphs `a_e/i_e/o_e`,
   vowel teams `ai/ee/oa`, r-controlled `ar/or/ir`). Best quality where it applies.
2. **Syllable chunking.** Hyphenation dictionaries (Hunspell/`pyphen`) split any word
   into syllables. Universal, robust, and still pedagogically sound.
3. **Letter by letter.** Last resort for names and unusual words.

Tier 2 is the workhorse and must handle arbitrary pasted text without ever failing.

### Sounding out the parts

Neural TTS is unreliable at pronouncing isolated phonemes — asked for /k/ it tends to
say "kuh" or the letter name. So sounded-out parts come from a **pre-rendered clip
library**: a fixed set of phoneme and syllable clips, checked once by ear for correctness,
recorded in the same voice as the full-word reading. Deterministic, and it removes an
entire class of embarrassing mispronunciations.

### Rendering

- Word/sentence timing from the TTS engine's own alignment output.
- Highlight is a colour/weight change on the active letter group — not a moving bar —
  so the whole word stays readable throughout.
- Video assembled with a bundled **ffmpeg**, encoded so it plays on TV built-in players
  (H.264 High profile, AAC audio, in an `.mp4`).

### Packaging

Single offline Windows installer. Everything vendored: voice models, clip library,
hyphenation dictionaries, ffmpeg. No network calls at any point, at install or at run.

---

## Settings

Kept deliberately few, all on one screen:

| Setting | Default |
|---|---|
| Repetitions per word | 3 |
| Pause between words | 1.5s |
| Sounding-out speed | Slow |
| Read whole sentence at end | On |
| Text size | Extra large |
| Colour theme | High contrast |
| Voice | Kokoro (female, warm) |

## Status

Design stage. Nothing built yet.

## License

TBD.
