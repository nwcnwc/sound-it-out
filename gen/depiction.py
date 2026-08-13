"""How each word is shown: which character, doing what, with what object.

The realisation this encodes is that a small cast carries most of the
vocabulary. "jump", "go" and "stop" are not three drawings - they are one
character in three poses, and the same three poses on a different character
carry them again. Forty unrelated pictograms becomes six characters and a
pose library, which is both cheaper to make and a better thing to watch: a
child gets a consistent world with characters they recognise, instead of
forty strangers.

Four ways a word can be shown, and they are not interchangeable:

    ACTOR    a character performing it            go, jump, stop, help
    OBJECT   a thing, drawn plainly               cup, ball, shoe, milk
    RELATION two things in an arrangement         in, on, same, different
    NONE     nothing - the word form alone        what, why, who, when

NONE is a real answer and not a gap. Question words have no concrete
referent; AAC boards give them arbitrary symbols that must themselves be
taught, which in a reading video means adding a second thing to learn in
order to teach the first. The word gets the screen to itself.

The pose names below are the commission brief. Every ACTOR word resolves to
a pose in POSES, so the number of drawings needed is len(POSES) per
character, not one per word.
"""

from __future__ import annotations

ACTOR, OBJECT, RELATION, NONE = "actor", "object", "relation", "none"

# The cast. Small on purpose - every character added multiplies the drawing
# work by the size of the pose library.
CAST = ("dog", "cat", "boy", "girl", "mom", "dad", "baby")

# The pose library. A word is (character, pose), so these are what actually
# get drawn and rigged.
POSES = {
    "walk":     "mid-stride, moving off",
    "run":      "faster stride, leaning forward",
    "halt":     "stopped dead, front foot planted, palm up if handed",
    "jump":     "both feet off the ground, mid-air",
    "sit":      "seated, settled",
    "sleep":    "lying down, eyes closed",
    "eat":      "food to mouth",
    "reach_up": "stretched upward for something above",
    "crouch":   "low to the ground, reaching down",
    "hold_out": "offering or asking, hand extended toward the viewer",
    "take":     "hand closing on an object",
    "place":    "hand setting an object down",
    "look":     "head turned, hand shading the eyes",
    "wave":     "arm raised, greeting or calling",
    "turn":     "mid-rotation, one shoulder coming round",
    "point_self":  "pointing at own chest",
    "point_out":   "pointing at the viewer",
    "point_other": "pointing off to another character",
    "point_down":  "pointing at a spot on the ground",
    "empty_hands": "hands open and empty, plate pushed away",
    "build":    "hands working on something being made",
    "decline":  "head turned away, palm out, refusing",
}

# word -> (kind, detail)
#
# For ACTOR the detail is (pose, preferred character or None for any).
# For OBJECT it is the icon name. For RELATION, a short description of the
# arrangement. For NONE, why.
WORDS = {
    # -- Universal Core 36 ------------------------------------------------
    "go":        (ACTOR, ("run", "dog")),
    "stop":      (ACTOR, ("halt", "dog")),
    "up":        (ACTOR, ("reach_up", "boy")),
    "open":      (ACTOR, ("take", "boy")),
    "put":       (ACTOR, ("place", "girl")),
    "get":       (ACTOR, ("take", "girl")),
    "more":      (ACTOR, ("hold_out", "boy")),
    "want":      (ACTOR, ("hold_out", "girl")),
    "help":      (ACTOR, ("wave", "mom")),
    "look":      (ACTOR, ("look", "boy")),
    "make":      (ACTOR, ("build", "dad")),
    "turn":      (ACTOR, ("turn", "girl")),
    "finished":  (ACTOR, ("empty_hands", "boy")),
    "here":      (ACTOR, ("point_down", "girl")),
    "not":       (ACTOR, ("decline", "boy")),
    "good":      (ACTOR, ("wave", "dad")),
    "do":        (ACTOR, ("build", "dad")),
    "like":      (ACTOR, ("hold_out", "girl")),
    "I":         (ACTOR, ("point_self", "boy")),
    "you":       (ACTOR, ("point_out", "boy")),
    "he":        (ACTOR, ("point_other", "boy")),
    "she":       (ACTOR, ("point_other", "girl")),
    "can":       (ACTOR, ("jump", "dog")),

    "in":        (RELATION, "ball dropping into a box"),
    "on":        (RELATION, "ball resting on top of a box"),
    "same":      (RELATION, "two identical balls side by side"),
    "different": (RELATION, "a ball and a cup side by side"),
    "all":       (RELATION, "every ball inside the box"),
    "some":      (RELATION, "part of the balls inside the box"),

    "it":        (NONE, "no referent - stands for whatever was just named"),
    "that":      (NONE, "deictic; depends entirely on context"),
    "what":      (NONE, "question word, no concrete referent"),
    "when":      (NONE, "question word, no concrete referent"),
    "where":     (NONE, "question word, no concrete referent"),
    "who":       (NONE, "question word, no concrete referent"),
    "why":       (NONE, "question word, no concrete referent"),

    # -- the cast, as words in their own right ----------------------------
    "dog":    (ACTOR, ("walk", "dog")),
    "cat":    (ACTOR, ("walk", "cat")),
    "boy":    (ACTOR, ("walk", "boy")),
    "girl":   (ACTOR, ("walk", "girl")),
    "mommy":  (ACTOR, ("wave", "mom")),
    "daddy":  (ACTOR, ("wave", "dad")),
    "baby":   (ACTOR, ("sit", "baby")),

    # -- actions the cast carries ----------------------------------------
    "jump":   (ACTOR, ("jump", "dog")),
    "run":    (ACTOR, ("run", "boy")),
    "sit":    (ACTOR, ("sit", "cat")),
    "sleep":  (ACTOR, ("sleep", "cat")),
    "eat":    (ACTOR, ("eat", "girl")),
    "down":   (ACTOR, ("crouch", "boy")),
    "come":   (ACTOR, ("walk", "dog")),
    "play":   (ACTOR, ("jump", "girl")),

    # -- objects ----------------------------------------------------------
    "ball": (OBJECT, "ball"), "cup": (OBJECT, "cup"), "car": (OBJECT, "car"),
    "bed": (OBJECT, "bed"), "book": (OBJECT, "book"), "shoe": (OBJECT, "shoe"),
    "hat": (OBJECT, "hat"), "bus": (OBJECT, "bus"), "sun": (OBJECT, "sun"),
    "milk": (OBJECT, "milk"), "door": (OBJECT, "door"), "home": (OBJECT, "home"),
    "hand": (OBJECT, "hand"), "eye": (OBJECT, "eye"), "bath": (OBJECT, "bath"),
    "truck": (OBJECT, "truck"), "boat": (OBJECT, "boat"), "big": (RELATION,
        "two balls, one much larger"),
    "little": (RELATION, "two balls, one much smaller"),
}


# Poses that are a MOTION and need a frame cycle. Everything else is one
# drawing held still - a child looking at "sleep" does not need it to loop.
ANIMATED_POSES = {"walk", "run", "jump", "turn", "wave", "eat"}


def kind(word: str) -> str:
    e = WORDS.get(word)
    return e[0] if e else NONE


def poses_needed(character: str) -> set:
    """Poses this character must be drawn in, given the word list."""
    return {d[0] for k, d in WORDS.items()
            if k == ACTOR and d[1] == character}


def drawings() -> list:
    """Every distinct (character, pose, animated) the word list requires.

    This is the commission brief: its length is the number of things that
    have to be drawn, and the animated ones are the only ones needing a
    frame cycle rather than a single pose.
    """
    seen = {}
    for w, (k, d) in WORDS.items():
        if k != ACTOR:
            continue
        pose, who = d
        seen.setdefault((who, pose), []).append(w)
    return sorted((c, p, p in ANIMATED_POSES, sorted(ws))
                  for (c, p), ws in seen.items())


def summary() -> dict:
    counts = {}
    for w, (k, _) in WORDS.items():
        counts[k] = counts.get(k, 0) + 1
    return counts
