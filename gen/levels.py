"""The curriculum: what each level puts on screen, and in whose voice.

Level order follows the Down syndrome reading research rather than the obvious
phonics-first ordering - sight words come first, phonics only after roughly 50
confident words. See the README for the citations.

Voice sourcing per level is the other half of the design:

    levels 1-5   her recordings, used verbatim
    levels 6-8   generated - her cloned voice if installed, else the fallback

That split is deliberate. Levels 1-5 are where Alex lives for a year or more,
and every sound there is genuinely his mum. Generation only covers the long
tail he will not reach for months, so if the clone disappoints it degrades
content that is not yet in use.
"""

from __future__ import annotations

from dataclasses import dataclass

from gen import wordlists
from gen.soundout import Segment, whole

# ---------------------------------------------------------------- content

# Introduced in phonics order, not alphabetical. After just these six letters a
# child can already decode sat, pin, tap, nap, pit, tin - alphabetical order
# makes you wait until 't' before any word is possible at all.
SATPIN = [
    ("s", "s"), ("a", "æ"), ("t", "t"), ("p", "p"), ("i", "ɪ"), ("n", "n"),
]
SET2 = [("m", "m"), ("d", "d"), ("g", "ɡ"), ("o", "ɒ"), ("c", "k"), ("k", "k")]
SET3 = [("e", "ɛ"), ("u", "ʌ"), ("r", "ɹ"), ("h", "h"), ("b", "b"), ("f", "f"),
        ("l", "l")]

# Two-sound blends: consonant+vowel and vowel+consonant. The building blocks of
# blending, and the step most curricula skip too quickly.
BLENDS_2 = [
    [("s", "s"), ("a", "æ")], [("m", "m"), ("a", "æ")], [("p", "p"), ("i", "ɪ")],
    [("a", "æ"), ("t", "t")], [("i", "ɪ"), ("n", "n")], [("a", "æ"), ("m", "m")],
    [("i", "ɪ"), ("t", "t")], [("o", "ɒ"), ("n", "n")],
]

# Real CVC words and decodable nonsense words. Nonsense items are deliberate:
# a real word can be memorised as a shape, but 'vam' can only be read by
# actually decoding it. This is why formal phonics screening uses them.
CVC_REAL = ["sat", "pin", "man", "tap", "nip", "mat", "sit", "pan", "tin", "map"]
CVC_NONSENSE = ["vam", "zib", "fot", "lun", "dat", "mip"]

CVC_PHONEMES = {
    "s": "s", "a": "æ", "t": "t", "p": "p", "i": "ɪ", "n": "n", "m": "m",
    "d": "d", "g": "ɡ", "o": "ɒ", "c": "k", "k": "k", "e": "ɛ", "u": "ʌ",
    "r": "ɹ", "h": "h", "b": "b", "f": "f", "l": "l", "v": "v", "z": "z",
    "j": "dʒ", "w": "w", "y": "j", "x": "k", "q": "k",
}


def spell(word: str):
    """Split a word into (letter, phoneme) pairs. Level 5 is CVC only, so a
    straight letter-by-letter mapping is correct here; digraphs arrive at
    level 6 and will need the alignment lexicon described in the README."""
    return [(ch, CVC_PHONEMES.get(ch.lower(), ch.lower())) for ch in word]


# ----------------------------------------------------------------- levels


@dataclass
class Level:
    id: int
    name: str
    description: str
    voice: str  # "recorded" | "generated"


LEVELS = [
    Level(1, "Paw Patrol", "The pups' names as whole words. Where Alex starts.", "recorded"),
    Level(2, "Family and home", "His own name, the people he loves, everyday things.", "recorded"),
    Level(3, "Letter sounds", "One letter at a time, with its sound. s a t p i n first.", "recorded"),
    Level(4, "Two sounds together", "Joining two sounds: sa, at, ip, um.", "recorded"),
    Level(5, "Three-letter words", "sat, pin, man - and some nonsense words too.", "recorded"),
    Level(6, "Letter teams", "sh, ch, th, ck treated as one sound.", "generated"),
    Level(7, "Harder words", "Longer words with clusters: stop, black, hand.", "generated"),
    Level(8, "Sentences", "Whole sentences, read word by word then together.", "generated"),
]


# Levels whose content generators exist. 6-8 are designed and specified in the
# README but not built - they need the grapheme-phoneme alignment lexicon, not
# just more word lists. Kept explicit so the UI can never offer a level that
# would fail halfway through generating.
IMPLEMENTED = {1, 2, 3, 4, 5}


def level_status(capabilities: dict) -> list:
    """Which levels can be built right now, and an honest reason if not."""
    out = []
    for lv in LEVELS:
        if lv.id not in IMPLEMENTED:
            out.append({"id": lv.id, "name": lv.name, "description": lv.description,
                        "available": False, "reason": "Coming in a later version."})
            continue
        if lv.voice == "recorded":
            ok = capabilities.get("recordings") or capabilities.get("fallback_voice")
            reason = "" if ok else "Needs the voice recordings, or the built-in voice."
            if ok and not capabilities.get("recordings"):
                reason = "Will use the built-in voice until the recordings are imported."
        else:
            ok = capabilities.get("cloning") or capabilities.get("fallback_voice")
            reason = "" if ok else "Needs the built-in voice or voice cloning installed."
            if ok and not capabilities.get("cloning"):
                reason = "Will use the built-in voice - install voice cloning for Mum's voice."
        out.append({"id": lv.id, "name": lv.name, "description": lv.description,
                    "available": bool(ok), "reason": reason})
    return out


# ------------------------------------------------------------- builders


def _sight_words(voice, words, reps, pause):
    segs = []
    for word, color in words:
        audio = voice.word(word)
        for i in range(reps):
            segs.append(whole(word, audio, pad=pause if i < reps - 1 else pause + 0.6,
                              color=color))
    return segs


def _sounds(voice, letters, reps, pause):
    segs = []
    for letter, ipa in letters:
        audio = voice.phoneme(ipa)
        for i in range(reps):
            segs.append(whole(letter, audio, pad=pause if i < reps - 1 else pause + 0.6))
    return segs


def _sound_out(voice, spellings, reps, pause):
    """Highlight each letter as its sound plays, then blend the whole word."""
    segs = []
    for parts in spellings:
        word = "".join(g for g, _ in parts)
        blended = voice.word(word, slow=True)
        for _ in range(reps):
            for idx, (_, ipa) in enumerate(parts):
                shown = [(g, i == idx) for i, (g, _) in enumerate(parts)]
                segs.append(Segment(shown, voice.phoneme(ipa), pad=pause))
            segs.append(whole(word, blended, pad=pause + 1.2))
    return segs


def build(level: int, voice, opts: dict) -> list:
    """Produce the segment list for a level. `voice` supplies audio; see
    gen/voice.py for the recorded-first, generated-fallback resolution."""
    reps = int(opts.get("reps", 3))
    pause = float(opts.get("pauseSeconds", 1.2))
    groups = wordlists.load()

    def group(*names):
        for g in groups:
            if any(n in g.name.lower() for n in names):
                return g.words
        return []

    if level == 1:
        return _sight_words(voice, group("paw"), reps, pause)
    if level == 2:
        words = group("people") + group("home") + group("first")
        return _sight_words(voice, words, reps, pause)
    if level == 3:
        return _sounds(voice, SATPIN + SET2 + SET3, reps, pause)
    if level == 4:
        return _sound_out(voice, BLENDS_2, reps, pause)
    if level == 5:
        spellings = [spell(w) for w in CVC_REAL]
        if opts.get("nonsense", True):
            spellings += [spell(w) for w in CVC_NONSENSE]
        return _sound_out(voice, spellings, reps, pause)

    raise NotImplementedError(
        f"Level {level} is designed but not built yet - see README for the plan."
    )
