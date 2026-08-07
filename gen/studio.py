"""Record the clip library in the app, one item at a time.

The file-import path assumed a phone, a quiet 40 minutes, and no feedback until
the end - so a schwa on /t/ was discovered after the session, not during it.
Recording in the app turns that around: each item is prompted, spoken a few
times, scored immediately, and the best take kept.

## Why the best take, and not an average

Averaging several takes of the same word sounds like it should reduce noise, and
for a still image it would. For speech it does the opposite. Two takes are never
phase-aligned, so summing them comb-filters the result - a hollow, flanged
quality - and even after alignment the natural pitch and timing differences
between takes smear the formants, which are exactly the cues that distinguish
one sound from another. Blurring formants to reduce a little hiss is a bad
trade when the whole point is teaching a child to hear the difference between
/s/ and /f/.

So takes are scored and one is chosen. Noise is better handled by recording in
a quiet room, which the prompt asks for.

## What "best" means

Scored against what actually damages a phonics clip, worst first:

  1. a schwa on a consonant  - teaches "tuh" instead of /t/, fatal
  2. clipping                - distorted, and cannot be undone
  3. wrong length for class  - a held sound cut to 200ms cannot be blended with
  4. too quiet / poor SNR    - hiss becomes audible once it is stretched
  5. unsteadiness            - a held sound should be steady, not wobbling

The first two are disqualifying; the rest are weighted.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

import numpy as np
import soundfile as sf

from gen import recordings as R
from gen.paths import VOICE_DIR
from gen.soundout import SR

# Per class, the length a take should be. From RECORDING.md: continuants are
# held for about two seconds, stops are a burst and cannot be held at all.
LENGTH_TARGET = {
    "hold": (1.0, 3.0, 2.0),    # min, max, ideal seconds
    "crisp": (0.05, 0.60, 0.20),
    "free": (0.08, 1.50, 0.40),
}

TAKES_DEFAULT = 3


@dataclass
class Item:
    key: str            # filename-safe id
    kind: str           # "phoneme" | "word"
    display: str        # what appears on screen, large
    say: str            # the instruction under it
    length: str         # hold | crisp | free
    ipa: str = ""

    def path(self):
        sub = "phonemes" if self.kind == "phoneme" else "words"
        key = self.ipa if self.kind == "phoneme" else self.key
        safe = "".join(f"u{ord(c):04x}" if not c.isalnum() else c for c in key)
        return VOICE_DIR / sub / f"{safe}.wav"

    def done(self) -> bool:
        return self.path().exists()

    def as_dict(self):
        return {"key": self.key, "kind": self.kind, "display": self.display,
                "say": self.say, "length": self.length, "ipa": self.ipa,
                "target": LENGTH_TARGET[self.length][2], "done": self.done()}


def plan(part="phonemes", order="rows") -> list:
    """The ordered list of things to record, with on-screen guidance."""
    items = []
    if part == "phonemes":
        # phoneme_labels() returns keys; the studio needs the full record
        # (example word, IPA, and whether the sound is held or crisp) to
        # prompt properly and to score against the right target length.
        source = R.PHONEME_COLS if order == "columns" else R.PHONEME_ROWS
        for p in source:
            hold = p.length == "hold"
            items.append(Item(
                key=p.key, kind="phoneme", display=p.display, ipa=p.ipa,
                length=p.length,
                say=(f"Say the sound at the start of “{p.example}” - "
                     + ("hold it for about two seconds." if hold else
                        "keep it short and crisp." if p.length == "crisp" else
                        "say it naturally.")),
            ))
    else:
        from gen import wordlists

        for w in wordlists.all_words():
            items.append(Item(key=w.lower(), kind="word", display=w,
                              length="free",
                              say="Say it normally, the way you would in a sentence."))
    return items


# ------------------------------------------------------------------ audio


def decode(b64: str, sample_rate: int) -> np.ndarray:
    """Float32 PCM from the renderer, resampled to the pipeline's rate."""
    raw = np.frombuffer(base64.b64decode(b64), dtype="<f4").astype("float32")
    if sample_rate != SR:
        raw = R.resample(raw, sample_rate, SR)
    return raw


def _trim(a: np.ndarray, pad_ms=60) -> np.ndarray:
    """Strip room tone either side, keeping a little air so it is not clipped."""
    if not a.size:
        return a
    env = np.abs(a)
    thr = max(float(env.max()) * 0.06, 0.004)
    loud = np.where(env > thr)[0]
    if not loud.size:
        return a
    pad = int(SR * pad_ms / 1000)
    return a[max(0, loud[0] - pad): min(len(a), loud[-1] + pad)]


# ---------------------------------------------------------------- scoring


@dataclass
class Score:
    value: float = 0.0
    fatal: str = ""
    notes: list = field(default_factory=list)
    peak: float = 0.0
    seconds: float = 0.0
    snr_db: float = 0.0

    def as_dict(self):
        return {"value": round(self.value, 1), "fatal": self.fatal,
                "notes": self.notes, "peak": round(self.peak, 3),
                "seconds": round(self.seconds, 2), "snrDb": round(self.snr_db, 1)}


def score_take(audio: np.ndarray, item: Item) -> Score:
    s = Score()
    a = _trim(audio)
    if a.size < int(SR * 0.03):
        s.fatal = "Nothing was recorded."
        return s

    s.peak = float(np.abs(a).max())
    s.seconds = len(a) / SR

    # 2. clipping - disqualifying, and not fixable afterwards
    if s.peak >= 0.985:
        s.fatal = "Too loud - it distorted. Move back a little."
        return s

    # 1. schwa on a consonant - the fatal one for teaching
    if item.kind == "phoneme" and item.ipa:
        cls = R.phoneme_class(item.ipa)
        if cls != "vowel":
            try:
                if R._schwa_tail(a, item.ipa):
                    s.fatal = "There is an “uh” on the end."
                    return s
            except Exception:
                pass  # detector is advisory; never block a take on a crash

    lo, hi, ideal = LENGTH_TARGET[item.length]
    s.value = 100.0

    # 3. length
    if s.seconds < lo:
        s.value -= 45
        s.notes.append("shorter than it should be")
    elif s.seconds > hi:
        s.value -= 20
        s.notes.append("longer than it needs to be")
    else:
        s.value -= min(18.0, abs(s.seconds - ideal) / max(ideal, 0.01) * 18)

    # 4. level and noise.
    #
    # The floor must come from the UNTRIMMED audio: trimming removes exactly
    # the room tone we want to measure, so sampling the head of the trimmed
    # clip measures the onset of the sound itself and reports every clean take
    # as noisy. Use the quietest 100ms window of the original instead.
    n = int(SR * 0.1)
    if audio.size >= n * 2:
        wins = [float(np.sqrt(np.mean(audio[i:i + n] ** 2)))
                for i in range(0, len(audio) - n, n // 2)]
        noise = min(wins) if wins else 1e-4
    else:
        noise = 1e-4
    sig = float(np.sqrt(np.mean(a**2))) or 1e-6
    s.snr_db = 20 * np.log10(sig / max(noise, 1e-6))
    if s.peak < 0.06:
        s.value -= 35
        s.notes.append("very quiet")
    elif s.peak < 0.15:
        s.value -= 12
        s.notes.append("a little quiet")
    if s.snr_db < 12:
        s.value -= 15
        s.notes.append("noisy room")

    # 5. steadiness, but only where steadiness is the point
    if item.length == "hold":
        n = int(SR * 0.025)
        mid = a[int(len(a) * 0.2): int(len(a) * 0.85)]
        if len(mid) > n * 3:
            rms = np.array([np.sqrt(np.mean(mid[i * n:(i + 1) * n] ** 2))
                            for i in range(len(mid) // n)])
            if rms.mean() > 0:
                wobble = float(rms.std() / rms.mean())
                if wobble > 0.55:
                    s.value -= 12
                    s.notes.append("wavering rather than held steady")
    s.value = max(0.0, s.value)
    return s


def choose(takes: list, item: Item) -> dict:
    """Score every take and pick one, with a reason that can be shown."""
    scored = []
    for i, a in enumerate(takes):
        sc = score_take(a, item)
        scored.append({"index": i, "score": sc, "audio": _trim(a)})

    usable = [t for t in scored if not t["score"].fatal]
    best = max(usable, key=lambda t: t["score"].value) if usable else None

    return {
        "best": best["index"] if best else None,
        "takes": [{"index": t["index"], **t["score"].as_dict()} for t in scored],
        "audio": best["audio"] if best else None,
        "reason": ("" if not best else
                   "Clean take." if not best["score"].notes else
                   "Best of the takes, though it is " +
                   " and ".join(best["score"].notes) + "."),
        "allFailed": best is None,
    }


def save(item: Item, audio: np.ndarray) -> str:
    """Write the chosen take where gen/voice.py will find it.

    The saved files ARE the progress record - there is no separate state to
    keep in step, and nothing to corrupt. Whatever exists on disk is what has
    been recorded, which is also what the video generator will use.
    """
    path = item.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio.astype("float32"), SR)
    return str(path)


def find(part: str, key: str, order="rows"):
    """One item by key, so a single clip can be replayed or replaced."""
    for it in plan(part, order):
        if it.key == key:
            return it
    return None


def clip_path(part: str, key: str, order="rows"):
    """Where a recorded clip lives, or None if it has not been recorded."""
    it = find(part, key, order)
    if it is None:
        return None
    p = it.path()
    return str(p) if p.exists() else None


def remove(part: str, keys=None, order="rows") -> int:
    """Delete recordings so they can be done again.

    `keys=None` clears the whole part. Deleting is the honest way to redo:
    progress is read from the files, so removing one puts exactly that item
    back in the queue and leaves everything else untouched.
    """
    n = 0
    for it in plan(part, order):
        if keys is not None and it.key not in keys:
            continue
        p = it.path()
        if p.exists():
            p.unlink()
            n += 1
    return n
