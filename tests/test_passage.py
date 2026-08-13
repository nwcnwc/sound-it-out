"""Tests for recording the passage a section at a time.

The behavior that matters is resumption: a parent records two sections, is
interrupted, comes back an hour later, and has to land on section three
without deciding anything. Everything here is about that, and about the
failure it replaced - a session cut short leaving a fraction of the script on
disk with nothing saying so.

Run:  .venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import passage as P  # noqa: E402
from gen.soundout import SR  # noqa: E402


def tone(seconds):
    return (np.sin(np.arange(int(SR * seconds)) * 0.01) * 0.4).astype("float32")


@pytest.fixture
def voice_dir(tmp_path, monkeypatch):
    """Point the module at a scratch directory.

    Never let a test near the real one: it holds recordings that took a person
    forty minutes to make and cannot be reproduced.
    """
    monkeypatch.setattr(P, "VOICE_DIR", tmp_path)
    monkeypatch.setattr(P, "section_dir", lambda: tmp_path / "passage")
    monkeypatch.setattr(P, "whole_path", lambda: tmp_path / "passage.wav")
    monkeypatch.setattr(P, "section_path",
                        lambda i: tmp_path / "passage" / f"{i:02d}.wav")
    return tmp_path


# ------------------------------------------------------------- the sections


def test_the_passage_splits_at_its_own_headings():
    secs = P.sections()
    assert len(secs) > 1
    assert all(s.words > 20 for s in secs), "a section should be worth recording"
    assert all("##" not in s.text for s in secs), "headings are not read aloud"
    assert [s.index for s in secs] == list(range(len(secs)))


def test_every_section_is_long_enough_to_be_a_useful_reference():
    """Sections must stay above the length where prosody survives.

    The whole risk of splitting a cloning reference is losing connected
    speech. Twenty seconds is comfortably above what a reference needs; if
    someone later edits PASSAGE.md into very short sections, this should fail
    rather than quietly degrade the cloned voice.
    """
    for s in P.sections():
        assert s.expected_seconds >= 20, f"{s.title} is only {s.expected_seconds:.0f}s"


# ------------------------------------------------------------- resuming


def test_it_resumes_where_the_last_sitting_stopped(voice_dir):
    plan = P.plan()
    assert plan["resumeAt"] == 0 and plan["done"] == 0

    P.save_section(0, tone(40))
    P.save_section(1, tone(45))

    plan = P.plan()
    assert plan["done"] == 2
    assert plan["resumeAt"] == 2, "the point of the whole exercise"
    assert not plan["complete"]


def test_a_gap_in_the_middle_is_where_it_picks_up(voice_dir):
    """Re-recording section two should send her back to two, not to the end."""
    for i in range(len(P.sections())):
        P.save_section(i, tone(30))
    assert P.plan()["complete"]

    P.remove_section(1)
    plan = P.plan()
    assert plan["resumeAt"] == 1
    assert not plan["complete"]


def test_the_whole_passage_is_reassembled_from_the_sections(voice_dir):
    n = len(P.sections())
    for i in range(n):
        P.save_section(i, tone(10))
    built = P.rebuild()
    assert built["complete"] and built["sections"] == n

    a, sr = sf.read(voice_dir / "passage.wav", dtype="float32")
    expected = n * 10 + (n - 1) * P.JOIN_SILENCE
    assert abs(len(a) / sr - expected) < 0.05, "sections joined with a gap between"


def test_removing_a_section_rebuilds_without_it(voice_dir):
    for i in range(3):
        P.save_section(i, tone(10))
    before = sf.info(voice_dir / "passage.wav").frames
    P.remove_section(1)
    after = sf.info(voice_dir / "passage.wav").frames
    assert after < before, "the whole file must not keep audio that was deleted"


# --------------------------------------------------------- cut short


def test_a_section_cut_short_is_reported_as_such(voice_dir):
    sec = P.sections()[0]
    P.save_section(0, tone(5))                      # nowhere near the real length
    assert P.plan()["sections"][0]["short"] is True

    P.save_section(0, tone(sec.expected_seconds))   # read properly
    assert P.plan()["sections"][0]["short"] is False


# ------------------------------------------------------- not losing things


def test_a_passage_recorded_before_sections_existed_is_kept(voice_dir):
    """Someone who already read it in one go must not lose that recording.

    Their passage.wav was not produced by any section, and the first section
    saved rebuilds over it. Losing a recording to a software change would be
    indefensible, so it is copied aside first.
    """
    sf.write(voice_dir / "passage.wav", tone(33.5), SR)
    P.save_section(0, tone(40))

    keep = voice_dir / "passage.before-sections.wav"
    assert keep.exists(), "the original was overwritten"
    assert abs(sf.info(keep).frames / SR - 33.5) < 0.1


def test_the_backup_is_not_overwritten_by_later_sections(voice_dir):
    """Only the first save is a threat to it; later ones must leave it alone."""
    sf.write(voice_dir / "passage.wav", tone(33.5), SR)
    P.save_section(0, tone(40))
    P.save_section(1, tone(40))
    keep = voice_dir / "passage.before-sections.wav"
    assert abs(sf.info(keep).frames / SR - 33.5) < 0.1


def test_an_unknown_section_is_refused(voice_dir):
    with pytest.raises(ValueError):
        P.save_section(99, tone(10))
