"""Tests that a recording actually gets used once it has been made.

Recording is the expensive part of this app - forty minutes of a parent's time
- and every one of these tests exists because a clip that had been recorded was
silently not used. The failure is quiet by nature: the level still builds, the
video still plays, it just is not her voice, and nobody notices until they
listen closely to something they have no reason to doubt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import voice as V  # noqa: E402
from gen.soundout import SR  # noqa: E402


@pytest.fixture
def voice_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "VOICE_DIR", tmp_path)
    return tmp_path


def put(dirpath, name, seconds=0.5):
    """Write a clip where the lookup will actually look for it.

    Note the _safe(): keys are encoded on the way to disk, and writing the raw
    key produces a file that exists and is never found - which is the same
    class of bug this file is testing for.
    """
    dirpath.mkdir(parents=True, exist_ok=True)
    sf.write(dirpath / f"{V._safe(name)}.wav",
             np.full(int(SR * seconds), 0.2, dtype="float32"), SR)


# ------------------------------------------------- the /a/ vs /ae/ mismatch


def test_a_recorded_a_satisfies_a_request_for_ae(voice_dir):
    """The recording table writes the vowel in "cat" as /a/; levels.py writes
    it /ae/. Both are defensible and neither should change, but the lookup
    between them was exact - so every "a" in the curriculum used the built-in
    voice even after she had recorded it. "a" is in the first chapter
    (s, a, t, p, i, n), so this was audible in nearly every video.
    """
    put(voice_dir / "phonemes", "a")
    v = V.VoiceSource()
    assert v._recorded("phonemes", "æ") is not None
    assert v.used["recorded"] == 1


def test_the_alias_works_in_both_directions(voice_dir):
    put(voice_dir / "phonemes", "æ")
    assert V.VoiceSource()._recorded("phonemes", "a") is not None


def test_script_g_and_keyboard_g_are_the_same_sound(voice_dir):
    """espeak emits U+0261; a keyboard produces U+0067."""
    put(voice_dir / "phonemes", "g")
    assert V.VoiceSource()._recorded("phonemes", "ɡ") is not None


def test_an_alias_never_invents_a_recording(voice_dir):
    """Aliasing must not make a missing clip look present."""
    (voice_dir / "phonemes").mkdir(parents=True)
    assert V.VoiceSource()._recorded("phonemes", "æ") is None


def test_unrelated_sounds_are_not_aliased(voice_dir):
    """/s/ must never be answered with a recording of something else."""
    put(voice_dir / "phonemes", "z")
    assert V.VoiceSource()._recorded("phonemes", "s") is None


# ------------------------------------------------------------- sentences


def test_a_recorded_sentence_is_preferred_over_synthesis(voice_dir):
    """The sentence read was the one thing that could never be her voice.

    It went straight to the clone or the built-in voice with no lookup at all,
    which also made it the only thing voice cloning was actually generating.
    """
    put(voice_dir / "sentences", V.sentence_key("Sam sat on a mat."), seconds=2.0)
    v = V.VoiceSource()
    out = v.sentence("Sam sat on a mat.")
    assert v.used["recorded"] == 1 and v.used["generated"] == 0
    assert len(out) / SR == pytest.approx(2.0, abs=0.01), \
        "a real read is returned untouched, not slowed"


def test_sentence_keys_ignore_punctuation_and_case(voice_dir):
    assert V.sentence_key("Sam sat!") == V.sentence_key("sam sat")
    assert V.sentence_key("A dog sat on Sam.") == "a_dog_sat_on_sam"


def test_the_studio_and_the_lookup_agree_on_every_sentence(voice_dir, monkeypatch):
    """Where the studio saves and where the lookup searches must be identical.

    They are computed in two different modules. If they ever drift, every
    recorded sentence is silently ignored - the exact failure this file is
    about.
    """
    from gen import studio

    monkeypatch.setattr(studio, "VOICE_DIR", voice_dir)
    for it in studio.plan("sentences"):
        it.path().parent.mkdir(parents=True, exist_ok=True)
        sf.write(it.path(), np.full(int(SR * 2), 0.2, dtype="float32"), SR)

        v = V.VoiceSource()
        v.sentence(it.display)
        assert v.used["recorded"] == 1, f"{it.display!r} saved somewhere the lookup cannot see"
