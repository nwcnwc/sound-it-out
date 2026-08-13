"""The sentence library: any sentence she adds, recorded as its parts.

This is the simplified shape the app is growing toward. A sentence carries
everything a video needs - its words, their sounds, and the whole line - so
the library entry is just the text, and the recordings are captured in a
short walk-through: each word she has not recorded before, then the line
read whole. Words are saved to the SHARED word bank (gen/voice.py's words/),
not to anything per-sentence, so every sentence she adds gets cheaper to
record than the one before it.

The whole-line read earns its keep twice. Once as the natural payoff of the
video - connected speech has melody that joined-up clips do not - and once
as the read-along: the word being read is highlighted in time with her
voice, and the timing comes from arithmetic rather than an aligner. Her
isolated word clips give the RELATIVE length of each word (same speaker,
same words), the line recording gives the total, and the word boundaries
are the cumulative product of the two. See word_spans().
"""

from __future__ import annotations

import re

import numpy as np

from gen import studio
from gen import paths
from gen.paths import WORDLISTS
from gen.voice import sentence_key

SENTENCES_FILE = WORDLISTS / "sentences.txt"

# Words whose isolated clip is a poor guide to their length in flowing
# speech: said alone, "the" is a full careful syllable; inside a sentence it
# is squeezed to a fraction of that. Content words shrink too, but roughly
# uniformly - which proportional allocation cancels out - so only the little
# grammar words need a thumb on the scale.
FUNCTION_WORDS = {
    "the", "a", "an", "to", "of", "and", "in", "on", "at", "is", "it",
    "as", "or", "for", "was", "are", "be", "his", "her", "its", "with",
    "you", "i",
}
FUNCTION_DISCOUNT = 0.5


def _clean(word: str) -> str:
    return word.strip(".,!?;:‘’“”'\"")


def entry_kind(text: str) -> str:
    """What sort of thing one library entry is.

    The library holds more than sentences, on purpose - it is the ONLY list
    in the app, so a favourite name and a single letter live here too:

        "s"                one letter  -> its sound, from the phoneme bank
        "Chase"            one word    -> sight or sounded out, no line read
        "Sam sat."         a sentence  -> the full journey

    A one-word entry has no separate whole-line read - the word IS the line -
    and a letter entry has nothing to record at all, because the 42 sounds
    are recorded once in Setup and shared by everything.
    """
    words = [w for w in (_clean(w) for w in text.split()) if w]
    if len(words) == 1 and len(words[0]) == 1 and words[0].isalpha():
        return "letter"
    if len(words) == 1:
        return "word"
    return "sentence"


# ------------------------------------------------------------- the library


def load() -> list:
    """The sentences she has added, in the order she added them."""
    if not SENTENCES_FILE.exists():
        return []
    out, seen = [], set()
    for line in SENTENCES_FILE.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        key = sentence_key(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _save(texts: list):
    SENTENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SENTENCES_FILE.write_text(
        "# One sentence per line. This file belongs to your family - it is\n"
        "# never shipped with the app and never leaves this computer.\n"
        + "\n".join(texts) + ("\n" if texts else ""),
        encoding="utf-8",
    )


def add(text: str) -> list:
    """Add what she typed - one sentence or a pasted paragraph of them."""
    from gen import openended

    lines = openended.split_sentences(text)
    if not lines:
        raise ValueError("That did not contain a sentence to add.")
    texts = load()
    seen = {sentence_key(t) for t in texts}
    for line in lines:
        key = sentence_key(line)
        if key and key not in seen:
            seen.add(key)
            texts.append(line)
    _save(texts)
    return texts


def remove(key: str) -> list:
    """Drop a sentence from the library. Recordings are kept: the words
    belong to the shared bank and may serve other sentences, and the line
    clip is harmless on disk and precious if she re-adds the sentence."""
    texts = [t for t in load() if sentence_key(t) != key]
    _save(texts)
    return texts


def texts_for(keys=None) -> list:
    """The sentences to build a video from - the chosen ones, else all."""
    texts = load()
    if keys is None:
        return texts
    want = set(keys)
    return [t for t in texts if sentence_key(t) in want]


# ------------------------------------------------------ recording status


def _word_item(word: str) -> studio.Item:
    return studio.Item(key=word.lower(), kind="word", display=word,
                       length="free",
                       say="Say it normally, the way you would in a sentence.")


def _line_item(text: str) -> studio.Item:
    return studio.Item(key=sentence_key(text), kind="sentence", display=text,
                       length="line",
                       say="Read the whole line the way you would to your "
                           "child - not word by word.")


def _unique_words(text: str) -> list:
    out, seen = [], set()
    for w in text.split():
        c = _clean(w)
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def _letter_recorded(ch: str) -> bool:
    """Whether a letter's sound exists in her bank or the shipped starter.

    Reads the voice module's directory globals rather than importing paths
    afresh, so this looks wherever gen/voice.py looks - including under
    tests and overrides that repoint those globals.
    """
    from gen import levels, voice

    ipa = levels.SINGLE_LETTER_GRAPHEMES.get(ch.lower(), ch.lower())
    return (voice.VoiceSource._lookup(voice.VOICE_DIR, paths.SOUNDS, ipa) is not None
            or voice.VoiceSource._lookup(voice.STARTER_VOICE, paths.SOUNDS, ipa)
            is not None)


def _starter_has(sub: str, key: str) -> bool:
    from gen import voice

    return voice.VoiceSource._lookup(voice.STARTER_VOICE, sub, key) is not None


def status() -> list:
    """Every entry, with what is recorded and what is still to do."""
    out = []
    for text in load():
        kind = entry_kind(text)
        words = _unique_words(text)
        if kind == "letter":
            # Nothing per-entry to record: the sound comes from the 42
            # recorded in Setup (or the shipped starter voice until then).
            missing, line_done = [], True
            ready = _letter_recorded(words[0])
        elif kind == "word":
            missing = [w for w in words if not _word_item(w).done()]
            line_done = True  # the word IS the line
            ready = not missing
        else:
            missing = [w for w in words if not _word_item(w).done()]
            line_done = _line_item(text).done()
            ready = not missing and line_done
        # Whether the shipped starter voice fills every gap - the difference
        # between "a human reads this today" and "a synthesiser does", which
        # the row should say honestly.
        starter = bool(missing or not line_done) and all(
            _starter_has("words", w.lower()) for w in missing
        ) and (line_done or kind != "sentence"
               or _starter_has("sentences", sentence_key(text)))
        out.append({
            "key": sentence_key(text),
            "text": text,
            "kind": kind,
            "words": len(words),
            "missing": missing,
            # Buildup sound pieces not yet in the family's own voice -
            # the walk-through queues these after the line and the words.
            "missingSounds": 0 if kind == "letter" else len(_piece_items(text)),
            "starterCovered": starter,
            # How many of this entry's words the shared bank already covers.
            # The bank makes recording quietly cheap, and quiet reads as
            # broken: "it only asked me one of the five words" is a bug
            # report unless the screen says where the other four came from.
            "recordedWords": len(words) - len(missing),
            "lineRecorded": line_done,
            "ready": ready,
        })
    return out


def clips(key: str) -> list:
    """Every clip behind one entry, for listening back: each word, then the
    line. Entries without a recording yet carry no path - the UI shows them
    as still to do rather than hiding them."""
    import numpy as np
    import soundfile as sf

    out = []
    for it in walkthrough_items(key):
        entry = {"key": it.key, "kind": it.kind, "display": it.display,
                 "path": None, "seconds": 0.0, "silent": True}
        p = it.path()
        if p.exists():
            try:
                a, sr = sf.read(str(p), dtype="float32")
                peak = float(np.abs(a).max()) if a.size else 0.0
                entry.update(path=str(p), seconds=round(len(a) / sr, 2),
                             silent=peak < 0.01)
            except Exception:
                pass  # unreadable file reads as unrecorded, which is honest
        out.append(entry)
    return out


def _piece_items(text: str) -> list:
    """The sound pieces of this entry's buildups the family has NOT
    recorded themselves: grapheme pairs first, then single phonemes. These queue in
    the walk-through so a sentence can become fully hers, and they shrink
    to nothing as the shared bank fills - the pieces are keyed by sound,
    recorded once, used everywhere."""
    from gen import dictionary, levels

    seen, pairs_out, singles = set(), [], []
    for w in _unique_words(text):
        if not levels.decodable(w):
            continue
        for g, ipa in levels.word_alignment(w):
            if ipa in seen:
                continue
            seen.add(ipa)
            recipe = studio.sound_recipe(ipa)
            many = len(dictionary.phonemes_in(ipa)) > 1
            it = studio.Item(
                key=ipa, kind="phoneme", display=g.lower(), ipa=ipa,
                length="free",
                say=(f"From “{_clean(w)}”: say “{g.lower()}” — {recipe}"
                     + (", run together" if many else "")
                     + f". No word around it. (/{ipa}/)"))
            if it.done():
                continue
            (pairs_out if len(dictionary.phonemes_in(ipa)) > 1
             else singles).append(it)
    return pairs_out + singles


def walkthrough_items(key: str) -> list:
    """What to record for one entry: the whole line FIRST, then its words,
    then whatever sound pieces of the buildup are not yet in the family's
    own voice - pairs, then single phonemes. Missing means "not recorded by
    you": the shipped starter voice only ever fills gaps at video time.

    A single word skips the line (the word IS the line); a letter entry
    records nothing here - its sound belongs to the Sound Bank.

    Anything already in the shared banks shows as done and the studio
    resumes past it - the tenth sentence is cheaper than the first.
    """
    for text in load():
        if sentence_key(text) == key:
            kind = entry_kind(text)
            if kind == "letter":
                return []
            items = []
            if kind == "sentence":
                items.append(_line_item(text))
            items += [_word_item(w) for w in _unique_words(text)]
            items += _piece_items(text)
            return items
    raise ValueError("That sentence is not in the library any more.")


# ------------------------------------------------------------ starter packs
#
# The old levels, reborn as content. The research-backed progression (sight
# words first, then sounds, then blending, then text - see the README) used
# to be nine screens of UI; now it is sets of ordinary library entries added
# with one tap. Nothing about the pedagogy changed - only where it lives.


# Themed packs are SENTENCES, because the library is sentences: a pack about
# Paw Patrol is lines a Paw Patrol fan wants read, not an exercise dressed up
# as one. Two skill packs are the deliberate exception - letter sounds and
# nonsense sounding-out practice cannot be sentences by nature, and they are
# the mechanics the research says to drill - so they sit in their own group.
def _pack_defs() -> list:
    from gen import levels, wordlists

    try:
        own_words = [w for w in wordlists.all_words()]
    except Exception:
        own_words = []

    ladder = []
    for ch in levels.LADDER:
        ladder += ch["words"] + [ch["sentence"]]

    return [
        # ---- stories and favourites: themed sentences -------------------
        {"id": "own-words", "group": "favourites", "name": "Your word list",
         "description": "Everything from your old word list - names, "
                        "favourites, first words. The words a child already "
                        "cares about are the ones learned first.",
         "items": own_words},
        {"id": "paw-patrol", "group": "favourites", "name": "Paw Patrol",
         "description": "The pups and their lines.",
         "items": [
             "Chase is on the case.",
             "Skye is up in the sky.",
             "Marshall is all fired up.",
             "Rubble on the double.",
             "Rocky can fix it.",
             "Zuma is in the water.",
             "Ryder needs us.",
             "The pups save the day.",
             "No job is too big.",
             "No pup is too small.",
         ]},
        {"id": "veggie-tales", "group": "favourites", "name": "VeggieTales",
         "description": "Bob, Larry, and the song at the end of the show.",
         "items": [
             "Bob is a tomato.",
             "Larry is a cucumber.",
             "It is time for silly songs.",
             "God made you special.",
             "He loves you very much.",
         ]},
        {"id": "gods-world", "group": "favourites", "name": "God's world",
         "description": "Short lines of faith and thanks.",
         "items": [
             "God made the sun.",
             "God made the sea.",
             "God made the dog.",
             "God made me.",
             "God loves me.",
             "Jesus loves me.",
             "Give thanks to the Lord.",
             "The Lord is my shepherd.",
         ]},
        {"id": "family-day", "group": "favourites", "name": "Around home",
         "description": "The lines of an ordinary day.",
         "items": [
             "I love you.",
             "Time for bed.",
             "The dog wants to play.",
             "We can go to the park.",
             "What is for dinner?",
             "Come and see this.",
         ]},

        # ---- learning to sound out: the skills --------------------------
        {"id": "letters", "group": "skills", "name": "Letter sounds",
         "description": "One letter at a time, in phonics order - s a t p "
                        "i n first. Nothing to record: these use the sounds "
                        "from Setup.",
         "items": [l for l, _ in
                   levels.SATPIN + levels.SET2 + levels.SET3]},
        {"id": "ladder", "group": "skills", "name": "Building up",
         "description": "The whole journey in order: at, am, Sam, sat... "
                        "ending in whole sentences, each built only from "
                        "letters already met.",
         "items": ladder},
        {"id": "nonsense", "group": "skills", "name": "Sounding-out practice",
         "description": "Made-up words like vam and zib. They cannot be "
                        "memorised as shapes, so reading one proves the "
                        "sounding-out is real.",
         "items": list(levels.CVC_NONSENSE)},
        {"id": "letter-teams", "group": "skills", "name": "Letter teams",
         "description": "sh, ch, th, ck as one sound: ship, chat, duck.",
         "items": list(levels.DIGRAPH_WORDS)},
        {"id": "first-sentences", "group": "skills", "name": "First sentences",
         "description": "Short decodable lines: A duck sat on the rock.",
         "items": list(levels.SENTENCES)},
    ]


def packs() -> list:
    """The packs, with how much of each is already in the library."""
    have = {sentence_key(t) for t in load()}
    out = []
    for p in _pack_defs():
        keys = [sentence_key(i) for i in p["items"]]
        out.append({
            "id": p["id"], "name": p["name"], "group": p["group"],
            "description": p["description"],
            "count": len(p["items"]),
            "added": sum(1 for k in keys if k in have),
        })
    return out


def add_pack(pack_id: str) -> list:
    for p in _pack_defs():
        if p["id"] == pack_id:
            if not p["items"]:
                raise ValueError("That pack has nothing in it yet.")
            texts = load()
            seen = {sentence_key(t) for t in texts}
            for item in p["items"]:
                k = sentence_key(item)
                if k and k not in seen:
                    seen.add(k)
                    texts.append(item)
            _save(texts)
            return texts
    raise ValueError("No such pack.")


# ---------------------------------------------------------------- estimate


def estimate_seconds(keys=None, reps=3, pause=1.5) -> float:
    """Roughly how long the library video will run, without building it.

    Mirrors _library's structure with flat per-clip costs. "Pick 20 minutes"
    was the wrong control for this video: the buildups mean nobody can know
    what a length request costs in content, so the app now says what the
    chosen content costs in time instead. Rough is fine - this is a label
    on a button, not a contract - but it must track the options, or it
    teaches people to ignore it.
    """
    from gen import levels

    PH, WORD, LINE = 0.75, 0.55, 2.6
    passes = max(2, reps)
    gap = 0.12  # mean of the (now brisk) shrinking approach gaps

    def word_cost(w):
        if levels.decodable(w):
            n = len(levels.word_alignment(w))
            return passes * n * (PH + gap) + WORD + pause + 1.0
        return max(2, reps - 1) * (WORD + pause) + 1.0

    total = 1.0  # the loop pad
    for text in texts_for(keys):
        kind = entry_kind(text)
        words = _unique_words(text)
        if kind == "letter":
            total += reps * (PH + pause) + 0.6
        elif kind == "word":
            total += word_cost(words[0])
        else:
            total += sum(word_cost(w) for w in words)
            total += len(text.split()) * (WORD + pause)  # growing the line
            total += LINE + pause + 1.6                  # the read-along
    return total


# ------------------------------------------------------- read-along timing


def word_spans(audio: np.ndarray, words: list, clip_lens: list) -> list:
    """Where each word falls inside a whole-line recording, as (start, end)
    sample ranges that tile the audio exactly.

    No aligner. The isolated word clips give each word's RELATIVE length -
    same speaker, same words, so the ratios carry over - and the line
    recording gives the total. Function words are discounted because they
    compress far more in flowing speech than content words do (an isolated
    "the" is ~4x its in-sentence self). Leading and trailing room tone is
    excluded from the arithmetic but attached to the first and last word,
    so the slices concatenate back to the original audio and the picture
    can never drift from the sound.
    """
    n = len(audio)
    if not words or n == 0:
        return [(0, n)]

    env = np.abs(audio)
    thr = max(float(env.max()) * 0.06, 0.004)
    loud = np.where(env > thr)[0]
    start, end = (int(loud[0]), int(loud[-1]) + 1) if loud.size else (0, n)

    weights = []
    for i, w in enumerate(words):
        L = clip_lens[i] if i < len(clip_lens) and clip_lens[i] else 0
        wt = float(L) if L else float(max(len(_clean(w)), 2))
        if _clean(w).lower() in FUNCTION_WORDS:
            wt *= FUNCTION_DISCOUNT
        weights.append(wt)
    total = sum(weights) or 1.0

    run = 0.0
    cuts = []
    for wt in weights[:-1]:
        run += wt
        cuts.append(start + int((end - start) * run / total))
    bounds = [0] + cuts + [n]
    return list(zip(bounds[:-1], bounds[1:]))
