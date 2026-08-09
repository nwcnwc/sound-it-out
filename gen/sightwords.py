"""The sight-word list: words that are read WHOLE, never sounded out.

Typed in on the Sound Bank screen. A word on this list is never decomposed
into chunks or phonemes anywhere it appears: the Sentences walk-through does
not queue its sound pieces for recording, and the video shows and says it
whole - the same treatment the research-backed sight-word packs give every
word. This is the parent's override: `decodable()` decides what CAN honestly
be sounded out, this list decides what SHOULD NOT be, and the parent gets
the last word ("Chase" the pup is a sight word even though c-a-se builds).

Distinct from wordlists/sight-words.txt, which is the legacy Words-tab
CONTENT list (what appears in level videos). This file changes BEHAVIOUR
for words however they arrive - typed into a sentence, or from a pack.
"""

from __future__ import annotations

import re

from gen.paths import WORDLISTS

FILE_NAME = "whole-words.txt"

HEADER = (
    "# Sight words - read whole, never sounded out.\n"
    "# One word per line (or several on a line). Lines starting with # are\n"
    "# notes. Edited from the Sound Bank screen in the app.\n"
)

_SPLIT = re.compile(r"[\s,;]+")


def _path():
    return WORDLISTS / FILE_NAME


def _clean(word: str) -> str:
    return word.strip(".,!?;:‘’“”'\"")


def load_text() -> str:
    """The file as typed, minus the header - what the textarea shows."""
    p = _path()
    if not p.exists():
        return ""
    lines = [l for l in p.read_text(encoding="utf-8").splitlines()
             if not l.startswith("#")]
    return "\n".join(lines).strip()


def parse(text: str) -> list:
    """The words in some typed text, in order, de-duplicated."""
    out, seen = [], set()
    for line in (text or "").splitlines():
        if line.strip().startswith("#"):
            continue
        for raw in _SPLIT.split(line):
            w = _clean(raw)
            if not w or not any(c.isalpha() for c in w):
                continue
            k = w.lower()
            if k not in seen:
                seen.add(k)
                out.append(w)
    return out


def save(text: str) -> list:
    """Store what was typed; returns the words it parsed to."""
    words_ = parse(text)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEADER + "\n".join(words_) + ("\n" if words_ else ""),
                 encoding="utf-8")
    return words_


def words() -> set:
    """Every sight word, lowercased, for membership tests."""
    return {w.lower() for w in parse(load_text())}


def is_sight(word: str) -> bool:
    return _clean(word).lower() in words()
