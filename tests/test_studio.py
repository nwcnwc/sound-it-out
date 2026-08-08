"""Tests for the in-app recording studio.

The behaviour under test is the one a parent actually feels: how many times she
is asked to say each thing, and whether the app notices when a take went wrong.

Words get a single take. That makes the scorer load-bearing in a way it is not
at three takes: there is no better attempt to fall back on, so anything worth
fixing has to be caught on the spot or it goes into the library uncorrected.

As in test_recordings.py the audio is synthetic - a voiced buzz with an
envelope, at whatever amplitude and noise floor the case calls for. It is built
to match the *measurements* the scorer keys off, not to sound like speech.

Run:  .venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import studio  # noqa: E402
from gen.soundout import SR  # noqa: E402

RNG = np.random.default_rng(11)


def voiced(seconds=0.45, amp=0.55, noise=0.0):
    """A rough voiced sound: f0 plus harmonics under a Hann envelope."""
    t = np.arange(int(SR * seconds)) / SR
    sig = sum(np.sin(2 * np.pi * f * t) / (i + 1)
              for i, f in enumerate([120, 240, 360, 480]))
    sig *= np.hanning(len(t))
    sig = sig / np.abs(sig).max() * amp
    room = np.zeros(int(SR * 0.25))
    out = np.concatenate([room, sig, room]).astype("float32")
    if noise:
        out = out + RNG.normal(0, noise, len(out)).astype("float32")
    return out.astype("float32")


WORD = studio.Item(key="dog", kind="word", display="dog", say="", length="free")


# ------------------------------------------------------------ take counts


def test_words_are_asked_for_once_and_phonemes_three_times():
    # The whole point of the split: ~40 phonemes are worth three goes each,
    # 100+ words are not.
    assert studio.takes_for("words") == 1
    assert studio.takes_for("phonemes") == 3


def test_unknown_part_falls_back_to_the_careful_default():
    assert studio.takes_for("something-new") == studio.TAKES_DEFAULT


# --------------------------------------------------------------- flagging


def test_a_clean_word_is_kept_without_comment():
    r = studio.choose([voiced()], WORD)
    assert r["best"] == 0
    assert not r["weak"], "a good take must not nag - she will stop reading them"
    assert r["advice"] == []


@pytest.mark.parametrize("audio,expect", [
    (voiced(amp=0.03), "quiet"),
    (voiced(amp=0.45, noise=0.06), "noise"),
])
def test_a_poor_single_take_is_flagged(audio, expect):
    r = studio.choose([audio], WORD)
    assert r["weak"], "a single poor take has no better sibling to lose to"
    assert any(expect in a for a in r["advice"]), r["advice"]


def test_a_flagged_take_is_still_kept():
    """Flagging offers a redo; it must never throw the audio away.

    If a flagged take were discarded, a parent who carried on would end up with
    a gap in the library and no indication of which word it was.
    """
    r = studio.choose([voiced(amp=0.03)], WORD)
    assert r["weak"]
    assert r["best"] == 0
    assert r["audio"] is not None
    assert not r["allFailed"]


def test_advice_is_something_she_can_act_on():
    """Every flag has to name a fix, or it is just criticism."""
    for note, text in studio.ADVICE.items():
        assert text and not text.endswith("."), note


def test_being_slightly_off_ideal_length_does_not_flag():
    """Only actionable faults interrupt.

    A word a little longer than the ideal loses a few points, and that is fine
    - it is still a perfectly good recording of the word, and there is nothing
    useful to tell her about it.
    """
    r = studio.choose([voiced(seconds=0.9)], WORD)
    assert r["takes"][0]["value"] < 100, "should cost something"
    assert not r["weak"], "but not enough to stop her"


def test_silence_is_a_failure_not_a_flag():
    """A dead microphone must never produce a saved file.

    This is a regression test with a real incident behind it. _trim returns
    the buffer unchanged when it finds no signal, which is what silence is, so
    silence used to pass the length guard, score around 47, and be saved as
    "very quiet". ChromeOS hands Linux a microphone that reports healthy and
    delivers exact zeros, so a whole session went to disk empty.
    """
    r = studio.choose([np.zeros(int(SR * 0.5), dtype="float32")], WORD)
    assert r["allFailed"], "silence must be rejected outright"
    assert r["audio"] is None, "nothing may be written for a silent take"
    assert "microphone" in r["takes"][0]["fatal"], "and it should say why"


def test_near_silence_from_a_dead_mic_is_also_rejected():
    """Not every broken input is exactly zero - some drivers emit faint dither."""
    dither = (RNG.normal(0, 0.0002, int(SR * 0.5))).astype("float32")
    r = studio.choose([dither], WORD)
    assert r["allFailed"]


def test_a_genuinely_quiet_but_real_take_still_gets_through():
    """The silence check must not swallow a real recording made too far away.

    That one is recoverable - it is flagged, kept, and she can move closer.
    Rejecting it outright would lose a usable clip.
    """
    r = studio.choose([voiced(amp=0.03)], WORD)
    assert not r["allFailed"], "a real, quiet take is not a dead microphone"
    assert r["weak"] and r["audio"] is not None
