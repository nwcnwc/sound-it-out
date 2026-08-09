"""Tests for the sight-word list: words read whole, never sounded out.

The list is the parent's override of decodable(): a word on it must never
be decomposed into chunks or phonemes - not in the recording walk-through
(no sound pieces queued) and not in the video plan (shown and said whole).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import levels, sentences as S, sightwords, studio  # noqa: E402


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SENTENCES_FILE", tmp_path / "sentences.txt")
    monkeypatch.setattr(studio, "VOICE_DIR", tmp_path / "voice")
    monkeypatch.setattr(sightwords, "WORDLISTS", tmp_path)
    return tmp_path


# ------------------------------------------------------------- the list


def test_parse_tolerates_anything_a_human_types(library):
    assert sightwords.parse("Chase, Marshall\n  Skye\n# a note\nNana!") == \
        ["Chase", "Marshall", "Skye", "Nana"]


def test_save_then_load_round_trips(library):
    sightwords.save("Chase\nNana")
    assert sightwords.load_text() == "Chase\nNana"
    assert sightwords.words() == {"chase", "nana"}


def test_membership_ignores_case_and_punctuation(library):
    sightwords.save("Chase")
    assert sightwords.is_sight("chase")
    assert sightwords.is_sight("Chase,")
    assert not sightwords.is_sight("dog")


def test_empty_save_clears_the_list(library):
    sightwords.save("Chase")
    sightwords.save("")
    assert sightwords.words() == set()


# ------------------------------------- no decomposition, anywhere it counts


def test_sight_word_queues_no_sound_pieces_in_the_walkthrough(library):
    S.add("dog")
    with_pieces = S.status()[0]["missingSounds"]
    assert with_pieces > 0  # "dog" is decodable, so pieces queue by default

    sightwords.save("dog")
    assert S.status()[0]["missingSounds"] == 0
    items = S.walkthrough_items(S.status()[0]["key"])
    assert [i.kind for i in items] == ["word"]  # the whole word, nothing else


def test_sight_word_in_a_sentence_skips_only_that_word(library):
    S.add("The dog ran.")
    sightwords.save("dog")
    items = S.walkthrough_items(S.status()[0]["key"])
    piece_sources = [i for i in items if i.kind == "phoneme"]
    # "ran" still queues pieces; nothing derived from "dog" may appear.
    assert piece_sources, "ran should still be decomposed"
    assert all("dog" not in (i.say or "") for i in piece_sources)


def test_video_plan_shows_a_sight_word_whole(library):
    class FakeVoice:
        def word(self, w):
            import numpy as np
            return np.zeros(2400, dtype="float32")

        def phoneme(self, ipa):
            import numpy as np
            return np.zeros(2400, dtype="float32")

    sightwords.save("dog")
    segs = levels._one_word(FakeVoice(), "dog", reps=3, pause=0.5)
    # Whole-word treatment: every segment shows the full word, none of them
    # highlights an isolated letter or chunk.
    for seg in segs:
        shown = "".join(g for g, _ in seg.parts)
        assert shown == "dog"
        assert all(not hl for _, hl in seg.parts) or \
            [hl for _, hl in seg.parts] == [True]

    sightwords.save("")
    segs = levels._one_word(FakeVoice(), "dog", reps=3, pause=0.5)
    assert any(len(seg.parts) > 1 for seg in segs)  # sounded out again


def test_estimate_prices_a_sight_word_as_whole(library):
    S.add("dog")
    before = S.estimate_seconds()
    sightwords.save("dog")
    after = S.estimate_seconds()
    assert after < before  # no buildup passes in the whole-word price
