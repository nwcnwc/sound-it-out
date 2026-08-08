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
    monkeypatch.setattr(V, "VOICE_DIR", tmp_path / "family")
    # Point the starter voice somewhere empty too: these tests are about the
    # family lookup, and the real starter bank answering a phoneme request
    # would make a broken lookup pass.
    monkeypatch.setattr(V, "STARTER_VOICE", tmp_path / "starter")
    return tmp_path / "family"


@pytest.fixture
def starter_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "STARTER_VOICE", tmp_path / "starter")
    return tmp_path / "starter"


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


# --------------------------------------------------------- starter voice


def test_the_starter_voice_answers_an_unrecorded_phoneme(voice_dir, starter_dir):
    """A fresh install has no family recordings, and the whole point of
    shipping the starter clips is that /s/ is still a human /s/."""
    put(starter_dir / "phonemes", "s")
    v = V.VoiceSource()
    assert v.phoneme("s") is not None
    assert v.used["starter"] == 1 and v.used["generated"] == 0


def test_a_family_recording_always_beats_the_starter_voice(voice_dir, starter_dir):
    """"Until the user replaces them": the moment she records a sound, the
    shipped clip must never be heard again."""
    put(voice_dir / "phonemes", "s", seconds=0.9)
    put(starter_dir / "phonemes", "s", seconds=0.3)
    v = V.VoiceSource()
    out = v.phoneme("s")
    assert len(out) / SR == pytest.approx(0.9, abs=0.01)
    assert v.used["recorded"] == 1 and v.used["starter"] == 0


def test_the_starter_voice_understands_both_transcriptions(voice_dir, starter_dir):
    """The /a/ vs /ae/ alias applies to the starter bank the same as to the
    family's own - the shipped clips are named the way the recording table
    spells sounds, and levels.py asks the way espeak spells them."""
    put(starter_dir / "phonemes", "a")
    v = V.VoiceSource()
    v.phoneme("æ")
    assert v.used["starter"] == 1


def test_starter_clips_are_not_counted_as_genuinely_theirs(voice_dir, starter_dir):
    """The summary exists to be honest about whose voice a video is in, and
    the developer's phonemes are human but not hers."""
    put(starter_dir / "phonemes", "s")
    v = V.VoiceSource()
    v.phoneme("s")
    assert "0% genuinely their" in v.summary()


def test_the_shipped_bank_actually_resolves(monkeypatch):
    """The real assets/starter-voice, as shipped: every phoneme the shipped
    curriculum actually asks for must resolve without touching the
    synthesiser. Derived from the level content rather than the full grapheme
    table - the table also maps "qu" to /kw/, which is two sounds, has no
    single clip, and appears in no shipped word."""
    from gen import levels

    words = (levels.CVC_REAL + levels.CVC_NONSENSE + levels.DIGRAPH_WORDS
             + levels.CLUSTER_WORDS)
    for ch in levels.LADDER:
        words += ch["words"] + ch["sentence"].replace(".", "").split()
    for s in levels.SENTENCES:
        words += s.strip(".").split()
    asked = {p for w in words for _, p in levels.split_graphemes(w)}
    asked |= {p for pair in levels.BLENDS_2 for _, p in pair}
    asked |= {p for _, p in levels.SATPIN + levels.SET2 + levels.SET3}

    v = V.VoiceSource()
    missing = [p for p in sorted(asked)
               if v._lookup(V.STARTER_VOICE, "phonemes", p) is None]
    assert not missing, f"starter bank cannot say {missing}"


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


# -------------------------------------------------------------- loudness


def test_a_quiet_recording_comes_back_at_speaking_level(voice_dir):
    """Measured: her clips peaked at 0.12 and videos came out at -30 LUFS.
    Levelling is gain only, but it must actually happen."""
    from gen.soundout import loud

    quiet = np.full(int(SR * 0.5), 0.02, dtype="float32")
    out = loud(quiet)
    rms = float(np.sqrt(np.mean(out ** 2)))
    assert 0.07 < rms < 0.12


def test_levelling_never_clips(voice_dir):
    from gen.soundout import loud

    peaky = np.zeros(int(SR * 0.5), dtype="float32")
    peaky[100] = 0.9          # one hot sample in a quiet clip
    out = loud(peaky)
    assert float(np.abs(out).max()) <= 0.97 + 1e-6


def test_silence_is_not_amplified_into_noise(voice_dir):
    from gen.soundout import loud

    hiss = np.full(int(SR * 0.5), 1e-6, dtype="float32")
    assert float(np.abs(loud(hiss)).max()) < 1e-4


def test_the_lookup_levels_what_it_returns(voice_dir):
    put(voice_dir / "phonemes", "s")  # written at 0.2 - quiet
    v = V.VoiceSource()
    out = v.phoneme("s")
    assert float(np.sqrt(np.mean(out ** 2))) > 0.06


def test_starter_words_and_lines_answer_before_synthesis(voice_dir, starter_dir):
    """The packs ship with the developer's words and line reads, so a fresh
    install reads them with a human voice throughout."""
    put(starter_dir / "words", "chase")
    put(starter_dir / "sentences", V.sentence_key("Chase is on the case."), seconds=2.0)
    v = V.VoiceSource()
    v.word("Chase")
    v.sentence("Chase is on the case.")
    assert v.used["starter"] == 2 and v.used["generated"] == 0


def test_family_words_still_beat_starter_words(voice_dir, starter_dir):
    put(voice_dir / "words", "chase", seconds=0.9)
    put(starter_dir / "words", "chase", seconds=0.3)
    v = V.VoiceSource()
    out = v.word("Chase")
    assert len(out) / SR == pytest.approx(0.9, abs=0.01)
    assert v.used["recorded"] == 1 and v.used["starter"] == 0
