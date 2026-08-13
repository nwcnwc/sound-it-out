"""Words the parent says are read WHOLE, never sounded out.

`levels.decodable()` answers whether a word CAN honestly be built up from
sounds. This list answers a different question - whether it SHOULD be - and
it wins, because the parent knows things the grapheme table does not.

    "Chase"  builds cleanly as c + ase, and is still a sight word: it is a
             cartoon dog's name, the child knows it by shape, and sounding
             it out teaches a fight rather than a word.

    "Mom"    builds. Nobody sounds out their mother's name.

That distinction matters more here than it would elsewhere. The whole
curriculum is sight words before phonics - children with Down syndrome are
typically strong visual learners with a specific weakness in phonological
awareness, so the first fifty words are learned by shape on purpose. A word
being decodable is not a reason to decode it in front of a child who has not
got there yet, and the person who knows where they have got to is not the
dictionary.

There is already a built-in half of this: levels.IRREGULAR_WORDS, 75 words
whose spelling lies badly enough that no one should sound them out - "said",
"one", "was". That list is about ENGLISH. This one is about a child, so it is
editable, and it is per family.

## Its own file, and not sight-words.txt

wordlists/read-whole.txt, empty by default.

Reusing sight-words.txt was the obvious idea and it is wrong. That list means
"show these words early" - it holds cat and dog, which is exactly right for
level 2 and exactly wrong here, because sounding out cat is the whole point
of level 5. Appearing early and never being decoded are different claims
about a word, and one file cannot make both.

So this list starts empty. A word is on it only because somebody deliberately
put it there, which is the only thing that justifies overriding the grapheme
table.
"""

from __future__ import annotations

import re

FILENAME = "read-whole.txt"

_cache = None


def _clean(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())


def load() -> set:
    """The parent's sight words, lowercased and stripped of punctuation."""
    global _cache
    if _cache is None:
        from gen.paths import WORDLISTS

        try:
            _cache = {_clean(w) for w in parse(
                (WORDLISTS / FILENAME).read_text(encoding="utf-8"))}
        except OSError:
            _cache = set()       # absent is normal: nothing is overridden
        _cache.discard("")
    return _cache


def save(words) -> list:
    """Replace the list. Returns what was written."""
    from gen.paths import WORDLISTS

    words = parse("\n".join(words)) if not isinstance(words, str) else parse(words)
    path = WORDLISTS / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Words to read WHOLE - never sounded out, however spellable they are.\n"
        "# One per line. This is the parent's override: the app decides what CAN\n"
        "# be sounded out, and this decides what should not be.\n"
        "#\n"
        "# A name, a favourite, anything the child knows by shape and would only\n"
        "# be confused by taking apart.\n"
        + "\n".join(words) + ("\n" if words else ""),
        encoding="utf-8")
    reload()
    return words


def is_sight(word: str) -> bool:
    """Should this word be shown and spoken whole, never sounded out?"""
    return _clean(word) in load()


def reload() -> set:
    """Forget the cached list - called after the parent edits it."""
    global _cache
    _cache = None
    return load()


def parse(text: str) -> list:
    """Words out of anything a human might type.

    One per line, or commas, or several to a line - all tolerated, because
    the alternative is telling somebody their list is formatted wrongly.
    """
    out, seen = [], set()
    for line in (text or "").splitlines():
        if line.strip().startswith("#"):
            continue
        for raw in re.split(r"[\s,;]+", line):
            w = raw.strip().strip(".,!?;:‘’“”'\"")
            if not w or not re.search(r"[a-z]", w, re.I):
                continue
            k = _clean(w)
            if k and k not in seen:
                seen.add(k)
                out.append(w)
    return out
