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


def status() -> list:
    """Every sentence, with what is recorded and what is still to do."""
    out = []
    for text in load():
        words = _unique_words(text)
        missing = [w for w in words if not _word_item(w).done()]
        line_done = _line_item(text).done()
        out.append({
            "key": sentence_key(text),
            "text": text,
            "words": len(words),
            "missing": missing,
            "lineRecorded": line_done,
            "ready": not missing and line_done,
        })
    return out


def walkthrough_items(key: str) -> list:
    """What to record for one sentence: its words, then the whole line.

    Words already in the shared bank show as done and the studio resumes
    past them - this is what makes the tenth sentence cheaper than the
    first. The line comes last so the words are fresh in her voice when
    she reads them joined up.
    """
    for text in load():
        if sentence_key(text) == key:
            return [_word_item(w) for w in _unique_words(text)] + [_line_item(text)]
    raise ValueError("That sentence is not in the library any more.")


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
