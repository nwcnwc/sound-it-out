"""The curriculum: what each level puts on screen, and in whose voice.

Level order follows the Down syndrome reading research rather than the obvious
phonics-first ordering - sight words come first, phonics only after roughly 50
confident words. See the README for the citations.

Voice sourcing per level is the other half of the design:

    levels 1-6   the parent's recordings, used verbatim
    levels 7-9   generated - the cloned voice if installed, else the fallback

That split is deliberate. Levels 1-6 are where a new reader stays for a year or more,
and every sound there is genuinely the parent's. Generation only covers the
long tail the child will not reach for months, so if the clone disappoints it degrades
content that is not yet in use.
"""

from __future__ import annotations

from dataclasses import dataclass

from gen import openended, wordlists
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


# Multi-letter graphemes, longest first. This is the piece levels 7-9 needed:
# "ship" must highlight "sh" as ONE unit, because that is what it is - showing
# s-h-i-p teaches a child to look for four sounds in a three-sound word, which
# is worse than not splitting it at all.
#
# Curated rather than general. A full grapheme-phoneme aligner for arbitrary
# English is a research problem; a table that covers the words these levels
# actually teach is a afternoon's work and is correct where it applies.
GRAPHEMES = {
    # trigraphs first - longest match wins
    "igh": "aɪ", "air": "eə", "ear": "ɪə", "tch": "tʃ",
    # consonant digraphs
    "sh": "ʃ", "ch": "tʃ", "th": "θ", "ng": "ŋ", "ck": "k",
    "ph": "f", "wh": "w", "qu": "kw",
    # vowel digraphs
    "ai": "eɪ", "ay": "eɪ", "ee": "iː", "ea": "iː", "oa": "əʊ",
    "ow": "aʊ", "oo": "uː", "oi": "ɔɪ", "oy": "ɔɪ",
    "ar": "ɑː", "or": "ɔː", "er": "ɜː", "ir": "ɜː", "ur": "ɜː",
}


def split_graphemes(word: str):
    """Split a word into (letters, sound) pairs, keeping digraphs whole."""
    out, i, low = [], 0, word.lower()
    while i < len(word):
        for n in (3, 2):
            chunk = low[i:i + n]
            if len(chunk) == n and chunk in GRAPHEMES:
                out.append((word[i:i + n], GRAPHEMES[chunk]))
                i += n
                break
        else:
            ch = low[i]
            out.append((word[i], CVC_PHONEMES.get(ch, ch)))
            i += 1
    return out


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
    Level(1, "Paw Patrol", "The pups' names as whole words. Where a new reader starts.", "recorded"),
    Level(2, "Family and home", "Their own name, the people they love, everyday things.", "recorded"),
    Level(3, "Letter sounds", "One letter at a time, with its sound. s a t p i n first.", "recorded"),
    Level(4, "Two sounds together", "Joining two sounds: sa, at, ip, um.", "recorded"),
    Level(5, "Three-letter words", "sat, pin, man - and some nonsense words too.", "recorded"),
    Level(6, "Building up",
          "The whole journey in one go: single letters grow into words, "
          "and the words grow into a sentence.", "recorded"),
    Level(7, "Letter teams", "sh, ch, th, ck treated as one sound.", "generated"),
    Level(8, "Harder words", "Longer words with clusters: stop, black, hand.", "generated"),
    Level(9, "Sentences", "Whole sentences, read word by word then together.", "generated"),

    # Levels 10-12 have no fixed content. What they read depends on what the
    # parent pastes in, the names in their word list, and how far the child has
    # got - so it cannot be listed here, cannot be recorded in advance, and is
    # different for every family. This is what the cloned voice is for.
    Level(10, "Anything you paste in",
          "A page of a book, a card from Nana, a note about the day. "
          "Read word by word, then whole.", "open"),
    Level(11, "Their own sentences",
          "Sentences built from the names and things in your word list. "
          "Different for every family, and they change as you add words.", "open"),
    Level(12, "A story that grows",
          "A story told only with the letters they have learned so far. "
          "It gets longer as they learn more.", "open"),
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


# Level 7: each digraph taught with words that actually contain it.
DIGRAPH_WORDS = [
    "ship", "shop", "fish", "wish", "chat", "chip", "chin", "much",
    "thin", "with", "bath", "duck", "sock", "back", "kick",
    "ring", "sing", "long", "king",
]

# Level 8: consonant clusters, at the start and at the end. Clusters are the
# step after digraphs because they are two sounds that stay two sounds - the
# child has to hold both rather than swap in a new one.
CLUSTER_WORDS = [
    "stop", "step", "spin", "skip", "swim",
    "black", "flag", "plan", "clap", "glad",
    "hand", "sand", "bend", "jump", "lamp", "milk",
    "best", "nest", "must", "lost",
]

# Level 9: connected text, built only from what levels 1-8 have taught.
SENTENCES = [
    "The fish is in the net.",
    "A duck sat on the rock.",
    "Sam has a red hat.",
    "The king can sing.",
    "Stop and get the lamp.",
    "A chick is on the sand.",
]


def _check_ladder():
    """Fail loudly at import if a chapter uses an untaught letter.

    Silently showing a child a word they have no way to decode is exactly the
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
# All nine are built now. Levels 7-9 still lean on generation for the parts
# nobody can record - nonsense blends, and whole sentences read with real
# intonation - which is what the "install the extra voice" note is about.
IMPLEMENTED = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}


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
        elif lv.voice == "open":
            # Nothing here can be pre-recorded, so the voice question is real
            # rather than a fallback: without cloning these levels work, but
            # in the built-in voice rather than hers.
            ok = capabilities.get("cloning") or capabilities.get("fallback_voice")
            if not ok:
                reason = "Needs the built-in voice or voice cloning installed."
            elif capabilities.get("cloning"):
                reason = ""
            else:
                reason = ("Read in the built-in voice. This is the level the "
                          "extra voice pack is actually for - it is the only "
                          "way these can be in your voice, because nobody can "
                          "record them in advance.")
        else:
            ok = capabilities.get("cloning") or capabilities.get("fallback_voice")
            reason = "" if ok else "Needs the built-in voice or voice cloning installed."
            if ok and not capabilities.get("cloning"):
                reason = ("Whole sentences use the built-in voice. Install the "
                          "extra voice pack to have them read in your own.")
        out.append({"id": lv.id, "name": lv.name, "description": lv.description,
                    "available": bool(ok), "reason": reason,
                    # The UI has to know to show a text box for level 10, and
                    # to group the open-ended levels apart from the ladder.
                    "kind": lv.voice,
                    "needsText": lv.id == 10})
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
    what was asked for.
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
        #
        # Pacing note: these gaps are LONGER than the configured pause, not
        # shorter. The first version scaled them down (0.5x, 0.7x) on the
        # assumption that steps within one word should run together - which was
        # exactly wrong. The instant a new letter appears is the most important
        # beat in the level: it is when the word visibly changes, and the child
        # needs time to notice that before the next sound arrives. Rushing it
        # reads as skipping, because a step that should land has been swallowed.
        for word in chapter["words"]:
            parts = spell(word)
            for _ in range(inner):
                for i in range(len(parts)):
                    sofar = parts[: i + 1]
                    shown = [(g, j == i) for j, (g, _) in enumerate(sofar)]
                    # the new letter's own sound, then time to see it
                    segs.append(Segment(shown, voice.phoneme(sofar[i][1]),
                                        pad=pause * 1.15))
                    if i > 0:
                        # ...then everything so far, blended together. This is
                        # the payoff of the step, so it gets the longest beat.
                        flat = [(g, False) for g, _ in sofar]
                        segs.append(Segment(flat, voice.blend([p for _, p in sofar]),
                                            pad=pause * 1.35))
                segs.append(whole(word, voice.word(word), pad=pause + 1.4))

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
                                    pad=pause * 1.1, scale=0.9))
            segs.append(whole(chapter["sentence"],
                              voice.sentence(chapter["sentence"]),
                              pad=pause + 1.6, scale=0.9))
    return segs


def _sentences(voice, sentences, reps, pause):
    """Level 9: each word lit as it is read, then the whole thing together.

    The sentence is read WHOLE at the end rather than assembled from the word
    clips: connected speech has stress and intonation across the whole line,
    and concatenated words have neither. That read is the one part of this
    level that cannot come from the recorded clips.
    """
    segs = []
    for text in sentences:
        words = text.split()
        whole_audio = voice.sentence(text)
        for _ in range(max(1, reps - 1)):
            for i, w in enumerate(words):
                parts = []
                for j, other in enumerate(words):
                    if j:
                        parts.append((" ", False))
                    parts.append((other, j == i))
                segs.append(Segment(parts, voice.word(w.strip(".,!?")),
                                    pad=pause * 0.9, scale=0.85))
            segs.append(whole(text, whole_audio, pad=pause + 1.6, scale=0.85))
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
    if level == 7:
        return _sound_out(voice, [split_graphemes(w) for w in DIGRAPH_WORDS],
                          reps, pause)
    if level == 8:
        return _sound_out(voice, [split_graphemes(w) for w in CLUSTER_WORDS],
                          reps, pause)
    if level == 9:
        return _sentences(voice, SENTENCES, reps, pause)

    # ---- open-ended levels: content comes from the parent, not from here ----
    if level == 10:
        lines = openended.split_sentences(opts.get("text", ""))
        if not lines:
            raise ValueError(
                "Paste some text for this level first - a page of a book, a "
                "card, anything they would like read to them."
            )
        return _sentences(voice, lines, reps, pause)

    if level == 11:
        lines = openended.from_wordlist(groups)
        if not lines:
            raise ValueError(
                "This level builds sentences from your own word list, and it "
                "needs some names and some things to work with. Add a few to "
                "the People and Home groups on the Words tab."
            )
        return _sentences(voice, lines, reps, pause)

    if level == 12:
        lines = openended.story_so_far(stage=opts.get("stage"))
        if not lines:
            raise ValueError("No part of the story is readable yet.")
        return _sentences(voice, lines, reps, pause)

    raise NotImplementedError(
        f"Level {level} is designed but not built yet - see README for the plan."
    )
