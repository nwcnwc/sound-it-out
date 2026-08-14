"""Tests for the in-app recording studio.

The behavior under test is the one a parent actually feels: how many times she
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


# ----------------------------------------------------------- what it says


def test_a_single_take_is_never_described_as_the_best_of_several():
    """It read "Best of the takes" after one take.

    That is not just clumsy - it tells her the app compared this against
    attempts she never made, which makes the feedback untrustworthy.
    """
    # A little quiet: enough to be worth mentioning, not enough to interrupt
    # for, which is exactly the case that produces a qualified sentence.
    r = studio.choose([voiced(amp=0.10)], WORD)
    assert r["takes"][0]["notes"], "this case is meant to produce a comment"
    assert not r["weak"], "and it is meant to be a comment, not a flag"
    assert "though" in r["reason"], r["reason"]
    assert "Best of the takes" not in r["reason"], r["reason"]
    assert "takes" not in r["reason"].lower(), r["reason"]


def test_three_takes_still_say_which_one_was_kept():
    r = studio.choose([voiced(seconds=0.9), voiced(), voiced(amp=0.03)], WORD)
    assert r["best"] is not None
    # With a genuinely clean take among them, nothing needs qualifying.
    assert r["reason"] == "Clean take."


def test_wording_matches_take_count_for_clean_audio():
    assert studio.choose([voiced()], WORD)["reason"] == "Got it."
    assert studio.choose([voiced(), voiced()], WORD)["reason"] == "Clean take."


# ---------------------------------------------------------------- passage


def test_the_passage_can_be_found_without_a_key(tmp_path, monkeypatch):
    """The passage is one file, not an item in a list.

    It had no key, so clip_path could not look it up, so nothing in the app
    could offer to play it back - the one recording you could not hear.
    """
    import soundfile as sf
    monkeypatch.setattr(studio, "VOICE_DIR", tmp_path)

    assert studio.clip_path("passage", "") is None, "absent means absent"

    sf.write(tmp_path / "passage.wav", voiced(seconds=1.0), SR)
    found = studio.clip_path("passage", "")
    assert found and found.endswith("passage.wav")


def test_asking_for_the_passage_does_not_need_a_matching_item():
    """A key of "" must not be mistaken for a real item and return one."""
    assert studio.clip_path("passage", "chase") == studio.clip_path("passage", "")


def test_the_alphabet_is_a_recordable_part_and_a_buildable_level():
    """Letter NAMES, which the app taught not at all.

    Every other level teaches sounds, because sounds are what reading runs
    on. But a child also has to say which letter this is, and sing the
    alphabet, and neither of those is a sound: S is named "ess" and sounds
    "sss". A reader needs both.
    """
    from gen import dictionary, levels, studio
    from gen.voice import VoiceSource

    items = studio.plan("letters")
    assert len(items) == 26, "one per letter"
    assert [i.display for i in items] == [c.upper() for c in
                                          "abcdefghijklmnopqrstuvwxyz"]
    # The prompt must ask for the NAME, since asking for "S" gets the sound.
    assert "NAME" in items[18].say and "ess" in items[18].say, items[18].say

    # Every name is speakable on a fresh install, joined from recorded sounds,
    # so the level works before anybody records anything extra.
    voice = VoiceSource()
    for ipa in dictionary.LETTER_NAMES:
        assert voice.phoneme(ipa) is not None

    segs = levels.build(16, voice, {"reps": 2, "pauseSeconds": 1.2})
    assert len(segs) == 26
    assert "".join(g for g, _ in segs[0].parts) == "Aa"


def test_the_alphabet_comes_before_letter_sounds():
    """Naming a letter is how a child says which one they are looking at."""
    from gen import levels

    order = [l.id for l in levels.LEVELS]
    assert order.index(16) < order.index(3), \
        "the alphabet is taught before the sounds"
