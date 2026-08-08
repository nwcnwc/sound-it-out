"""Tests for the levels whose content is not written in advance.

These exist because the app spent its whole life reading fixed lists, which is
what made voice cloning pointless: everything it could say, somebody could
record. What is tested here is the opposite property - content that depends on
the parent's own text, their own names, and the child's own progress.

The recurring risk is decodability. A phonics level must never show a child a
word containing a letter they have not been taught, and the growing story is
the one place where that could silently go wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import openended as O  # noqa: E402


# --------------------------------------------------------- pasted text


def test_plain_text_becomes_one_line_per_sentence():
    lines = O.split_sentences("Alex went to the park. They saw a dog! Was it big?")
    assert lines == ["Alex went to the park.", "They saw a dog!", "Was it big?"]


def test_nothing_in_nothing_out():
    assert O.split_sentences("") == []
    assert O.split_sentences("   \n  ") == []
    assert O.split_sentences(None) == []


def test_a_long_sentence_breaks_where_a_reader_would_breathe():
    """Not mid-phrase.

    Splitting purely by word count put the break inside "across the / whole
    field", which is worse than a slightly long line: the child sees half a
    phrase and the voice stops in the middle of it.
    """
    long = ("Yes, it wagged its tail, and then it ran away across the field "
            "towards the trees at the far end of the park.")
    lines = O.split_sentences(long)
    assert len(lines) > 1
    assert lines[0] == "Yes,"
    assert any(x.endswith("tail,") for x in lines)


def test_a_pasted_chapter_cannot_become_a_nine_hour_render():
    huge = " ".join(f"This is sentence number {i}." for i in range(500))
    assert len(O.split_sentences(huge)) <= O.MAX_SENTENCES


def test_no_line_is_wider_than_a_beginner_can_hold():
    huge = "word " * 200
    assert all(len(x.split()) <= O.MAX_WORDS for x in O.split_sentences(huge))


# ----------------------------------------------------- their own words


class FakeGroup:
    def __init__(self, name, words):
        self.name = name
        self.words = [(w, None) for w in words]


PEOPLE = FakeGroup("People", ["Alex", "Mum", "Nana"])
THINGS = FakeGroup("Home", ["ball", "cup", "dog"])


def test_sentences_are_built_from_the_parents_own_words():
    lines = O.from_wordlist([PEOPLE, THINGS], limit=12)
    assert lines
    joined = " ".join(lines)
    assert any(n in joined for n in ["Alex", "Mum", "Nana"])
    assert any(t in joined for t in ["ball", "cup", "dog"])


def test_the_same_list_gives_the_same_sentences():
    """Generated audio is cached on disk, so instability costs an hour of
    synthesis for no change in what the child sees."""
    a = O.from_wordlist([PEOPLE, THINGS], limit=10)
    b = O.from_wordlist([PEOPLE, THINGS], limit=10)
    assert a == b


def test_a_different_list_gives_different_sentences():
    other = FakeGroup("People", ["Sam", "Dad", "Grandad"])
    assert O.from_wordlist([PEOPLE, THINGS], limit=10) != \
        O.from_wordlist([other, THINGS], limit=10)


def test_an_empty_list_returns_nothing_rather_than_raising():
    """A family who has not filled in the People group should be told what to
    do, not shown a traceback."""
    assert O.from_wordlist([FakeGroup("People", []), THINGS]) == []
    assert O.from_wordlist([PEOPLE, FakeGroup("Home", [])]) == []


def test_nobody_is_paired_with_themselves():
    solo = FakeGroup("People", ["Alex"])
    for line in O.from_wordlist([solo, THINGS], limit=20):
        assert "Alex and Alex" not in line
        assert "Alex can go to Alex" not in line


def test_sentences_do_not_repeat():
    lines = O.from_wordlist([PEOPLE, THINGS], limit=20)
    assert len(lines) == len(set(lines))


# ------------------------------------------------------ the growing story


def test_every_line_of_the_story_is_eventually_readable():
    """A line nobody can ever reach is dead weight, and would go unnoticed."""
    known = O.taught_letters(3)
    unreachable = [x for x in O.STORY if O._letters(x) - known]
    assert not unreachable, unreachable


def test_the_story_only_uses_letters_that_have_been_taught():
    """The one rule a phonics scheme cannot break."""
    for stage in (1, 2, 3):
        known = O.taught_letters(stage)
        for line in O.story_so_far(stage=stage):
            assert O._letters(line) <= known, f"stage {stage}: {line!r}"


def test_the_story_actually_grows():
    """It has to get materially longer, not merely not-shrink.

    The first version filtered ordinary decodable text against the taught
    letters and yielded three lines out of twenty-four across the entire
    curriculum - technically growing, useless as a story.
    """
    one, two, three = (len(O.story_so_far(stage=s)) for s in (1, 2, 3))
    assert one >= 5, "a first-stage child needs something to read"
    assert two >= one * 2
    assert three > two


def test_early_stages_avoid_the_word_the():
    """"the" needs h and e, which are not taught until the third set. It is the
    most tempting word to reach for and the easiest mistake to make."""
    for line in O.story_so_far(stage=2):
        assert "the" not in line.lower().split(), line


def test_progress_is_reportable():
    p = O.story_progress(2)
    assert p["lines"] > 0 and p["total"] >= p["lines"]
    assert set(p["letters"]) == O.taught_letters(2)


@pytest.mark.parametrize("stage", [0, 1, 2, 3, 99, None])
def test_any_stage_value_is_survivable(stage):
    assert O.story_so_far(stage=stage), f"stage={stage} produced nothing"
