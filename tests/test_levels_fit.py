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


class FakeGroup:
    def __init__(self, name, words):
        self.name, self.words = name, words


def fake_wordlist(*_a, **_k):
    return [
        FakeGroup("Paw Patrol", [("Chase", "#00a"), ("Skye", None)]),
        FakeGroup("People", [("Mum", None)]),
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
    assert segs[8].pad == pytest.approx(0.3)


def test_each_pass_still_sweeps_the_highlight_left_to_right(monkeypatch):
    segs = levels._approach(StubVoice(), levels.spell("sat"), 1.5, passes=2)
    for p in range(2):
        for j in range(3):
            parts = segs[p * 3 + j].parts
            assert [on for _, on in parts] == [i == j for i in range(3)]
