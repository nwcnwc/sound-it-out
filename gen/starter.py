"""Build the shipped starter voice from the developer's own recordings.

The starter voice is what a fresh install speaks with until the family
records their own: the 42 phonemes, and - so the starter packs are human
on day one - every word and line the packs contain. Nothing family-specific
goes in: the "own-words" pack is each family's private list, so it is
excluded by name.

Workflow, run from the repo:

    .venv/bin/python -m gen.starter          # report coverage, copy nothing
    .venv/bin/python -m gen.starter --copy   # copy what exists into assets/

Record whatever it reports missing the same way any content is recorded -
add the pack on the Sentences tab, press Record - then run --copy again.
The copied files are tracked and shipped (see electron-builder.yml); the
family's own recordings always beat them at lookup time (gen/voice.py).
"""

from __future__ import annotations

import shutil
import sys

from gen import sentences as slib
from gen import studio
from gen.paths import STARTER_VOICE, VOICE_DIR
from gen.voice import sentence_key


def needed() -> tuple:
    """(words, sentence texts) every shipped pack needs, deduplicated."""
    words, lines, seen = [], [], set()
    for p in slib._pack_defs():
        if p["id"] == "own-words":
            continue  # the family's private list is never shipped
        for item in p["items"]:
            kind = slib.entry_kind(item)
            if kind == "letter":
                continue  # phonemes are the starter bank's original job
            for w in slib._unique_words(item):
                if w.lower() not in seen:
                    seen.add(w.lower())
                    words.append(w)
            if kind == "sentence" and sentence_key(item) not in seen:
                seen.add(sentence_key(item))
                lines.append(item)
    return words, lines


def run(copy=False) -> dict:
    words, lines = needed()
    have_w, miss_w, have_l, miss_l = [], [], [], []

    for w in words:
        src = studio.Item(key=w.lower(), kind="word", display=w,
                          say="", length="free").path()
        (have_w if src.exists() else miss_w).append((w, src))
    for text in lines:
        src = VOICE_DIR / "sentences" / f"{sentence_key(text)}.wav"
        (have_l if src.exists() else miss_l).append((text, src))

    if copy:
        for sub, pairs in (("words", have_w), ("sentences", have_l)):
            d = STARTER_VOICE / sub
            d.mkdir(parents=True, exist_ok=True)
            for _, src in pairs:
                shutil.copy2(src, d / src.name)

    return {
        "words": len(words), "lines": len(lines),
        "have_words": len(have_w), "have_lines": len(have_l),
        "missing_words": [w for w, _ in miss_w],
        "missing_lines": [t for t, _ in miss_l],
        "copied": copy,
    }


def main():
    copy = "--copy" in sys.argv
    r = run(copy=copy)
    print(f"packs need {r['words']} words and {r['lines']} line reads")
    print(f"recorded already: {r['have_words']} words, {r['have_lines']} lines"
          + ("  -> copied into assets/starter-voice/" if copy else ""))
    if r["missing_words"]:
        print(f"\nstill to record ({len(r['missing_words'])} words):")
        print("  " + " ".join(r["missing_words"]))
    if r["missing_lines"]:
        print(f"\nstill to read whole ({len(r['missing_lines'])} lines):")
        for t in r["missing_lines"]:
            print("  " + t)
    if not r["missing_words"] and not r["missing_lines"]:
        print("\nnothing missing - the packs are fully covered.")


if __name__ == "__main__":
    main()
