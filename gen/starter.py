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
Or generate the gaps from the developer's cloned voice:

    .venv/bin/python -m gen.starter --copy --generate

which speaks every missing word, line, and magic-e rime with the slow
high-quality clone model. The rimes matter beyond the packs: the buildup
says "ase" as one sound /eɪs/, which is not among the 42 phonemes, so
every rime the spelling rules can produce ships as a clip - that is what
lets arbitrary magic-e words build up without a synthesiser in the app.

The copied files are tracked and shipped (see electron-builder.yml); the
family's own recordings always beat them at lookup time (gen/voice.py).
"""

from __future__ import annotations

import shutil
import sys

import numpy as np
import soundfile as sf

from gen import sentences as slib
from gen import studio
from gen.paths import SOUNDS, STARTER_VOICE, VOICE_DIR
from gen.soundout import SR, tidy_word
from gen.voice import _safe, sentence_key


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
    have_r, miss_r = [], []

    for w in words:
        src = studio.Item(key=w.lower(), kind="word", display=w,
                          say="", length="free").path()
        (have_w if src.exists() else miss_w).append((w, src))
    for text in lines:
        # THROUGH the item, never a hand-built path: the studio encodes keys
        # on the way to disk (_safe turns "_" into "u005f"), and a hand-built
        # path here reported every recorded line as missing.
        src = slib._line_item(text).path()
        (have_l if src.exists() else miss_l).append((text, src))
    for spelling, ipa in all_magic_e():
        src = VOICE_DIR / SOUNDS / f"{_safe(ipa)}.wav"
        (have_r if src.exists() else miss_r).append((spelling, src))

    if copy:
        for sub, pairs in (("words", have_w), ("sentences", have_l),
                           (SOUNDS, have_r)):
            d = STARTER_VOICE / sub
            d.mkdir(parents=True, exist_ok=True)
            for _, src in pairs:
                shutil.copy2(src, d / src.name)

    return {
        "words": len(words), "lines": len(lines), "magic-e": len(all_magic_e()),
        "have_words": len(have_w), "have_lines": len(have_l),
        "have_rimes": len(have_r),
        "missing_words": [w for w, _ in miss_w],
        "missing_lines": [t for t, _ in miss_l],
        "missing_rimes": [s for s, _ in miss_r],
        "copied": copy,
    }


def all_magic_e() -> list:
    """Every (spelling, ipa) rime the magic-e rule can produce.

    The spelling doubles as what the clone is asked to SAY - "ase", "ike",
    "ome" read aloud are the rimes themselves - and the ipa is the filename
    the phoneme lookup asks for.
    """
    from gen.levels import SINGLE_LETTER_GRAPHEMES, LONG_VOWELS, MAGIC_E, MAGIC_E_CONS

    out = []
    for v in "aeiou":
        for c in "bcdfgklmnpstz":
            spelling = f"{v}{c}e"
            if MAGIC_E.search(spelling):
                out.append((spelling,
                            LONG_VOWELS[v] + MAGIC_E_CONS.get(c, SINGLE_LETTER_GRAPHEMES[c])))
    return out


def generate_missing(profile="mom", variant="english", log=print) -> dict:
    """Speak every gap with the developer's cloned voice and stage it.

    Slow on purpose: these ship to every install, so they get the
    high-quality model, hours and all. Each clip is leveled at lookup
    time like everything else; words get the same conservative tidy-up
    as any generated word. A clip that comes back silent or absurdly
    long is reported and NOT written - a bad shipped default is worse
    than a missing one.
    """
    from gen import clone

    prof = clone.PROFILES / profile
    words, lines = needed()
    jobs = []
    for w in words:
        dest = STARTER_VOICE / "words" / f"{_safe(w.lower())}.wav"
        if not dest.exists():
            jobs.append(("word", w, dest))
    for text in lines:
        dest = STARTER_VOICE / "sentences" / f"{_safe(sentence_key(text))}.wav"
        if not dest.exists():
            jobs.append(("line", text, dest))
    # Rimes are deliberately NOT generated: an isolated sound is what
    # cloning does worst, and a wrong sound teaches a wrong thing. They are
    # recorded live in Setup (part "magic-e") like the 42 phonemes, and
    # --copy stages them from the developer's own bank.

    bad, done = [], 0
    for i, (kind, text, dest) in enumerate(jobs):
        log(f"[{i + 1}/{len(jobs)}] {kind}: {text}")
        a = clone.synthesize(text, prof, variant=variant)
        if kind != "line":
            a = tidy_word(a)
        seconds = len(a) / SR
        peak = float(np.abs(a).max()) if a.size else 0.0
        limit = 12.0 if kind == "line" else 4.0
        if peak < 0.01 or seconds < 0.15 or seconds > limit:
            bad.append((kind, text, round(seconds, 2), round(peak, 3)))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        sf.write(dest, a.astype("float32"), SR)
        done += 1
    return {"generated": done, "rejected": bad, "jobs": len(jobs)}


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
    if r["missing_rimes"]:
        print(f"\nrimes still to record live, in Setup ({len(r['missing_rimes'])}):")
        print("  " + " ".join(r["missing_rimes"]))
    if not r["missing_words"] and not r["missing_lines"] and not r["missing_rimes"]:
        print("\nnothing recorded is missing - the packs are fully covered.")

    if "--generate" in sys.argv:
        g = generate_missing()
        print(f"\ngenerated {g['generated']} of {g['jobs']} clips with the cloned voice")
        for kind, text, secs, peak in g["rejected"]:
            print(f"  REJECTED {kind} '{text}': {secs}s, peak {peak}")


if __name__ == "__main__":
    main()
