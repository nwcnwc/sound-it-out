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

# Per class, the length a take should be. Continuants are held for a second
# or so; stops are a burst and cannot be held at all.
#
# The hold ideal is 1.3s, not the 2.0 it used to be, and the floor is 0.7.
# Measured against the guidance that said "about two seconds": a motivated
# adult following it held a MEDIAN of 1.22s - two full seconds is a length
# real mouths do not produce - and the scorer was docking every normal take
# for missing a target nobody hits. The videos prefer the shorter holds
# anyway: a long phoneme clip slows every buildup it appears in.
LENGTH_TARGET = {
    "continuant": (0.7, 3.0, 1.3),    # min, max, ideal seconds
    "stop": (0.05, 0.60, 0.20),
    "free": (0.08, 1.50, 0.40),
    # A whole line, not a word. Scored against "free" every sentence would be
    # over its 1.5s ceiling and lose points for the length that makes it a
    # sentence.
    "line": (0.8, 6.0, 2.2),
}

TAKES_DEFAULT = 3

# How many attempts to record per item, by part.
#
# Three takes earn their keep on the phonemes: there are only ~40 of them, an
# isolated /t/ is genuinely hard to say without an "uh" on the end, and picking
# the best of three is what keeps a schwa out of the library.
#
# Words are a different job. There are well over a hundred, saying one is
# something the speaker does correctly by reflex, and three takes of "dog"
# turns a manageable sitting into an hour of repeating herself. One take, and
# the scorer speaks up when it actually went wrong.
TAKES = {"phonemes": 3, "magic-e": 2, "pairs": 2, "words": 1, "sentences": 1}

# A real word carrying each rime's SOUND, so the prompt can always say
# "as in ...". Every rime has one - a prompt that names a sound the reader
# cannot deduce is a prompt that stops the session dead. Where no same-
# spelled everyday word exists, a sound-alike anchors it instead: "beef"
# carries /eef/ for "efe" perfectly well, because the anchor is for the
# ear, not the spelling.
MAGIC_E_EXAMPLES = {
    "abe": "babe", "ace": "face", "ade": "made", "afe": "safe",
    "age": "page", "ake": "cake", "ale": "tale", "ame": "name",
    "ane": "plane", "ape": "tape", "ase": "case", "ate": "gate",
    "aze": "maze",
    "ebe": "Beebe", "ece": "niece", "ede": "Swede", "efe": "beef",
    "ege": "siege", "eke": "week", "ele": "eel", "eme": "theme",
    "ene": "gene", "epe": "deep", "ese": "geese", "ete": "Pete",
    "eze": "sneeze",
    "ibe": "tribe", "ice": "nice", "ide": "ride", "ife": "life",
    "ige": "oblige", "ike": "like", "ile": "smile", "ime": "time",
    "ine": "nine", "ipe": "pipe", "ise": "rice", "ite": "kite",
    "ize": "prize",
    "obe": "robe", "oce": "dose", "ode": "rode", "ofe": "loaf",
    "oge": "doge", "oke": "joke", "ole": "hole", "ome": "home",
    "one": "bone", "ope": "hope", "ose": "dose", "ote": "note",
    "oze": "doze",
    "ube": "tube", "uce": "spruce", "ude": "rude", "ufe": "roof",
    "uge": "huge", "uke": "duke", "ule": "rule", "ume": "zoom",
    "une": "June", "upe": "soup", "use": "goose", "ute": "flute",
    "uze": "snooze",
}

# How each half of a rime is said, in plain letters a non-linguist can
# read aloud. The vowel says its NAME (that is what the magic e does);
# c and g are their soft sounds inside a rime.
MAGIC_E_VOWEL_HINT = {"a": "ay", "e": "ee", "i": "eye", "o": "oh", "u": "oo"}
MAGIC_E_CONS_HINT = {
    "b": "b", "c": "sss", "d": "d", "f": "fff", "g": "j", "k": "k",
    "l": "lll", "m": "mmm", "n": "nnn", "p": "p", "s": "sss", "t": "t",
    "z": "zzz",
}

# Every sound, in words a non-linguist can read aloud. Used to spell out
# what a pair is made of: "an" is “a as in ant” then “nnn”.
SOUND_HINTS = {
    "æ": "“a” as in ant", "ɑː": "“ah” as in father", "ɒ": "“o” as in hot",
    "ɔː": "“aw” as in saw", "aʊ": "“ow” as in cow", "aɪ": "“igh” as in high",
    "ʌ": "“u” as in cup", "ə": "a light “uh”", "ɛ": "“e” as in egg",
    "ɜː": "“er” as in her", "eɪ": "“ay” as in day", "iː": "“ee” as in see",
    "ɪ": "“i” as in sit", "əʊ": "“oh” as in go", "ɔɪ": "“oy” as in boy",
    "ʊ": "“oo” as in book", "uː": "“oo” as in moon", "eə": "“air”",
    "ɪə": "“ear”", "b": "“b”", "d": "“d”", "ð": "soft “th” as in this",
    "f": "“fff”", "ɡ": "“g”", "h": "“h”", "dʒ": "“j” as in jam",
    "k": "“k”", "l": "“lll”", "m": "“mmm”", "n": "“nnn”",
    "ŋ": "“ng” as in ring", "p": "“p”", "ɹ": "“rrr”", "s": "“sss”",
    "ʃ": "“sh” as in ship", "t": "“t”", "tʃ": "“ch” as in chip",
    "θ": "hard “th” as in thin", "v": "“vvv”", "w": "“w”",
    "j": "“y” as in yes", "z": "“zzz”", "ʒ": "“zh” as in treasure",
}


def sound_recipe(ipa: str) -> str:
    """The spoken recipe for a sound: its phonemes, in plain words."""
    from gen import dictionary

    hints = [SOUND_HINTS.get(t, f"“{t}”") for t in dictionary.phonemes_in(ipa)]
    return " then ".join(hints)


def takes_for(part: str) -> int:
    return TAKES.get(part, TAKES_DEFAULT)


# Faults worth stopping her for, and what to do about each.
#
# The test is not "is this take imperfect" but "can she do something about
# it". A word a shade longer than ideal is fine and saying so is nagging; a
# word too quiet to hear is worth ten seconds of moving the laptop closer.
# Only what is listed here interrupts - everything else is kept quietly.
ADVICE = {
    "very quiet": "it came out very quiet - try sitting a bit closer",
    "noisy room": "there is a fair bit of background noise",
    "shorter than it should be": "it got cut off - leave a beat before and after",
    "wavering rather than held steady": "try to hold it steady",
}


@dataclass
class Item:
    key: str            # filename-safe id
    kind: str           # "phoneme" | "word"
    display: str        # what appears on screen, large
    say: str            # the instruction under it
    length: str         # hold | crisp | free
    ipa: str = ""

    def path(self):
        sub = {"phoneme": "phonemes", "sentence": "sentences"}.get(self.kind, "words")
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
            hold = p.length == "continuant"
            # NOT "the sound at the start of" - that is only true for the
            # consonants. Nearly every vowel example has the sound in the
            # middle or at the end ("oo" in moon, "ar" in car), so the old
            # wording told her to say the wrong part of the word. This phrasing
            # is correct wherever the sound falls.
            items.append(Item(
                key=p.key, kind="phoneme", display=p.display, ipa=p.ipa,
                length=p.length,
                say=(f"Say the “{p.display}” sound, as in “{p.example}” - "
                     + ("hold it for a second or two." if hold else
                        "keep it short and crisp." if p.length == "stop" else
                        "say it naturally.")),
            ))
    elif part == "magic-e":
        # The magic-e rimes (ake, ice, ome), recorded live for the same reason
        # the 42 sounds are: an isolated sound is what cloning does worst,
        # and a wrong sound teaches a wrong thing. They save into phonemes/
        # under their IPA, which is exactly where the lookup already asks -
        # so a family recording these overrides the shipped ones with no new
        # machinery at all.
        from gen.starter import all_magic_e

        for spelling, ipa in all_magic_e():
            ex = MAGIC_E_EXAMPLES.get(spelling)
            how = (f"“{MAGIC_E_VOWEL_HINT[spelling[0]]}” then "
                   f"“{MAGIC_E_CONS_HINT[spelling[1]]}”, run together")
            items.append(Item(
                key=spelling, kind="phoneme", display=spelling, ipa=ipa,
                length="free",
                say=(f"Say the ending “{spelling}”: {how}"
                     + (f" — as in “{ex}”" if ex else "")
                     + ". No word around it."),
            ))
    elif part == "pairs":
        # Every GRAPHEME PAIR the dictionary uses, most useful first. Each
        # already PLAYS as an automatic blend of the two recorded phonemes;
        # recording one replaces the blend with a single human breath, for
        # that sound everywhere it appears. Saved under the sound's own name
        # in phonemes/, same as the 42 - which is also why magic-e
        # recordings made before this list existed appear here as done.
        from gen import dictionary

        for c in dictionary.pair_catalog():
            items.append(Item(
                key=c["ipa"], kind="phoneme", display=c["spelling"],
                ipa=c["ipa"], length="free",
                say=(f"Say “{c['spelling']}” as in “{c['example']}”: "
                     f"{sound_recipe(c['ipa'])}, run together. "
                     f"(/{c['ipa']}/)"),
            ))
    elif part == "sentences":
        # Every whole line any level reads out. There are about ten and they
        # take a minute; before this they were the one thing that could not be
        # her voice at all, however much else she recorded.
        from gen import levels
        from gen.voice import sentence_key

        seen = set()
        for text in ([ch["sentence"] for ch in levels.LADDER] + list(levels.SENTENCES)):
            key = sentence_key(text)
            if key in seen:
                continue
            seen.add(key)
            items.append(Item(
                key=key, kind="sentence", display=text, length="line",
                say="Read the whole line the way you would to your child - "
                    "not word by word.",
            ))
    else:
        from gen import levels, wordlists

        # Her own list first, then any word level 6 needs that is not already
        # in it. Without this the build-up level was 32% her voice even after a
        # full recording session: it teaches "sat", "mat", "dog" and so on,
        # none of which are sight words, so every one fell back to the built-in
        # voice with nothing on screen to explain why.
        seen, order = set(), []
        for w in wordlists.all_words():
            if w.lower() not in seen:
                seen.add(w.lower())
                order.append(w)
        ladder = [w for ch in levels.LADDER for w in ch["words"]]
        ladder += [w.strip(".,!?") for ch in levels.LADDER
                   for w in ch["sentence"].split()]
        # Levels 7-9 teach real words too, so they belong in the list. Without
        # this those levels fall back to the built-in voice for every word,
        # even after a complete recording session.
        ladder += levels.DIGRAPH_WORDS + levels.CLUSTER_WORDS
        ladder += [w.strip(".,!?") for sent in levels.SENTENCES
                   for w in sent.split()]
        for w in ladder:
            if w.lower() not in seen:
                seen.add(w.lower())
                order.append(w)

        for w in order:
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

    # Silence has to be caught here, on the untrimmed audio, and it has to be
    # fatal.
    #
    # _trim gives up and returns the buffer unchanged when nothing crosses its
    # threshold - which is exactly what a dead microphone produces. That buffer
    # is then long enough to satisfy the length guard below, so a recording of
    # pure digital silence used to score around 47, pick up a "very quiet"
    # note, and be SAVED. A parent could complete a whole session and end up
    # with a library of empty files, discovering it only on playback.
    #
    # That is not hypothetical: ChromeOS hands Linux a microphone that looks
    # healthy and delivers exact zeros, and it happened.
    raw_peak = float(np.abs(audio).max()) if audio.size else 0.0
    if raw_peak < 0.002:
        s.fatal = ("Nothing came through - check the microphone is on and is "
                   "the one the computer is listening to.")
        return s

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
    if item.length == "continuant":
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

    # Anything she could actually fix by having another go. With three takes
    # this rarely fires, because the best of three is usually clean. With one
    # take it is the whole safety net: nobody is comparing this against a
    # better attempt, so if it went wrong the app has to be the one to say so.
    advice = [ADVICE[n] for n in (best["score"].notes if best else []) if n in ADVICE]

    # "Best of the takes" is a lie when there was only one of them, and it
    # reads as though the app is comparing against attempts she never made.
    # The wording has to follow the number of takes, not assume three.
    notes = best["score"].notes if best else []
    single = len(scored) == 1
    if not best:
        reason = ""
    elif not notes:
        reason = "Got it." if single else "Clean take."
    else:
        reason = (("Got it, though it is " if single else
                   "Best of the takes, though it is ")
                  + " and ".join(notes) + ".")

    return {
        "best": best["index"] if best else None,
        "takes": [{"index": t["index"], **t["score"].as_dict()} for t in scored],
        "audio": best["audio"] if best else None,
        "reason": reason,
        "allFailed": best is None,
        # Kept, but worth offering another go at.
        "weak": bool(advice),
        "advice": advice,
    }


def backup_existing(item: Item) -> None:
    """Keep the previous take before overwriting it.

    Re-recording used to destroy the old clip outright. A spare copy costs a
    few KB and means a worse second attempt is not a one-way door.
    """
    p = item.path()
    if p.exists():
        prev = p.with_suffix(".previous.wav")
        try:
            prev.write_bytes(p.read_bytes())
        except OSError:
            pass  # a failed backup must never block the new recording


def save(item: Item, audio: np.ndarray) -> str:
    """Write the chosen take where gen/voice.py will find it.

    The saved files ARE the progress record - there is no separate state to
    keep in step, and nothing to corrupt. Whatever exists on disk is what has
    been recorded, which is also what the video generator will use.
    """
    backup_existing(item)
    path = item.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio.astype("float32"), SR)
    return str(path)


def _undo_safe(stem: str) -> str:
    """Best-effort reverse of _safe(), for display only. The uXXXX escapes
    only ever encode non-alphanumerics, so a real word is untouched and an
    encoded one comes back readable. Lookups keep using the stem itself."""
    import re

    return re.sub(r"u([0-9a-f]{4})", lambda m: chr(int(m.group(1), 16)), stem)


def bank_plan() -> list:
    """Every word actually in the shared bank, read straight from disk.

    Unlike plan("words"), which lists what the old curriculum wanted
    recorded, this is the catalog of what EXISTS - including words recorded
    through sentences that appear on no other list. The files ARE the
    catalog, the same way they are the progress record everywhere else.
    """
    d = VOICE_DIR / "words"
    items = []
    if d.exists():
        for f in sorted(d.glob("*.wav")):
            if f.name.endswith(".previous.wav"):
                continue
            items.append(Item(key=f.stem, kind="word",
                              display=_undo_safe(f.stem), length="free",
                              say="Say it normally, the way you would in a "
                                  "sentence."))
    return items


def find(part: str, key: str, order="rows"):
    """One item by key, so a single clip can be replayed or replaced."""
    for it in plan(part, order):
        if it.key == key:
            return it
    return None


def clip_path(part: str, key: str, order="rows"):
    """Where a recorded clip lives, or None if it has not been recorded."""
    # The passage is one file rather than an item in a list, so it has no key
    # to look up. It was therefore the one recording with no way to hear it
    # back - six minutes of reading, saved, with nothing to confirm it worked.
    if part == "passage":
        p = VOICE_DIR / "passage.wav"
        return str(p) if p.exists() else None

    # Bank keys ARE the on-disk stems, so no lookup table is needed - and
    # none would work, since the bank holds words no list knows about.
    if part == "bank":
        p = VOICE_DIR / "words" / f"{key}.wav"
        return str(p) if p.exists() else None

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
    items = bank_plan() if part == "bank" else plan(part, order)
    for it in items:
        if keys is not None and it.key not in keys:
            continue
        p = it.path()
        if p.exists():
            p.unlink()
            n += 1
    return n
