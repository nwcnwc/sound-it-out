"""Levels whose content is not written in advance.

Levels 1-9 read from fixed lists, which means every family gets the same
videos and the whole library could - and eventually did - get recorded by
hand. That made voice cloning pointless: measured against a complete recording
session it was generating ten sentences.

These three levels invert that. Their content depends on what the parent
pastes in, what names they typed into their word list, and how far the child
has got, so it cannot be enumerated, cannot be pre-recorded, and is different
for every family. That is what the cloned voice is for: her voice saying
things she never sat down and recorded.

## No language model

Nothing here generates text with a model. Everything is either text the parent
supplied, or a template filled from their own word list, or a sentence chosen
from a curated bank and filtered by which letters have been taught. That is a
deliberate constraint, and it costs less than it sounds: a child learning to
read needs "Sam sat on the mat", not prose.

It also keeps the app honest about decodability. A model would happily produce
a sentence full of letters the child has never met, which is precisely the
thing a phonics scheme must not do. A filter cannot.

## Determinism

Output is stable for the same input, because generated audio is cached on
disk. Sentences are shuffled with a seed derived from the input itself, so a
parent who adds a name gets different sentences, and one who does not gets the
same video without re-synthesising an hour of speech.
"""

from __future__ import annotations

import hashlib
import random
import re

from gen import wordlists

# Long enough to be worth watching, short enough that a pasted chapter does not
# become a nine-hour render. The minutes setting trims the video; this bounds
# the synthesis, which is the part that costs.
MAX_SENTENCES = 40

# A sentence a beginner can hold in their head. Longer lines are split at
# clause boundaries rather than dropped.
MAX_WORDS = 12


# ------------------------------------------------------------ pasted text


def split_sentences(text: str) -> list:
    """Break arbitrary text into readable lines.

    Deliberately simple. A real sentence tokeniser would handle "Dr." and
    "e.g." correctly, and would also drag in a dependency and a model file for
    a job whose failure mode here is one line reading slightly long.
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []

    out = []
    for raw in re.split(r"(?<=[.!?])\s+", text):
        line = raw.strip()
        if not line:
            continue
        words = line.split()
        if len(words) <= MAX_WORDS:
            out.append(line)
            continue
        # Too long to show at once. Break at punctuation the reader would
        # breathe at, and only chop mid-phrase for whatever is still too long
        # after that - splitting every over-long line by word count put breaks
        # in the middle of "across the / whole field".
        for part in re.split(r"(?<=[,;:])\s+", line):
            part = part.strip()
            if not part:
                continue
            pw = part.split()
            if len(pw) <= MAX_WORDS:
                out.append(part)
                continue
            for i in range(0, len(pw), MAX_WORDS):
                out.append(" ".join(pw[i:i + MAX_WORDS]))
    return out[:MAX_SENTENCES]


# -------------------------------------------------- their own word list


# Filled from the parent's own groups. Every slot is a word they typed, so the
# result is about their family - which is the entire point, and is also what
# the research on reading and Down syndrome keeps pointing at: start with words
# the child already cares about.
#
# Kept grammatically simple on purpose. These are read by a child sounding out,
# not parsed for style.
TEMPLATES = [
    ("{person} can see the {thing}.", ("person", "thing")),
    ("{person} has a {thing}.", ("person", "thing")),
    ("I can see {person}.", ("person",)),
    ("{person} and {person2} can go.", ("person", "person2")),
    ("The {thing} is for {person}.", ("thing", "person")),
    ("{person} likes the {thing}.", ("person", "thing")),
    ("Here is the {thing}.", ("thing",)),
    ("{person} can go to {person2}.", ("person", "person2")),
    ("I like my {thing}.", ("thing",)),
    ("{person} sees my {thing}.", ("person", "thing")),
]


def _groups_named(groups, *names):
    for g in groups:
        if any(n in g.name.lower() for n in names):
            return [w for w, _ in g.words]
    return []


def from_wordlist(groups=None, limit=MAX_SENTENCES) -> list:
    """Sentences built from the names and things the parent typed in.

    Returns [] rather than raising when there is nothing to work with: a family
    who has not filled in the People group yet should see the level explain
    itself, not a traceback.
    """
    groups = groups if groups is not None else wordlists.load()
    people = _groups_named(groups, "people", "family")
    things = _groups_named(groups, "home", "thing", "toy")
    # Characters are people too, and for a child who cares about them they may
    # be the strongest words in the list.
    people += _groups_named(groups, "paw", "character")

    if not people or not things:
        return []

    seed = hashlib.sha256(
        ("|".join(sorted(people)) + "//" + "|".join(sorted(things))).encode()
    ).hexdigest()
    rng = random.Random(seed)

    out, seen = [], set()
    # Round-robin through the templates so the same shape does not repeat
    # three times before the second one appears.
    order = list(TEMPLATES)
    rng.shuffle(order)
    for i in range(limit * 3):
        text, slots = order[i % len(order)]
        person = rng.choice(people)
        fill = {"person": person, "thing": rng.choice(things)}
        if "person2" in slots:
            others = [p for p in people if p != person]
            if not others:
                continue
            fill["person2"] = rng.choice(others)
        line = text.format(**fill)
        if line.lower() in seen:
            continue
        seen.add(line.lower())
        out.append(line)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------- the growing story


# The story, written stage by stage against the letters level 3 actually
# teaches: SATPIN, then SET2 (m d g o c k), then SET3 (e u r h b f).
#
# Written INSIDE those sets rather than filtered against them afterwards. The
# first attempt was ordinary decodable text filtered by taught letters, and it
# collapsed - three lines of twenty-four survived the whole ladder, because
# natural sentences reach for "the", "run", "big" long before e, u, r and b are
# taught. A growing story has to be composed within each stage's alphabet or it
# does not grow at all.
#
# Which letters a line needs is still derived from the line itself, so a line
# added to the wrong stage is caught rather than trusted.
#
# Note "the" cannot appear until stage 3: h and e are both in SET3. Stage 1 and
# 2 use "a" instead, which is why the early lines read the way they do.
STORY = [
    # Stage 1 - s a t p i n. Thin on purpose; six letters is not much of an
    # alphabet, and pretending otherwise would put undecodable words in front
    # of a child in their first week.
    "Sit.",
    "Sit in it.",
    "A pin.",
    "It is a pin.",
    "Tip it in.",
    "A pan is tan.",
    "Sip it.",
    "It is tin.",

    # Stage 2 - adds m d g o c k. Sam and the animals arrive, and with them
    # something that behaves like a story.
    "Sam sat.",
    "Sam sat on a mat.",
    "A cat sat on Sam.",
    "Sam is mad.",
    "A dog is in it.",
    "A dog can dig.",
    "Sam got a cat.",
    "Sam and a dog.",
    "A cat can nap.",
    "Sam pats a cat.",
    "A cat sat on a cot.",
    "Sam is sad.",
    "Dad got a mop.",
    "Dad can mop it.",
    "A dog is on top.",
    "Sam can not stop.",
    "A cat naps on a cot.",
    "Sam and Dad.",

    # Stage 3 - adds e u r h b f. "the" becomes possible, and so does most of
    # ordinary early reading.
    "The dog ran.",
    "The cat is red.",
    "Sam fed the cat.",
    "The dog had a bed.",
    "Sam had a red hat.",
    "The dog hid the hat.",
    "Sam ran to the dog.",
    "The hat is in the mud.",
    "Dad got the hat.",
    "The hat is red.",
    "Sam put it in the sun.",
    "The cat sat in the sun.",
    "The dog sat in the sun.",
    "Sam had a big hug.",
    "The cat and the dog nap.",
    "Sam is not sad.",
]


def _letters(text: str) -> set:
    return set(re.sub(r"[^a-z]", "", text.lower()))


def taught_letters(stage=None) -> set:
    """Every letter taught by the end of `stage` (1, 2 or 3).

    These are level 3's own letter sets, which is what "has been taught"
    actually means in this app. The four-chapter ladder was the wrong source:
    it teaches ten letters total, so a story filtered against it never got past
    its opening lines.
    """
    from gen import levels

    sets = [levels.SATPIN, levels.SET2, levels.SET3]
    n = len(sets) if stage is None else max(1, min(int(stage), len(sets)))
    out = {"a"}  # both a letter and a word, taught from the start
    for group in sets[:n]:
        out |= {letter for letter, _ in group}
    return out


def story_so_far(known=None, stage=None, limit=None) -> list:
    """The story as far as it can be read with the letters taught so far.

    The point of the level: the same story extends as the child learns more
    letters, so it is never a wall of words they cannot decode and never stays
    still either. A line is included only when every letter in it has been
    taught - which is a filter, not a judgement, and so cannot be wrong the way
    a generated sentence could be.
    """
    known = set(known) if known is not None else taught_letters(stage)
    out = [line for line in STORY if _letters(line) <= known]
    # No default cap. The story is curated and finite, and truncating it
    # silently at MAX_SENTENCES hid two lines with nothing to say so.
    return out[:limit] if limit else out


def story_progress(stage=None) -> dict:
    """How much of the story is reachable, for showing on screen."""
    known = taught_letters(stage)
    usable = story_so_far(known)
    return {
        "letters": "".join(sorted(known)),
        "lines": len(usable),
        "total": len(STORY),
    }
