"""The curriculum: what each level puts on screen, and in whose voice.

Level order follows the Down syndrome reading research rather than the obvious
phonics-first ordering - sight words come first, phonics only after roughly 50
confident words. See the README for the citations.

Voice sourcing per level is the other half of the design:

    levels 1-6   her recordings, used verbatim
    levels 7-9   generated - her cloned voice if installed, else the fallback

That split is deliberate. Levels 1-6 are where Alex lives for a year or more,
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
    level 7 and will need the alignment lexicon described in the README."""
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
    Level(6, "Building up",
          "The whole journey in one go: single letters grow into words, "
          "and the words grow into a sentence.", "recorded"),
    Level(7, "Letter teams", "sh, ch, th, ck treated as one sound.", "generated"),
    Level(8, "Harder words", "Longer words with clusters: stop, black, hand.", "generated"),
    Level(9, "Sentences", "Whole sentences, read word by word then together.", "generated"),
]

# The Building-up ladder, in chapters.
#
# One arc runs about a minute, and looping it thirty times is repetition, not a
# journey. So each chapter introduces a couple of new letters, builds words from
# everything taught so far, and ends on a sentence - four chapters is roughly
# half an hour and genuinely travels from single letters to connected text.
#
# The strict rule: no word may contain a letter that has not already been
# taught, in this chapter or an earlier one. That is what makes it cumulative
# rather than just sequential. `_check_ladder()` enforces it at import.
#
# "a" is the deliberate exception - it is both a letter and a word, and is
# taught as a sight word so a sentence can be formed at all.
SIGHT_IN_LADDER = {"a"}

LADDER = [
    {"letters": [("s", "s"), ("a", "æ"), ("t", "t"), ("m", "m")],
     "words": ["at", "am", "Sam", "sat", "mat"],
     "sentence": "Sam sat."},
    {"letters": [("o", "ɒ"), ("n", "n")],
     "words": ["on", "not", "man", "tan"],
     "sentence": "Sam sat on a mat."},
    {"letters": [("p", "p"), ("i", "ɪ")],
     "words": ["pin", "tip", "pit", "nap", "Pat"],
     "sentence": "Pat sat on a pin."},
    {"letters": [("d", "d"), ("g", "ɡ")],
     "words": ["dog", "dad", "mad", "dig"],
     "sentence": "A dog sat on Sam."},
]


def _check_ladder():
    """Fail loudly at import if a chapter uses an untaught letter.

    Silently showing a child a word he has no way to decode is exactly the
    failure this level exists to avoid, and it is far too easy to introduce by
    editing a word list without checking the letters.
    """
    taught = set(SIGHT_IN_LADDER)
    for n, ch in enumerate(LADDER, 1):
        taught |= {g for g, _ in ch["letters"]}
        for item in ch["words"] + ch["sentence"].replace(".", "").split():
            unknown = {c for c in item.lower() if c.isalpha()} - taught
            if unknown:
                raise ValueError(
                    f"Ladder chapter {n}: '{item}' uses untaught "
                    f"letter(s) {sorted(unknown)}"
                )


_check_ladder()


# Levels whose content generators exist. 7-9 are designed and specified in the
# README but not built - they need the grapheme-phoneme alignment lexicon, not
# just more word lists. Kept explicit so the UI can never offer a level that
# would fail halfway through generating.
IMPLEMENTED = {1, 2, 3, 4, 5, 6}


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


def _build_up(voice, reps, pause):
    """The whole arc in one video: letters -> words -> a sentence.

    Rather than three separate videos, a word is grown on screen one letter at
    a time, with the newly added letter highlighted:

        s  ->  sa  ->  sat  ->  "sat"

    then the finished words are grown into a sentence the same way. The point
    is the join: separate videos teach letters and words as different things,
    where this shows one becoming the other. It is also, almost word for word,
    what the parent asked for.
    """
    segs = []
    inner = max(1, reps - 1)

    for chapter in LADDER:
        # 1. Meet each new letter on its own.
        for letter, ipa in chapter["letters"]:
            audio = voice.phoneme(ipa)
            for i in range(reps):
                segs.append(whole(letter, audio,
                                  pad=pause if i < reps - 1 else pause + 0.5))

        # 2. Grow each word, one letter at a time.
        for word in chapter["words"]:
            parts = spell(word)
            for _ in range(inner):
                for i in range(len(parts)):
                    sofar = parts[: i + 1]
                    shown = [(g, j == i) for j, (g, _) in enumerate(sofar)]
                    # the new letter's own sound...
                    segs.append(Segment(shown, voice.phoneme(sofar[i][1]),
                                        pad=pause * 0.5))
                    if i > 0:
                        # ...then everything so far, blended together
                        flat = [(g, False) for g, _ in sofar]
                        segs.append(Segment(flat, voice.blend([p for _, p in sofar]),
                                            pad=pause * 0.7))
                segs.append(whole(word, voice.word(word), pad=pause + 1.0))

        # 3. Grow the chapter's sentence, one word at a time.
        words = chapter["sentence"].split()
        for _ in range(inner):
            for i, w in enumerate(words):
                parts = []
                for j, other in enumerate(words[: i + 1]):
                    if j:
                        parts.append((" ", False))
                    parts.append((other, j == i))
                segs.append(Segment(parts, voice.word(w.strip(".,!?")),
                                    pad=pause * 0.8, scale=0.9))
            segs.append(whole(chapter["sentence"],
                              voice.sentence(chapter["sentence"]),
                              pad=pause + 1.6, scale=0.9))
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
    if level == 6:
        return _build_up(voice, reps, pause)

    raise NotImplementedError(
        f"Level {level} is designed but not built yet - see README for the plan."
    )
