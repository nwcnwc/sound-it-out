"""Tests for fitting a video to the minutes that were asked for, and for the
shape of the blending buildup.

Both exist because of the same generated video: five minutes was requested,
nine came out, and in the middle of it a synthesised voice said "sat" and was
immediately followed by the parent's recording saying "sat" - the one place a
voice seam is impossible to miss. The length bug was `//` rounding down to a
floor of one whole pass, so any level whose single pass overran the request
shipped the whole pass; the seam was the full-word blend being synthesised
even though the recorded word played right after it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import levels, service  # noqa: E402
from gen.soundout import SR, Segment  # noqa: E402


class StubVoice:
    """Deterministic clip lengths, and a record of every blend requested."""

    def __init__(self):
        self.blends = []

    def word(self, text, slow=False):
        return np.zeros(int(SR * 0.4), dtype="float32")

    def phoneme(self, ipa):
        return np.zeros(int(SR * 0.2), dtype="float32")

    def blend(self, ipas):
        self.blends.append(list(ipas))
        return np.zeros(int(SR * 0.3), dtype="float32")

    def sentence(self, text, tempo=0.68):
        return np.zeros(int(SR * 1.0), dtype="float32")

    def can_say(self, text):
        # The stub can say anything - this test is about where a level ENDS,
        # not about what a particular bank happens to hold.
        return True


class FakeGroup:
    def __init__(self, name, words):
        self.name, self.words = name, words


def fake_wordlist(*_a, **_k):
    return [
        FakeGroup("Paw Patrol", [("Chase", "#00a"), ("Skye", None)]),
        FakeGroup("People", [("Mom", None)]),
        FakeGroup("Home", [("dog", None)]),
    ]


def build(level, monkeypatch, reps=3):
    monkeypatch.setattr(levels.wordlists, "load", fake_wordlist)
    return levels.build(level, StubVoice(), {"reps": reps, "pauseSeconds": 1.5})


# ------------------------------------------------------------ item marking


def test_every_level_ends_on_an_item_boundary(monkeypatch):
    """Trimming keeps only whole items, so a level whose final segment is not
    marked would silently lose its tail every time it was trimmed."""
    for level in range(1, 10):
        segs = build(level, monkeypatch)
        assert segs, f"level {level} built nothing"
        assert segs[-1].item_end, f"level {level}'s last item is unmarked"


# ---------------------------------------------------------------- trimming


def seg(seconds, end=False):
    return Segment([("x", False)], np.zeros(int(SR * seconds), dtype="float32"),
                   item_end=end)


def ten_items():
    # ten items of 10s each: [5s, 5s-with-end] * 10
    out = []
    for _ in range(10):
        out += [seg(5), seg(5, end=True)]
    return out


def total(segs):
    return sum(s.duration for s in segs)


def test_trim_cuts_at_the_nearest_item_boundary():
    assert total(service._whole_items_upto(ten_items(), 36)) == 40
    assert total(service._whole_items_upto(ten_items(), 34)) == 30


def test_trim_never_cuts_mid_item():
    out = service._whole_items_upto(ten_items(), 36)
    assert out[-1].item_end


def test_a_request_shorter_than_one_item_still_makes_a_video():
    assert total(service._whole_items_upto(ten_items(), 2)) == 10


def test_topping_up_may_add_nothing():
    """The remainder of a filled request can be smaller than any item."""
    assert service._whole_items_upto(ten_items(), 2, allow_empty=True) == []


def test_unmarked_segments_are_returned_untouched():
    """If no boundary was ever marked, trimming must not empty the level."""
    plain = [seg(5), seg(5)]
    assert service._whole_items_upto(plain, 3) == plain


# ------------------------------------------------------- the voice seam


def test_the_completed_word_is_never_a_synthesised_blend(monkeypatch):
    """The blend of every one of a word's sounds IS the word, and the recorded
    word plays immediately after - synthesising it too said the same thing
    twice in two different voices, back to back."""
    monkeypatch.setattr(levels.wordlists, "load", fake_wordlist)
    v = StubVoice()
    levels.build(6, v, {"reps": 3, "pauseSeconds": 1.5})
    words = {w for ch in levels.LADDER for w in ch["words"]}
    full = {tuple(p for _, p in levels.spell(w)) for w in words}
    for b in v.blends:
        assert tuple(b) not in full, f"full word {b} was synthesised as a blend"
    assert v.blends, "halfway blends (sa on the way to sat) must remain"


# ------------------------------------------------------- the approach


def test_the_gaps_shrink_pass_by_pass(monkeypatch):
    """Successive blending: the sounds are said again and again with the gap
    closing, so they audibly become the word instead of being replaced by it."""
    pause = 1.5
    segs = levels._approach(StubVoice(), levels.spell("sat"), pause, passes=3)
    assert len(segs) == 9
    gaps = [segs[i * 3].pad for i in range(2)]
    assert gaps[0] > gaps[1]
    # WITHIN-word gaps are brisk: a fraction of the between-words pause,
    # never the pause itself - sounding out at 1.5s a beat was a crawl.
    assert abs(gaps[0] - levels._approach_start(3)) < 1e-6
    assert gaps[0] <= 0.5
    # more passes start wider - the count IS the pacing control
    assert levels._approach_start(4) > levels._approach_start(3) > \
        levels._approach_start(2)
    # ...each round ends with a breath, so passes read as separate attempts
    assert segs[2].pad > segs[0].pad
    assert segs[5].pad > segs[3].pad
    # ...and the FINAL pass has no gaps at all: the sounds touch, joined by
    # crossfades, with one held breath before the whole word answers.
    assert segs[6].pad == 0 and segs[7].pad == 0
    assert segs[8].pad == pytest.approx(0.7)


def test_each_pass_still_sweeps_the_highlight_left_to_right(monkeypatch):
    segs = levels._approach(StubVoice(), levels.spell("sat"), 1.5, passes=2)
    for p in range(2):
        for j in range(3):
            parts = segs[p * 3 + j].parts
            assert [on for _, on in parts] == [i == j for i in range(3)]


# ------------------------------------------------- the blend hears the sound
#
# Round 3 of "Ezra" lit r, then a, with nothing audible under either, while
# the same two clips sounded fine in rounds 1 and 2. The cause was not the
# recordings: their sound simply started a third of a second in, behind a
# breath too loud for content() to strip, and the blend's cap is 0.40s - so
# the window it kept was the breath. The longer rounds reached past it.


class LateVoice:
    """A recording whose sound starts late, behind an audible breath."""

    def __init__(self, lead=0.38, lead_amp=0.15):
        self.lead, self.lead_amp = lead, lead_amp

    def _clip(self):
        rng = np.random.default_rng(7)
        breath = rng.uniform(-self.lead_amp, self.lead_amp,
                             int(self.lead * SR)).astype("float32")
        t = np.arange(int(0.45 * SR)) / SR
        sound = (np.sin(2 * np.pi * 180 * t) * 0.9).astype("float32")
        return np.concatenate([breath, sound])

    def phoneme(self, ipa):
        return self._clip()

    def word(self, text, slow=False):
        return np.zeros(int(SR * 0.4), dtype="float32")

    def blend(self, ipas):
        return np.zeros(int(SR * 0.3), dtype="float32")

    def sentence(self, text, tempo=0.68):
        return np.zeros(int(SR * 1.0), dtype="float32")


def _rms(a):
    return float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0


def test_a_sound_that_starts_late_is_still_heard_in_the_blend():
    voice = LateVoice()
    clipped = levels._hard_clip(voice, "m", 0.40)
    # the window kept must be mostly the sound, not the breath in front of
    # it: the breath's own level is 0.15/sqrt(3), the sound's is 0.9/sqrt(2)
    assert _rms(clipped) > 0.5 * (0.9 / np.sqrt(2)), _rms(clipped)
    assert _rms(clipped) > 5 * (0.15 / np.sqrt(3))


def test_every_slice_of_the_touching_pass_has_a_sound_in_it():
    """The whole point of the final pass is that all of it is audible."""
    segs = levels._touching(LateVoice(), levels.spell("Sam"))
    assert len(segs) == 3
    for seg in segs:
        assert _rms(seg.audio) > 0.3, [_rms(s.audio) for s in segs]


def test_a_swelling_vowel_is_not_slid_forward():
    """The shape this must NOT touch: an /iː/ that fades in over half a
    second starts late too, and cutting its swell is how lollipop lost its
    i. A swell rises into its sound; a breath sits flat and then stops."""
    t = np.arange(int(1.0 * SR)) / SR
    swell = (np.sin(2 * np.pi * 180 * t) * 0.9).astype("float32")
    ramp = np.concatenate([np.linspace(0, 1, int(0.5 * SR)),
                           np.ones(int(0.5 * SR))]).astype("float32")
    c = (swell * ramp[:len(swell)]).astype("float32")
    assert np.array_equal(levels._onto_the_sound(c, int(0.40 * SR)), c)


def test_a_clip_that_starts_on_its_sound_is_left_alone():
    t = np.arange(int(0.9 * SR)) / SR
    c = (np.sin(2 * np.pi * 180 * t) * 0.9).astype("float32")
    assert np.array_equal(levels._onto_the_sound(c, int(0.40 * SR)), c)

def test_every_implemented_level_builds_against_the_shipped_bank():
    """A level that raises is a level nobody can watch.

    Levels 4, 5 and 6 were all broken at once and nothing noticed, because
    every other test drives them with a stub voice that can say anything.
    This one uses the real VoiceSource against the real shipped starter bank,
    which is what a person gets on a fresh install:

      4  asked voice.word("sa") for a blend nobody says on its own
      5  wanted six words absent from the starter bank
      6  went through voice.blend(), which raised outright

    Level 6 is the building-up journey - the centre of the curriculum - so
    "nothing the app's screens reach arrives here" was not true.
    """
    from gen import levels as L
    from gen.voice import VoiceSource

    voice = VoiceSource()
    fixed = sorted(n for n in L.IMPLEMENTED if n < 10 or n > 13)
    broken = {}
    for n in fixed:
        try:
            segs = L.build(n, voice, {"reps": 2, "pauseSeconds": 1.2})
            if not segs:
                broken[n] = "built nothing"
        except Exception as e:                      # noqa: BLE001
            broken[n] = f"{type(e).__name__}: {e}"
    assert not broken, "levels that do not build: " + repr(broken)
