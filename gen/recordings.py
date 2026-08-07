"""Turn the parent's phone recordings into the clip library.

RECORDING.md asks them for three long files rather than 110 short ones, because
110 files is a 40 minute admin job for them and a 5 second job for a computer.
So this module does the 5 second job: find the gaps, cut on them, put a name to
each piece, and - the part that actually matters - check the result before it
goes anywhere near the TV.

    .venv/bin/python -m gen.recordings rec1.m4a --part phonemes
    .venv/bin/python -m gen.recordings rec2.m4a --part words
    .venv/bin/python -m gen.recordings rec3.m4a --part passage

The single most valuable thing in here is the schwa check. README's "Known
issue: schwa on isolated consonants" is about Kokoro, but a human makes exactly
the same mistake - saying "tuh" for /t/ is the natural thing to do, and it is
the most common reason home phonics stalls. A schwa-polluted /t/ is not a
slightly worse clip, it is a clip that teaches the wrong thing, and it will be
played hundreds of times. Catching it here costs their one retake; missing it
costs a year of "cuh-a-tuh".

Everything is reported in plain English, because the person reading the output
is the person who made the recording, not a programmer.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import wordlists  # noqa: E402
from gen.soundout import (  # noqa: E402
    SONORANTS, SR, STOP_MAX, STOPS, SUSTAIN_CONS, SUSTAIN_VOWEL, VOWELS,
    _buckets, shape_phoneme,
)

ROOT = Path(__file__).resolve().parent.parent
VOICE = ROOT / "assets" / "voice"

PARTS = ("phonemes", "words", "passage")


# ------------------------------------------------------------ the sounds

# Part 1 of RECORDING.md, in the order the tables are laid out. Order is the
# whole basis of the alignment - there is nothing in the audio that says which
# sound is which - so if they reads the tables in a different order, every clip
# gets the wrong name. Two mitigations: `--order columns` for the other obvious
# reading of a two-column table, and the report prints the order it assumed so
# a wrong guess is visible immediately rather than shipping silently.
#
# `key` is the filename and the manifest label; where RECORDING.md shows the
# same letters twice (th/th, oo/oo) the example word disambiguates.
# `ipa` is only used to classify the sound for the checks below, and is written
# in the same notation as gen/check_passage.py (script ɡ, ɹ not r).


class Phoneme(NamedTuple):
    key: str
    display: str  # what they sees in RECORDING.md
    example: str
    ipa: str
    length: str   # "hold" | "crisp" | "free"


# RECORDING.md gives their two lists and, deliberately, leaves three sounds off
# both of them: `w`, `y` and `h` are told neither to be held nor to be crisp.
# That is not an oversight to be tidied up - /w/ and /j/ are glides and /h/ is
# a puff of breath, and none of the three has a length anyone can be told to
# hit. So they are "free" and get no duration check at all; flagging their for
# the length of a sound they was never given a target for would be noise.
HOLD, CRISP, FREE = "hold", "crisp", "free"

# Rows exactly as printed: left column, right column.
_ROWS = [
    (("s", "s", "sun", "s", HOLD), ("m", "m", "man", "m", HOLD)),
    (("t", "t", "top", "t", CRISP), ("n", "n", "net", "n", HOLD)),
    (("p", "p", "pan", "p", CRISP), ("ng", "ng", "ring", "ŋ", HOLD)),
    (("k", "k", "cat", "k", CRISP), ("l", "l", "leg", "l", HOLD)),
    (("b", "b", "bat", "b", CRISP), ("r", "r", "run", "ɹ", HOLD)),
    (("d", "d", "dog", "d", CRISP), ("w", "w", "wet", "w", FREE)),
    (("g", "g", "got", "ɡ", CRISP), ("y", "y", "yes", "j", FREE)),
    (("f", "f", "fan", "f", HOLD), ("h", "h", "hat", "h", FREE)),
    (("v", "v", "van", "v", HOLD), ("sh", "sh", "shop", "ʃ", HOLD)),
    (("z", "z", "zip", "z", HOLD), ("ch", "ch", "chip", "tʃ", CRISP)),
    (("th", "th", "thin", "θ", HOLD), ("j", "j", "jam", "dʒ", CRISP)),
    (("th-this", "th", "this", "ð", HOLD), ("zh", "zh", "vision", "ʒ", HOLD)),
    (("a", "a", "cat", "a", HOLD), ("ee", "ee", "see", "iː", HOLD)),
    (("e", "e", "bed", "ɛ", HOLD), ("oo", "oo", "moon", "uː", HOLD)),
    (("i", "i", "sit", "ɪ", HOLD), ("or", "or", "door", "ɔː", HOLD)),
    (("o", "o", "dog", "ɒ", HOLD), ("ur", "ur", "her", "ɜː", HOLD)),
    (("u", "u", "cup", "ʌ", HOLD), ("ay", "ay", "day", "eɪ", HOLD)),
    (("oo-put", "oo", "put", "ʊ", HOLD), ("igh", "igh", "my", "aɪ", HOLD)),
    (("ar", "ar", "car", "ɑː", HOLD), ("oy", "oy", "boy", "ɔɪ", HOLD)),
    (("ow", "ow", "now", "aʊ", HOLD), ("oa", "oa", "go", "əʊ", HOLD)),
    (("air", "air", "hair", "eə", HOLD), ("ear", "ear", "near", "ɪə", HOLD)),
]

PHONEME_ROWS = [Phoneme(*c) for row in _ROWS for c in row]  # read across rows
PHONEME_COLS = [Phoneme(*row[0]) for row in _ROWS] + [Phoneme(*row[1]) for row in _ROWS]
PHONEMES = {p.key: p for p in PHONEME_ROWS}


# espeak-ng writes /g/ as U+0261 script ɡ (gen/check_passage.py says so, and
# the table above follows it), while gen/soundout.py spells STOPS with an ASCII
# g. Matching on the wrong one does not raise anything - it silently files
# every /g/ as a fricative and then points the schwa test at the wrong end of
# the sound. Normalise once, here, rather than remembering it at three sites.
_IPA_ALIASES = {"ɡ": "g", "ʧ": "t", "ʤ": "d", "ɫ": "l"}


def phoneme_class(ipa: str) -> str:
    """"vowel" | "stop" | "sonorant" | "fricative", in soundout.py's terms.

    Only the first symbol matters: an affricate (tʃ) behaves like its stop, and
    a long vowel or diphthong (ɑː, eɪ) like its first vowel.
    """
    c = _IPA_ALIASES.get(ipa[:1], ipa[:1])
    if c in VOWELS:
        return "vowel"
    if c in STOPS:
        return "stop"
    if c in SONORANTS:
        return "sonorant"
    return "fricative"


def phoneme_labels(order="rows") -> list:
    """The expected label order for Part 1."""
    return [p.key for p in (PHONEME_COLS if order == "columns" else PHONEME_ROWS)]


def word_labels(path=None) -> list:
    """The expected label order for Part 2 - their own checklist, in their order."""
    return wordlists.all_words(wordlists.load(path) if path else None)


# --------------------------------------------------------------- tuning

# All of these are shaped by what RECORDING.md actually asks them to do, which
# is the only thing we know for certain about the audio. None of it has been
# measured against a real session yet - there isn't one - so every constant is
# a named default that can be moved from the command line when there is.

FRAME = 0.020        # analysis hop for the silence gate
MIN_SILENCE = 0.6    # they are asked for 2s gaps; 0.6 survives their rushing them
MIN_ITEM = 0.05      # a duration filter cannot be the thing that rejects
                     # breaths: an isolated /t/ is a burst and a bit of
                     # aspiration and can be well under 100ms, so anything
                     # strict enough to drop a breath would drop half the stops.
                     # Level does that job instead - see BREATH_BELOW.
EDGE_PAD = 0.05      # keep either side of the gate - a /t/ release is fast and
                     # an RMS gate always opens a frame or two late
NOISE_PCT = 10       # with 2s gaps between items, the quietest 10% is room tone
FLOOR_WIN = 0.3      # quietest window taken as the noise floor
BREATH_BELOW = 22.0  # dB under the median item peak. Breaths run ~30dB down,
                     # but /f/ and /th/ are genuinely quiet sounds (~15dB down
                     # from a vowel), so there is less room here than it looks.
RETAKE_GAP = 1.2     # a pair closer together than this is a fluff and a retake
                     # rather than two different items (they are asked for 2s)
MERGED_RATIO = 1.9   # two items said without a gap come to ~2x the median

# Levels, in dBFS / linear peak. A phone at a hand's width lands around -12 dBFS.
CLIP_LEVEL = 0.999
QUIET_PEAK = 0.05    # -26 dBFS: audible, but thin on a TV across a room
SILENT_PEAK = 0.01   # -40 dBFS: whatever this is, it is not a voice

# How long each kind of item should be. The hold/crisp split is physical, not
# stylistic: fricatives, nasals and vowels have a steady state and can be
# sustained; a stop is a closure and a release with nothing holdable in between
# (README: "Stops are a hard physical limit, not an engineering gap").
# The pipeline's own synthesised clips run SUSTAIN_VOWEL/SUSTAIN_CONS long, so
# a recording shorter than that is too short to teach with even when it is a
# perfectly clean recording of the right sound.
HOLD_MIN = min(SUSTAIN_CONS, SUSTAIN_VOWEL)   # 0.68s
HOLD_MAX = 5.0
STOP_MIN = 0.04
STOP_MAX_OK = STOP_MAX + 0.15     # 0.45s - past here a "t" is really "tuh"
WORD_MIN = 0.15
WORD_MAX = 2.5

# The schwa test. shape_phoneme() cuts Kokoro's tail off at the point where the
# spectral centroid falls back into vowel territory; the same measurement finds
# the same fault in a human take. 2200Hz is shape_phoneme's own threshold.
SCHWA_CENTROID_HZ = 2200
SCHWA_RATIO = 0.55   # ...and it must be a *collapse*, not just a low centroid,
                     # or every voiced fricative (ð, v, z) trips it
SCHWA_MIN_MS = 100   # a release transient is shorter than this; a vowel isn't

PASSAGE_WORDS = 716
PASSAGE_WPM = 130    # unhurried reading-aloud pace


# ----------------------------------------------------------------- types


class Seg(NamedTuple):
    """An unnamed lump of sound with silence either side of it."""

    audio: np.ndarray
    start_s: float
    end_s: float

    @property
    def duration(self) -> float:
        return self.end_s - self.start_s


class Clip(NamedTuple):
    """A segment with a name on it. Unpacks as (label, audio, start, end)."""

    label: str | None
    audio: np.ndarray
    start_s: float
    end_s: float

    @property
    def duration(self) -> float:
        return self.end_s - self.start_s


@dataclass
class Issue:
    """One thing wrong with one clip. `message` is what they reads."""

    label: str
    code: str            # machine-readable, for the manifest
    severity: str        # "fail" = re-record it, "check" = have a listen
    message: str


@dataclass
class Alignment:
    """The result of matching segments to expected labels."""

    clips: list = field(default_factory=list)       # list[Clip], in label order
    unmatched: list = field(default_factory=list)   # list[Clip], label=None
    missing: list = field(default_factory=list)     # labels with no audio
    review: set = field(default_factory=set)        # labels a human must check
    notes: list = field(default_factory=list)       # plain English, for the report
    health: list = field(default_factory=list)      # Issues about the whole file
    source: Path | None = None

    @property
    def confident(self) -> bool:
        return not self.missing and not self.unmatched and not self.review


# ------------------------------------------------------------------- io


def _read_via_ffmpeg(path) -> tuple:
    """Decode with ffmpeg, for the formats libsndfile will not open.

    A phone voice memo is usually .m4a, which libsndfile cannot read at all.
    ffmpeg is already a hard dependency of the video pipeline, so lean on it
    rather than adding a decoder - and let it do the resampling to SR on the
    way out, since that is where the clips have to end up anyway.
    """
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype="<f4").astype("float32"), SR


def read_audio(path) -> tuple:
    """(mono float32, sample rate). Whatever their phone produced."""
    try:
        a, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:
        return _read_via_ffmpeg(path)
    return np.ascontiguousarray(a.mean(axis=1), dtype="float32"), int(sr)


def resample(a: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    """Band-limited resample, numpy only.

    Truncating the spectrum is an ideal low-pass, so 48k -> 24k does not alias
    the way a bare decimation would. Done per clip rather than per file: a
    15 minute recording at 48k is 43M samples and its complex spectrum would be
    most of a gigabyte, while a clip is seconds long and costs nothing. The
    circular edge effect that comes with a whole-signal FFT is harmless here
    because every clip starts and ends in room tone.
    """
    a = np.asarray(a, dtype="float32")
    if sr_in == sr_out or a.size == 0:
        return a
    n_out = int(round(len(a) * sr_out / sr_in))
    if n_out < 2:
        return np.zeros(0, dtype="float32")
    S = np.fft.rfft(a.astype(np.float64))
    T = np.zeros(n_out // 2 + 1, dtype=complex)
    keep = min(len(S), len(T))
    T[:keep] = S[:keep]
    return (np.fft.irfft(T, n=n_out) * (n_out / len(a))).astype("float32")


# ------------------------------------------------------- silence splitting


def _frame_db(a, sr) -> tuple:
    """Per-frame level in dBFS, and the hop in samples."""
    hop = max(1, int(sr * FRAME))
    nf = len(a) // hop
    fr = a[: nf * hop].reshape(nf, hop).astype(np.float64)
    return 20 * np.log10(np.sqrt((fr**2).mean(axis=1)) + 1e-9), hop


def _noise_floor(db) -> float:
    """The level of the quietest ~0.3s in the recording.

    A percentile would do for Parts 1 and 2, where most of the file is gaps,
    but Part 3 is five minutes of continuous reading - there the 10th
    percentile lands inside speech and the room looks far noisier than it is.
    The quietest short window works for both, because even a natural read
    leaves 0.3s of nothing at the section breaks.

    The percentile is kept as a floor under the floor: some phone apps write
    digital silence at the head of a file, and a window landing on that would
    put the gate below the real room tone.
    """
    n = max(1, int(FLOOR_WIN / FRAME))
    if len(db) <= n:
        return float(db.min())
    c = np.concatenate([[0.0], np.cumsum(10 ** (db / 10))])
    quietest = float(((c[n:] - c[:-n]) / n).min())
    return max(10 * np.log10(quietest + 1e-12),
               float(np.percentile(db, NOISE_PCT)) - 12.0)


def _runs(mask) -> list:
    """[(start, stop), ...] for each run of True in a boolean array."""
    out, run = [], None
    for i, v in enumerate(np.append(mask, False)):
        if v and run is None:
            run = i
        elif not v and run is not None:
            out.append((run, i))
            run = None
    return out


def find_segments(audio, sr, min_silence=MIN_SILENCE, min_item=MIN_ITEM,
                  pad=EDGE_PAD) -> list:
    """Cut a long recording into individual items on the silences.

    The threshold is taken from the recording rather than fixed, because a
    fixed dB gate is wrong for almost every phone: -40 dBFS is silence in a
    bedroom and speech in a kitchen. Two facts make an adaptive one easy here:
    RECORDING.md asks for a 2 second gap between every item, so the noise floor
    is directly measurable (_noise_floor); and the gate only has to sit
    *somewhere* between floor and voice, which is a 30-45 dB gap on any halfway
    usable recording.

    The gate opens at floor+margin and closes 4 dB lower (hysteresis), so a
    sound that dips in the middle - which every held /s/ does - stays one
    segment instead of shattering into five.
    """
    a = np.asarray(audio, dtype="float32")
    if len(a) < 3 * max(1, int(sr * FRAME)):
        return []
    db, hop = _frame_db(a, sr)
    floor, loud = _noise_floor(db), float(np.percentile(db, 95))
    if loud - floor < 6.0:
        return []  # no usable contrast: silence, or noise all the way through

    # A third of the way up from the floor, clamped: 8 dB is enough to clear
    # room tone, more than 18 dB starts eating quiet consonants like /f/.
    margin = min(max(0.35 * (loud - floor), 8.0), 18.0)
    open_db = min(floor + margin, loud - 10.0)
    close_db = open_db - 4.0

    core, ext = db >= open_db, db >= close_db
    segs = [(i, j) for i, j in _runs(ext) if core[i:j].any()]
    if not segs:
        return []

    # Join anything separated by less than a real gap. This is what stops a
    # breath taken mid-word, or the closure inside a /t/, becoming its own item.
    gap = max(1, int(min_silence / FRAME))
    merged = [list(segs[0])]
    for i, j in segs[1:]:
        if i - merged[-1][1] < gap:
            merged[-1][1] = j
        else:
            merged.append([i, j])

    keep = [(i, j) for i, j in merged if (j - i) * FRAME >= min_item]
    if not keep:
        return []

    # Breaths that land in the middle of a gap survive the duration test but
    # not the level test: they sit well below the items around them.
    peaks = [20 * np.log10(np.abs(a[i * hop:j * hop]).max() + 1e-9) for i, j in keep]
    if len(keep) >= 3:  # below that there is no median worth taking
        ref = float(np.median(peaks))
        keep = [s for s, p in zip(keep, peaks) if p >= ref - BREATH_BELOW]

    out, npad = [], int(pad * sr)
    for k, (i, j) in enumerate(keep):
        lo = max(i * hop - npad, keep[k - 1][1] * hop if k else 0)
        hi = min(j * hop + npad, keep[k + 1][0] * hop if k + 1 < len(keep) else len(a))
        out.append(Seg(a[lo:hi], lo / sr, hi / sr))
    return out


# ------------------------------------------------------------- alignment


def align(segments, expected_labels, retake_gap=RETAKE_GAP) -> Alignment:
    """Put a name to each segment, in order, without ever guessing quietly.

    There is nothing in the audio that identifies an item, so alignment is
    positional and a single miscount poisons everything after it. That makes
    honesty the design constraint: when the counts do not match, say so and
    mark the clips for a human, rather than producing a tidy-looking library
    where 'p' is actually 'b'.

    Too many segments is the expected case, not an error - RECORDING.md tells
    their "if you fluff one, just pause and say it again". The retake is the pair
    that is closest together, and the good one is the second, so drop the
    earlier half of the tightest pair until the counts agree.
    """
    segs = list(segments)
    labels = list(expected_labels)
    al = Alignment()
    dropped = []

    while len(segs) > len(labels) and len(segs) > 1:
        gaps = [segs[i + 1].start_s - segs[i].end_s for i in range(len(segs) - 1)]
        i = int(np.argmin(gaps))
        dropped.append((i, segs.pop(i), gaps[i] <= retake_gap))

    n = min(len(segs), len(labels))
    al.clips = [Clip(labels[i], segs[i].audio, segs[i].start_s, segs[i].end_s)
                for i in range(n)]
    al.missing = labels[n:]
    al.unmatched = [Clip(None, s.audio, s.start_s, s.end_s) for s in segs[n:]]

    for i, seg, looked_like_retake in dropped:
        name = labels[min(i, len(labels) - 1)] if labels else None
        al.unmatched.append(Clip(None, seg.audio, seg.start_s, seg.end_s))
        if looked_like_retake:
            al.notes.append(
                f"At {mmss(seg.start_s)} you said {describe(name)} twice - "
                f"I kept the second one."
            )
        else:
            # Far apart, so probably not a fluff-and-retake at all: something
            # extra got recorded, or an item got said in two pieces.
            if name:
                al.review.add(name)
            al.notes.append(
                f"There is an extra item at {mmss(seg.start_s)} that does not look "
                f"like a retake (the gap around it is {seg.duration:.1f}s of speech). "
                f"I left it out - worth a listen."
            )

    if len(segs) < len(labels):
        # A skipped item shifts every name after it, and nothing in the audio
        # says where the skip was. So no clip here can be trusted by position.
        al.review.update(c.label for c in al.clips)
        al.notes.append(
            f"I found {len(segs)} items but expected {len(labels)}. Something was "
            f"skipped, or two items were said without a gap between them - which "
            f"means the names after that point may be wrong."
        )
        if segs:
            med = float(np.median([s.duration for s in segs]))
            for s in segs:
                if s.duration > MERGED_RATIO * med:
                    al.notes.append(
                        f"  Most likely around {mmss(s.start_s)}, where one item runs "
                        f"for {s.duration:.1f}s - that may be two said together."
                    )
    elif al.unmatched and not dropped:
        al.notes.append(
            f"{len(al.unmatched)} more items than expected. The extra ones are at "
            + ", ".join(mmss(c.start_s) for c in al.unmatched) + "."
        )
    return al


def split_recording(path, expected_labels, min_silence=MIN_SILENCE,
                    min_item=MIN_ITEM, pad=EDGE_PAD, sr_out=SR) -> Alignment:
    """Read one long recording and return named clips at `sr_out`.

    `.clips` is the list of (label, audio, start_s, end_s) asked for; anything
    that could not be given a name is in `.unmatched`.
    """
    path = Path(path)
    audio, sr = read_audio(path)
    segs = find_segments(audio, sr, min_silence, min_item, pad)
    al = align(segs, expected_labels)
    al.source = path
    al.health = recording_health(audio, sr)  # while the whole file is still here
    al.clips = [c._replace(audio=resample(c.audio, sr, sr_out)) for c in al.clips]
    al.unmatched = [c._replace(audio=resample(c.audio, sr, sr_out))
                    for c in al.unmatched]
    return al


# ------------------------------------------------------------------- qc

# Everything below analyses at SR, because it reuses _buckets() from
# gen/soundout.py and that reads SR from the module. split_recording() already
# resamples, so clips arrive in the right rate.


def _analyse(a) -> list:
    """[(index, rms, centroid_hz)] per 25ms bucket. Zero centroid = silence."""
    return [(i, rms, cen) for i, _n, rms, cen in _buckets(a)]


def _schwa_tail(a, ipa):
    """Where an "uh" starts on a consonant, in seconds, or None.

    This is shape_phoneme()'s own measurement pointed the other way. There it
    finds the point where Kokoro's centroid falls back into vowel territory so
    it can cut it off; here the same collapse in a human take means they said
    "tuh", and the fix is a retake rather than a trim - their clips are used
    verbatim (README: levels 3-5 are "recorded, used verbatim").

    Two conditions, because either alone gives false positives: the centroid
    must land in vowel territory (<2200Hz, shape_phoneme's threshold) *and*
    collapse relative to the sound itself, or every voiced fricative - ð, v, z
    all sit low - would be flagged. It also has to last: a release transient is
    a bucket or two, a vowel is four or more.
    """
    b = _analyse(a)
    live = [x for x in b if x[1] >= 0.01]
    if len(live) < 3:
        return None

    if phoneme_class(ipa) == "stop":
        # A stop is a burst and then nothing. Anchor on the burst; anything
        # sustained after it is by definition not part of the stop.
        anchor = max(live, key=lambda x: x[1])[0]
        ref_cen = None
        core_rms = 0.0
    else:
        # Anchor on the frication core, exactly as shape_phoneme does.
        anchor = max(live, key=lambda x: x[2])[0]
        ref_cen = max(x[2] for x in live)
        core = [x[1] for x in live if x[0] <= anchor]
        core_rms = float(np.median(core)) if core else 0.0

    need = int(np.ceil(SCHWA_MIN_MS / 25))
    run, start = 0, None
    for i, rms, cen in b:
        if i <= anchor:
            continue
        vowelish = (
            rms > 0.02
            and 0 < cen < SCHWA_CENTROID_HZ
            and (ref_cen is None or cen < SCHWA_RATIO * ref_cen)
            and (core_rms == 0.0 or rms > 0.6 * core_rms)  # the RMS holds up
        )
        if vowelish:
            start = i if run == 0 else start
            run += 1
            if run >= need:
                return start * 0.025
        else:
            run, start = 0, None
    return None


def _sonorant_tail(a):
    """Where an "uh" may start on a nasal or liquid, in seconds, or None.

    The centroid test cannot separate /m/ from a schwa - both are voiced and
    low frequency, which is why soundout.py excludes SONORANTS from it too.
    What does survive is the direction of travel: a nasal sits very low and an
    "uh" after it sits higher, so the tail's centroid *rises* instead of
    collapsing. That is weaker evidence than the fricative test, so it only
    ever asks for a listen; it never asks for a retake.
    """
    live = [x for x in _analyse(a) if x[1] >= 0.01 and x[2] > 0]
    if len(live) < 12:
        return None
    tail, body = live[-8:], live[:-8]  # last 200ms
    body_cen = float(np.median([x[2] for x in body]))
    tail_cen = float(np.median([x[2] for x in tail]))
    body_rms = float(np.median([x[1] for x in body]))
    tail_rms = float(np.median([x[1] for x in tail]))
    if tail_cen > max(900.0, 1.8 * body_cen) and tail_rms > 0.5 * body_rms:
        return tail[0][0] * 0.025
    return None


def clean_phoneme(clip: Clip) -> np.ndarray:
    """A schwa-stripped, sustained version of a recorded phoneme.

    Not part of the import - their clips ship verbatim, and the honest fix for a
    schwa is a retake. This is here for the case where a retake is not going to
    happen (they has done their 40 minutes and moved on) and a usable /t/ is worth
    more than a pure one. Same treatment Kokoro's output gets.
    """
    p = PHONEMES.get(clip.label)
    # shape_phoneme branches on `ipa in STOPS/VOWELS`, i.e. on a single ASCII
    # symbol, so hand it the normalised first symbol rather than "ɡ" or "tʃ".
    ipa = _IPA_ALIASES.get(p.ipa[:1], p.ipa[:1]) if p else ""
    return shape_phoneme(np.asarray(clip.audio, dtype="float32"), ipa)


def quality_report(clips, part=None) -> list:
    """Everything wrong with these clips, worst first, in plain English."""
    clips = list(clips)
    if part is None:
        part = "phonemes" if all(c.label in PHONEMES for c in clips) else "words"
    issues = []

    for c in clips:
        a = np.asarray(c.audio, dtype="float32")
        who = describe(c.label)
        peak = float(np.abs(a).max()) if a.size else 0.0
        dur = len(a) / SR

        if peak < SILENT_PEAK:
            issues.append(Issue(c.label, "silent", "fail",
                                f"{who} - there is no sound here at all, just silence."))
            continue

        n_clipped = int(np.count_nonzero(np.abs(a) >= CLIP_LEVEL))
        if n_clipped > max(4, 0.0005 * a.size):
            issues.append(Issue(c.label, "clipped", "fail",
                                f"{who} - too loud, so it crackles. Move the phone a "
                                f"little further away and say it again."))
        elif peak < QUIET_PEAK:
            issues.append(Issue(c.label, "quiet", "fail",
                                f"{who} - very quiet, and it will be hard to hear "
                                f"across a room. Hold the phone closer and say it again."))

        p = PHONEMES.get(c.label) if part == "phonemes" else None
        if p is None:
            if dur < WORD_MIN:
                issues.append(Issue(c.label, "short", "fail",
                                    f"{who} - only {dur:.2f} seconds, which is too "
                                    f"short to be the whole word."))
            elif dur > WORD_MAX:
                issues.append(Issue(c.label, "long", "check",
                                    f"{who} - {dur:.1f} seconds, longer than a single "
                                    f"word usually takes. Have a listen in case two "
                                    f"words ran together."))
            continue

        # The one that matters most, and it comes first because on a stop it
        # explains the duration as well - "your t is half a second long" and
        # "your t has an uh on it" are the same finding, and saying both just
        # buries the one that tells them what to do about it.
        schwa = False
        kind = phoneme_class(p.ipa)
        if kind == "vowel":
            pass  # a schwa is a vowel; on a vowel there is nothing to separate
        elif kind == "sonorant":
            if _sonorant_tail(a) is not None:
                issues.append(Issue(c.label, "schwa?", "check",
                                    f"{who} - there may be an \"uh\" at the end. Have a "
                                    f"listen: it should be one long hum with nothing "
                                    f"after it, not \"{p.display}uh\"."))
        elif _schwa_tail(a, p.ipa) is not None:
            schwa = True
            issues.append(Issue(c.label, "schwa", "fail",
                                f"{who} - it has an \"uh\" on the end; it sounds like "
                                f"\"{p.display}uh\". Say just the sound and stop - this "
                                f"is the one thing worth getting exactly right."))

        if p.length == HOLD:
            if dur < HOLD_MIN:
                held = p.display * 5 if len(p.display) == 1 else p.display
                issues.append(Issue(c.label, "too-short", "fail",
                                    f"{who} - only {dur:.1f} seconds. Hold it for "
                                    f"about two seconds: \"{held}\". A sound that is "
                                    f"merely short is no use for sounding out."))
            elif dur > HOLD_MAX:
                issues.append(Issue(c.label, "too-long", "check",
                                    f"{who} - {dur:.1f} seconds, longer than expected. "
                                    f"Have a listen in case two got joined together."))
        elif p.length == CRISP:
            if dur < STOP_MIN:
                issues.append(Issue(c.label, "too-short", "fail",
                                    f"{who} - {dur:.2f} seconds, so short it may have "
                                    f"been cut off."))
            elif dur > STOP_MAX_OK and not schwa:
                issues.append(Issue(c.label, "too-long", "fail",
                                    f"{who} - {dur:.1f} seconds. This one is a tiny "
                                    f"burst and then gone, so anything this long has "
                                    f"something else on the end of it."))

    order = {"fail": 0, "check": 1}
    return sorted(issues, key=lambda i: order.get(i.severity, 2))


def recording_health(audio, sr) -> list:
    """Problems with the recording as a whole rather than any one item."""
    a = np.asarray(audio, dtype="float32")
    out = []
    if a.size < sr:
        return [Issue("recording", "empty", "fail",
                      "The file is less than a second long.")]
    db, _hop = _frame_db(a, sr)
    floor, loud = _noise_floor(db), float(np.percentile(db, 95))

    if int(np.count_nonzero(np.abs(a) >= CLIP_LEVEL)) > 0.0002 * a.size:
        out.append(Issue("recording", "clipped", "fail",
                         "The recording is too loud in places and crackles. Hold the "
                         "phone a bit further from your mouth and record it again."))
    if loud < -30:
        out.append(Issue("recording", "quiet", "check",
                         "The whole recording is quiet. It will work, but closer to "
                         "the phone would be better."))
    if loud - floor < 20:
        out.append(Issue("recording", "noisy", "check",
                         "There is a fair amount of background noise - it is not far "
                         "below your voice. A quieter room would help."))
    return out


# ------------------------------------------------------------------ save


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")
    return s or "item"


def default_outdir(part: str) -> Path:
    return VOICE if part == "passage" else VOICE / part


def save_clips(clips, outdir, source=None, issues=(), review=(), part=None,
               notes=()) -> list:
    """Write one wav per clip plus a manifest, and return the paths written.

    Clips are written verbatim at SR, mono, 32-bit float - the same rate the
    rest of the pipeline works in, so nothing has to convert at playback time.
    Flagged clips are written too: the manifest carries the flags, and it is
    for the app (or a human) to decide what to do with a clip that needs a
    retake, not for the importer to silently drop their recording.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    by_label = {}
    for i in issues:
        by_label.setdefault(i.label, []).append(i)

    items, written, used = [], [], set()
    for c in clips:
        name = _slug(c.label)
        while name in used:  # two words that slug the same, e.g. "Mum" / "mum!"
            name += "-2"
        used.add(name)
        path = outdir / f"{name}.wav"
        sf.write(path, np.asarray(c.audio, dtype="float32"), SR, subtype="FLOAT")
        written.append(path)
        items.append({
            "label": c.label,
            "file": path.name,
            "start_s": round(c.start_s, 3),
            "end_s": round(c.end_s, 3),
            "duration_s": round(len(c.audio) / SR, 3),
            "confidence": "check" if c.label in set(review) else "ok",
            "flags": [{"code": i.code, "severity": i.severity, "message": i.message}
                      for i in by_label.get(c.label, [])],
        })

    manifest = {
        "part": part,
        "source": str(source) if source else None,
        "sample_rate": SR,
        "channels": 1,
        "format": "float32",
        "imported": datetime.datetime.now().isoformat(timespec="seconds"),
        "items": items,
        "notes": list(notes),
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return written


# ---------------------------------------------------------------- report


def mmss(t: float) -> str:
    """Position in the recording, so they can find it in the recorded voice memo app."""
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def describe(label) -> str:
    p = PHONEMES.get(label)
    if p:
        return f"the '{p.display}' sound (as in {p.example})"
    return f'the word "{label}"' if label else "an extra item"


_TITLES = {
    "phonemes": "Part 1 - the sounds",
    "words": "Part 2 - the sight words",
    "passage": "Part 3 - the reading passage",
}


def format_report(part, alignment=None, issues=(), source=None, outdir=None,
                  extra=()) -> str:
    """The whole result, for someone who has never seen a terminal before."""
    lines = [_TITLES.get(part, part), "=" * max(34, len(_TITLES.get(part, part)))]
    if source:
        lines.append(f"From: {Path(source).name}")
    lines.append("")

    if alignment is not None:
        found = len(alignment.clips)
        want = found + len(alignment.missing)
        lines.append(f"Expected {want} items, matched up {found}.")
        for note in alignment.notes:
            lines.append(f"  {note}")
        lines.append("")

    for line in extra:
        lines.append(line)
    if extra:
        lines.append("")

    fails = [i for i in issues if i.severity == "fail"]
    checks = [i for i in issues if i.severity != "fail"]

    if fails:
        n = len(fails)
        lines.append(f"Please record {n} of these again:" if n > 1
                     else "Please record this one again:")
        lines.append("")
        for i in fails:
            lines += _wrap(i.message)
        lines.append("")
    if checks:
        lines.append("Worth a quick listen (they may be fine):")
        lines.append("")
        for i in checks:
            lines += _wrap(i.message)
        lines.append("")

    if alignment is not None:
        labels = {c.label for c in alignment.clips}
        good = len(labels - {i.label for i in issues})
        if not fails and not checks and alignment.confident:
            lines.append("Everything looks good. Nothing to re-record.")
        elif good > 0:
            lines.append(f"The other {good} look good.")
    if outdir:
        lines.append(f"Saved to {outdir}")
    return "\n".join(lines).rstrip() + "\n"


def _wrap(text, width=74, bullet="  * ", indent="    "):
    out, line = [], bullet
    for w in text.split():
        if len(line) > len(indent) and len(line) + len(w) > width:
            out.append(line.rstrip())
            line = indent
        line += w + " "
    out.append(line.rstrip())
    return out


# ---------------------------------------------------------------- passage


def check_passage(path, outdir=None, dry_run=False) -> tuple:
    """Part 3 is never split - it is the voice-cloning reference, used whole.

    Nothing here can be checked against a list, so the checks are about whether
    the recording is usable at all: is it the right length (i.e. did they read
    all of it), is it clean, is the room quiet enough. A cloner learns rhythm
    and melody from this, so a truncated or noisy take is worth catching now
    rather than after the model has been trained on it.
    """
    audio, sr = read_audio(path)
    a = resample(audio, sr, SR)
    dur = len(a) / SR
    expected = PASSAGE_WORDS / PASSAGE_WPM * 60
    issues = list(recording_health(a, SR))
    notes = [f"Length: {dur / 60:.1f} minutes "
             f"(expected roughly {expected / 60:.1f} for all six sections)."]

    if dur < expected * 0.55:
        issues.append(Issue("recording", "short", "fail",
                            f"This is only {dur / 60:.1f} minutes, and the passage "
                            f"takes about {expected / 60:.0f}. It looks like part of "
                            f"it is missing - please read all six sections."))
    elif dur > expected * 2.2:
        issues.append(Issue("recording", "long", "check",
                            "This is a good deal longer than expected. That is fine, "
                            "but check nothing extra got recorded at the end."))

    out = None
    if not dry_run:
        outdir = Path(outdir or default_outdir("passage"))
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / "passage.wav"
        sf.write(out, a, SR, subtype="FLOAT")
        (outdir / "passage.json").write_text(json.dumps({
            "source": str(path),
            "sample_rate": SR,
            "duration_s": round(dur, 2),
            "purpose": "voice cloning reference - never played back to the child",
            "imported": datetime.datetime.now().isoformat(timespec="seconds"),
        }, indent=2) + "\n")
    return issues, notes, out


# ------------------------------------------------------------------ main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m gen.recordings",
        description="Split a recording session into clips and check them.",
    )
    ap.add_argument("audio", help="the long recording from their phone")
    ap.add_argument("--part", required=True, choices=PARTS)
    ap.add_argument("--out", help="where to write the clips")
    ap.add_argument("--min-silence", type=float, default=MIN_SILENCE,
                    help="shortest gap that counts as a gap (seconds)")
    ap.add_argument("--order", choices=("rows", "columns"), default="rows",
                    help="how the two-column sound tables in RECORDING.md were read")
    ap.add_argument("--words", help="word list file (defaults to the shipped one)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)

    src = Path(args.audio)
    if not src.exists():
        print(f"Can't find that file: {src}")
        return 2

    if args.part == "passage":
        issues, notes, out = check_passage(src, args.out, args.dry_run)
        print(format_report("passage", None, issues, src, out, extra=notes))
        return 1 if any(i.severity == "fail" for i in issues) else 0

    labels = (phoneme_labels(args.order) if args.part == "phonemes"
              else word_labels(args.words))
    al = split_recording(src, labels, min_silence=args.min_silence)
    issues = al.health + quality_report(al.clips, part=args.part)

    extra = []
    if args.part == "phonemes":
        extra.append(f"Assuming you read the tables across the rows "
                     f"({', '.join(PHONEMES[k].display for k in labels[:4])}, ...). "
                     f"If you went down the columns instead, run it again with "
                     f"--order columns.")

    out = None
    if not args.dry_run and al.clips:
        out = Path(args.out or default_outdir(args.part))
        save_clips(al.clips, out, source=src, issues=issues, review=al.review,
                   part=args.part, notes=al.notes)
    print(format_report(args.part, al, issues, src, out, extra=extra))
    return 1 if any(i.severity == "fail" for i in issues) or not al.confident else 0


if __name__ == "__main__":
    raise SystemExit(main())
