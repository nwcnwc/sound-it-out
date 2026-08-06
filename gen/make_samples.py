"""Generate sample videos for feedback.

Run:  .venv/bin/python -m gen.make_samples
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen.soundout import (  # noqa: E402
    SAMPLES, THEMES, Segment, Theme, Voice, build_video, whole,
)

# ---------------------------------------------------------------- content

# Level 1 is sight words, per the Down syndrome reading research: whole-word
# recognition first, phonics only after ~50 confident sight words. Personally
# meaningful words are explicitly recommended - hence Paw Patrol.
#
# Colours echo each pup's kit. No copyrighted art, just the association.
PAW_PATROL = [
    ("Chase", "#4da6ff"),      # police - blue
    ("Marshall", "#ff5a4d"),   # fire - red
    ("Skye", "#ff8fc7"),       # aviator - pink
    ("Rubble", "#ffd23f"),     # construction - yellow
    ("Rocky", "#6fcf6f"),      # recycling - green
]

# Preview of a later level: sounding out with letter highlighting.
# (grapheme, IPA phoneme) - IPA is fed to Kokoro directly so the sound is
# exact rather than whatever the model guesses from the spelling.
# Continuant-heavy words first: m, s, f, n, l can all be held and drawn out,
# so they demonstrate blending best. Stops (p, t, k, b, d, g) physically
# cannot be sustained - "pin" is kept last so its /p/ can be judged directly.
CVC = [
    [("m", "m"), ("a", "æ"), ("n", "n")],
    [("s", "s"), ("a", "æ"), ("t", "t")],
    [("p", "p"), ("i", "ɪ"), ("n", "n")],
]

SENTENCE = "Chase is on the case."


# -------------------------------------------------------------- builders


def sight_words(v: Voice, words, reps=2):
    """Level 1: show the whole word, say it, repeat. No segmenting."""
    segs = []
    for word, _ in words:
        audio = v.say(word)
        for i in range(reps):
            segs.append(whole(word, audio, pad=1.4 if i < reps - 1 else 2.0))
    return segs


def sound_out(v: Voice, words, reps=2):
    """Later level: highlight each grapheme as its sound plays, then blend."""
    segs = []
    for parts in words:
        word = "".join(g for g, _ in parts)
        blended = v.say(word, speed=0.85)
        for _ in range(reps):
            for idx, (_, ipa) in enumerate(parts):
                shown = [(g, i == idx) for i, (g, _) in enumerate(parts)]
                segs.append(Segment(shown, v.say(ipa, phonemes=True), pad=0.28))
            segs.append(whole(word, blended, pad=1.6))
    return segs


def sentence(v: Voice, text):
    """Highlight each word as it is read, then read the whole thing."""
    words = text.split()
    segs = []
    for idx, w in enumerate(words):
        parts = []
        for i, other in enumerate(words):
            if i:
                parts.append((" ", False))
            parts.append((other, i == idx))
        segs.append(Segment(parts, v.say(w.strip(".,!?")), pad=0.35, scale=0.9))
    segs.append(whole(text, v.say(text, speed=0.9), pad=2.0, scale=0.9))
    return segs


# ------------------------------------------------------------------ main


def main():
    SAMPLES.mkdir(exist_ok=True)
    v = Voice(voice="af_heart", speed=0.9)

    colors = {w: c for w, c in PAW_PATROL}
    made = []

    # Same content, three looks - so the choice is about the look alone.
    for name in ("night", "paper", "contrast"):
        base = THEMES[name]
        theme = Theme(base.name, base.bg, base.fg, base.highlight, base.dim,
                      base.weight, colors)
        out = SAMPLES / f"0{len(made) + 1}-pawpatrol-{name}.mp4"
        build_video(sight_words(v, PAW_PATROL), theme, out)
        made.append(out)
        print(f"  built {out.name}")

    # Mechanic previews, in the front-runner theme.
    night = THEMES["night"]
    for label, segs in (
        ("sounding-out", sound_out(v, CVC)),
        ("sentence", sentence(v, SENTENCE)),
    ):
        out = SAMPLES / f"0{len(made) + 1}-{label}.mp4"
        build_video(segs, night, out)
        made.append(out)
        print(f"  built {out.name}")

    return made


if __name__ == "__main__":
    print("Generating samples...")
    for p in main():
        print(p)
