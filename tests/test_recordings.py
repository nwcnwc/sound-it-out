"""Tests for the recording importer.

Everything here is synthetic. There is no real recording of the parent to test
against - there won't be until she sits down and makes one - so the audio is
built from numpy: hiss where a fricative goes, a low buzz where a vowel goes, a
click where a stop goes, and near-silent room tone in between. Those stand-ins
are chosen to match the *measurements* the code keys off (README: a fricative
sits around 7000Hz, a schwa around 1400Hz with the RMS holding up), not to
sound like speech.

Run:  .venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import recordings as R  # noqa: E402
from gen.soundout import SR  # noqa: E402

RNG = np.random.default_rng(7)


# ------------------------------------------------------- synthetic audio


# Levels are given as RMS, not peak, because RMS is what every threshold in
# the module is written against. A harmonic stack and a burst of noise with the
# same peak differ by 15dB in RMS, which is enough to make a test lie.

def _at_rms(x, amp):
    x = np.asarray(x, dtype="float64")
    return (x / (np.sqrt((x**2).mean()) + 1e-12) * amp).astype("float32")


def room(dur, amp=0.0015):
    """Room tone. Quiet, but never digital silence - a real room isn't."""
    return _at_rms(RNG.standard_normal(int(dur * SR)), amp)


def hiss(dur, amp=0.08):
    """Fricative stand-in: noise tilted up, centroid lands around 7kHz."""
    return _at_rms(np.diff(RNG.standard_normal(int(dur * SR) + 1)), amp)


def buzz(dur, f0=120, harmonics=12, amp=0.10):
    """Vowel stand-in: a harmonic stack, so the centroid is low.

    Random phases, or the harmonics line up and the crest factor goes through
    the roof - real voiced sound does not do that.
    """
    t = np.arange(int(dur * SR)) / SR
    ph = RNG.uniform(0, 2 * np.pi, harmonics)
    x = sum(np.sin(2 * np.pi * f0 * k * t + ph[k - 1]) for k in range(1, harmonics + 1))
    return _at_rms(x, amp)


def tone(f, dur, amp=0.10):
    t = np.arange(int(dur * SR)) / SR
    return _at_rms(np.sin(2 * np.pi * f * t), amp)


def click(dur=0.16, amp=0.35, tau=0.015):
    """Stop stand-in: a burst that decays to nothing and stays there."""
    n = int(dur * SR)
    env = np.exp(-np.arange(n) / (tau * SR))
    x = RNG.standard_normal(n) * env
    return (x / np.abs(x).max() * amp).astype("float32")  # peak, it's a transient


def session(items, gap=2.0, lead=1.5, tail=1.2):
    """Splice items together the way a voice memo of the session would be.

    Returns (audio, [(start_s, end_s), ...]) so offsets can be checked.
    """
    parts, spans, t = [room(lead)], [], lead
    for i, item in enumerate(items):
        parts.append(item)
        spans.append((t, t + len(item) / SR))
        t += len(item) / SR
        g = gap[i] if isinstance(gap, (list, tuple)) else gap
        if i < len(items) - 1:
            parts.append(room(g))
            t += g
    parts.append(room(tail))
    return np.concatenate(parts).astype("float32"), spans


def clip(label, audio, start=0.0):
    return R.Clip(label, np.asarray(audio, "float32"), start,
                  start + len(audio) / SR)


def write(tmp_path, audio, name="rec.wav", sr=SR):
    p = tmp_path / name
    sf.write(p, np.asarray(audio, "float32"), sr, subtype="FLOAT")
    return p


# ------------------------------------------------------------ splitting


def test_finds_every_item_and_ignores_room_tone():
    audio, spans = session([hiss(2.0), buzz(2.0), click(), tone(400, 1.5)])
    segs = R.find_segments(audio, SR)
    assert len(segs) == 4
    for seg, (s, e) in zip(segs, spans):
        assert abs(seg.start_s - s) < 0.12
        assert abs(seg.end_s - e) < 0.12


def test_threshold_adapts_to_a_noisy_room():
    """Same items, a room tone 25dB louder. A fixed dB gate would fail here."""
    quiet, _ = session([hiss(1.5), buzz(1.5), tone(500, 1.5)])
    noisy, _ = session([hiss(1.5), buzz(1.5), tone(500, 1.5)])
    noisy = noisy + room(len(noisy) / SR, amp=0.008)
    assert len(R.find_segments(quiet, SR)) == 3
    assert len(R.find_segments(noisy, SR)) == 3


def test_a_breath_in_the_gap_is_not_an_item():
    breath = hiss(0.3, amp=0.003)  # ~30dB below the items, as breaths are
    parts = [room(1.5), hiss(1.5), room(0.9), breath, room(0.9), buzz(1.5),
             room(0.9), tone(500, 1.5), room(1.0)]
    segs = R.find_segments(np.concatenate(parts), SR)
    assert len(segs) == 3


def test_a_dip_inside_one_sound_does_not_split_it():
    """A held /s/ dips in the middle; hysteresis + gap merging keeps it whole."""
    held = np.concatenate([hiss(0.8), hiss(0.25, amp=0.02), hiss(0.8)])
    audio, _ = session([held, buzz(1.5)])
    assert len(R.find_segments(audio, SR)) == 2


def test_no_segments_in_an_empty_room():
    assert R.find_segments(room(6.0), SR) == []


# ------------------------------------------------------------ alignment


def _dominant_hz(a):
    S = np.abs(np.fft.rfft(np.asarray(a, "float64")))
    return float(np.fft.rfftfreq(len(a), 1 / SR)[int(np.argmax(S))])


def test_retake_keeps_the_last_take():
    # She fluffs the second item, pauses briefly, says it again.
    audio, _ = session([tone(300, 1.2), tone(500, 1.2), tone(900, 1.2),
                        tone(1500, 1.2)],
                       gap=[2.0, 0.8, 2.0, 2.0])
    segs = R.find_segments(audio, SR)
    assert len(segs) == 4
    al = R.align(segs, ["a", "b", "c"])
    assert len(al.clips) == 3
    assert len(al.unmatched) == 1
    assert _dominant_hz(al.unmatched[0].audio) == pytest.approx(500, abs=20)
    assert _dominant_hz(al.clips[1].audio) == pytest.approx(900, abs=20)
    assert any("twice" in n for n in al.notes)


def test_extra_item_far_from_its_neighbours_is_not_assumed_to_be_a_retake():
    audio, _ = session([tone(300, 1.2), tone(500, 1.2), tone(900, 1.2)])
    al = R.align(R.find_segments(audio, SR), ["a", "b"])
    assert len(al.clips) == 2
    assert al.review  # flagged rather than quietly dropped
    assert any("retake" in n for n in al.notes)
    assert not al.confident


def test_missing_item_marks_everything_for_review():
    audio, _ = session([hiss(1.5), buzz(1.5), tone(600, 1.5)])
    al = R.align(R.find_segments(audio, SR), ["a", "b", "c", "d", "e"])
    assert len(al.clips) == 3
    assert al.missing == ["d", "e"]
    assert al.review == {"a", "b", "c"}
    assert not al.confident
    assert any("skipped" in n for n in al.notes)


def test_two_items_run_together_are_pointed_at():
    together = np.concatenate([buzz(1.6), room(0.15), buzz(1.6)])
    audio, _ = session([hiss(1.5), buzz(1.5), together, tone(500, 1.5)])
    al = R.align(R.find_segments(audio, SR), ["a", "b", "c", "d", "e"])
    assert any("may be two said together" in n for n in al.notes)


def test_align_is_clean_when_the_counts_agree():
    audio, _ = session([hiss(1.5), buzz(1.5)])
    al = R.align(R.find_segments(audio, SR), ["s", "a"])
    assert [c.label for c in al.clips] == ["s", "a"]
    assert al.confident and not al.notes


# ----------------------------------------------------------- resampling


def test_resample_keeps_duration_and_pitch():
    a = tone(1000, 1.0)  # generated at SR, treated as if it were 48k source
    out = R.resample(a, 48000, SR)
    assert len(out) == pytest.approx(len(a) * SR / 48000, rel=0.001)
    S = np.abs(np.fft.rfft(out.astype("float64")))
    assert np.fft.rfftfreq(len(out), 1 / SR)[int(np.argmax(S))] == pytest.approx(2000, abs=20)


def test_resample_is_a_no_op_at_the_same_rate():
    a = tone(440, 0.2)
    assert R.resample(a, SR, SR) is a


def test_split_recording_reads_a_file_and_returns_named_clips(tmp_path):
    # Written at 48k, so every duration in it halves - it stands in for a
    # phone file that has to be resampled on the way in.
    audio, _ = session([hiss(3.0), buzz(3.0), click(0.4, tau=0.05)],
                       gap=3.0, lead=3.0)
    path = write(tmp_path, audio, sr=48000)
    al = R.split_recording(path, ["s", "a", "t"])
    assert [c.label for c in al.clips] == ["s", "a", "t"]
    for label, samples, start_s, end_s in al.clips:  # unpacks as a 4-tuple
        assert samples.dtype == np.float32
        assert 0 < len(samples) / SR < (end_s - start_s) * 2
    assert al.source == path


# ------------------------------------------------------------------ qc


def _codes(issues, label=None):
    return {i.code for i in issues if label is None or i.label == label}


def test_silence_is_reported_as_nothing_recorded():
    issues = R.quality_report([clip("s", room(2.0))])
    assert _codes(issues) == {"silent"}


def test_clipping_is_caught():
    a = np.clip(hiss(2.0, amp=3.0), -1.0, 1.0)
    assert "clipped" in _codes(R.quality_report([clip("s", a)]))


def test_a_quiet_take_is_caught():
    assert "quiet" in _codes(R.quality_report([clip("s", hiss(2.0, amp=0.008))]))


def test_a_continuant_that_is_too_short_is_caught():
    issues = R.quality_report([clip("s", hiss(0.3))])
    assert "too-short" in _codes(issues)
    assert "two seconds" in " ".join(i.message for i in issues)


def test_a_well_held_continuant_is_clean():
    assert R.quality_report([clip("s", hiss(2.0))]) == []


def test_a_crisp_stop_is_clean():
    assert R.quality_report([clip("t", np.concatenate([click(), room(0.05)]))]) == []


def test_a_long_stop_is_flagged():
    a = np.concatenate([click(), hiss(0.5, amp=0.05)])  # long, but no "uh"
    assert "too-long" in _codes(R.quality_report([clip("t", a)]))


def test_a_stop_with_a_schwa_is_only_told_off_once():
    """"your t is half a second long" and "your t has an uh on it" are the
    same fault; two bullets for it buries the one that says what to do."""
    a = np.concatenate([click(0.12), buzz(0.22)])
    assert _codes(R.quality_report([clip("t", a)])) == {"schwa"}


def test_a_word_that_is_too_long_gets_a_listen():
    issues = R.quality_report([clip("Chase", buzz(3.0))], part="words")
    assert [i.severity for i in issues] == ["check"]


def test_words_are_not_measured_as_phonemes():
    assert R.quality_report([clip("Chase", buzz(0.9))], part="words") == []


# ----------------------------------------------- the schwa check (part 3)


def test_schwa_on_a_fricative_is_caught():
    """'sss' then 'uh': the centroid collapses while the RMS holds up."""
    a = np.concatenate([hiss(1.6, amp=0.25), buzz(0.25, amp=0.30)])
    issues = R.quality_report([clip("s", a)])
    assert "schwa" in _codes(issues)
    msg = next(i.message for i in issues if i.code == "schwa")
    assert '"suh"' in msg and "uh" in msg


def test_schwa_on_a_stop_is_caught():
    a = np.concatenate([click(0.12), buzz(0.22, amp=0.30)])
    assert "schwa" in _codes(R.quality_report([clip("t", a)]))


def test_a_voiced_fricative_is_not_flagged_just_for_being_low():
    """/ð/ sits low all the way through - an absolute threshold alone
    would fail it, so the test also requires a collapse."""
    a = np.concatenate([buzz(0.9, f0=90, harmonics=18), buzz(0.9, f0=90, harmonics=18)])
    assert "schwa" not in _codes(R.quality_report([clip("th-this", a)]))


def test_a_clean_fricative_is_not_flagged():
    assert "schwa" not in _codes(R.quality_report([clip("s", hiss(2.0))]))


def test_a_short_release_is_not_mistaken_for_a_schwa():
    a = np.concatenate([hiss(1.6), buzz(0.05, amp=0.30)])  # 50ms, under the floor
    assert "schwa" not in _codes(R.quality_report([clip("s", a)]))


def test_a_vowel_is_never_flagged_for_schwa():
    """A schwa is a vowel; there is nothing to separate it from, so the check
    must not fire rather than firing uselessly on every vowel."""
    a = np.concatenate([buzz(1.0, f0=140), buzz(0.4, f0=120)])
    assert "schwa" not in _codes(R.quality_report([clip("a", a)]))


def test_a_rising_tail_on_a_nasal_asks_for_a_listen():
    """The centroid test can't work on /m/, so the sonorant path looks for the
    tail's centroid rising into schwa territory instead - and only ever asks."""
    a = np.concatenate([tone(250, 1.6), buzz(0.3, f0=150, harmonics=14)])
    issues = R.quality_report([clip("m", a)])
    assert "schwa?" in _codes(issues)
    assert all(i.severity == "check" for i in issues if i.code == "schwa?")


def test_a_clean_nasal_is_not_flagged():
    assert R.quality_report([clip("m", tone(250, 2.0))]) == []


def test_schwa_issues_are_sorted_before_advisory_ones():
    bad = np.concatenate([hiss(1.6), buzz(0.25)])
    issues = R.quality_report([clip("m", np.concatenate(
        [tone(250, 1.6), buzz(0.3, f0=150, harmonics=14)])),
        clip("s", bad)])
    assert issues[0].severity == "fail"


# ------------------------------------------------- whole-file health


def test_a_noisy_room_is_reported():
    audio, _ = session([hiss(1.5), buzz(1.5)])
    noisy = audio + room(len(audio) / SR, amp=0.05)
    assert "noisy" in _codes(R.recording_health(noisy, SR))


def test_a_clean_room_is_not_reported():
    audio, _ = session([hiss(1.5), buzz(1.5)])
    assert R.recording_health(audio, SR) == []


# ---------------------------------------------------------------- save


def test_save_clips_writes_wavs_and_a_manifest(tmp_path):
    clips = [clip("s", hiss(2.0), start=1.5), clip("t", click(), start=5.0)]
    issues = R.quality_report(clips)
    paths = R.save_clips(clips, tmp_path, source="rec.m4a", issues=issues,
                         review={"t"}, part="phonemes", notes=["hello"])
    assert [p.name for p in paths] == ["s.wav", "t.wav"]

    a, sr = sf.read(tmp_path / "s.wav", dtype="float32")
    assert sr == SR and a.ndim == 1
    assert sf.info(tmp_path / "s.wav").subtype == "FLOAT"

    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["sample_rate"] == SR and m["part"] == "phonemes"
    assert m["source"] == "rec.m4a" and m["notes"] == ["hello"]
    assert [i["label"] for i in m["items"]] == ["s", "t"]
    assert m["items"][0]["start_s"] == 1.5
    assert m["items"][0]["confidence"] == "ok"
    assert m["items"][1]["confidence"] == "check"


def test_save_clips_does_not_overwrite_on_a_name_clash(tmp_path):
    clips = [clip("Mum", buzz(0.6)), clip("mum!", buzz(0.6))]
    paths = R.save_clips(clips, tmp_path, part="words")
    assert len({p.name for p in paths}) == 2


# -------------------------------------------------------------- report


def test_the_report_is_written_for_a_parent():
    a = np.concatenate([hiss(1.6), buzz(0.25)])
    al = R.Alignment(clips=[R.Clip("t", a, 0.0, 2.0)])
    text = R.format_report("phonemes", al, R.quality_report([clip("t", a)]))
    lowered = text.lower()
    for jargon in ("centroid", "rms", "dbfs", "hz", "schwa", "phoneme", "traceback"):
        assert jargon not in lowered
    assert "record" in lowered and "uh" in lowered


def test_the_report_says_so_when_everything_is_fine():
    al = R.Alignment(clips=[R.Clip("s", hiss(2.0), 0.0, 2.0)])
    assert "Everything looks good" in R.format_report("phonemes", al, [])


def test_the_report_names_the_position_in_the_recording():
    assert R.mmss(134.2) == "2:14"
    assert R.mmss(0.4) == "0:00"


# --------------------------------------------------------------- lists


def test_the_phoneme_list_matches_the_recording_guide():
    labels = R.phoneme_labels()
    assert len(labels) == 42 == len(set(labels))
    assert labels[:4] == ["s", "m", "t", "n"]          # read across the rows
    assert R.phoneme_labels("columns")[:3] == ["s", "t", "p"]
    assert sorted(labels) == sorted(R.phoneme_labels("columns"))
    # RECORDING.md prints "th" and "oo" twice; the keys still have to be unique
    assert R.PHONEMES["th"].example == "thin"
    assert R.PHONEMES["th-this"].example == "this"
    assert R.PHONEMES["oo"].example == "moon"
    assert R.PHONEMES["oo-put"].example == "put"


def test_hold_and_crisp_match_what_she_was_told():
    """RECORDING.md's two lists, and the three sounds it leaves off both."""
    by = {}
    for k, p in R.PHONEMES.items():
        by.setdefault(p.length, set()).add(k)
    assert {"s", "f", "m", "n", "l", "r", "v", "z", "sh", "th", "ng"} <= by["hold"]
    assert by["crisp"] == {"p", "t", "k", "b", "d", "g", "ch", "j"}
    assert by["free"] == {"w", "y", "h"}
    assert all(p.length == "hold" for p in R.PHONEMES.values()
               if p.ipa[0] in R.VOWELS)


def test_every_sound_is_classified_the_way_soundout_would():
    """The trap here is silent: espeak writes /g/ as script ɡ and soundout.py
    spells STOPS with an ASCII g, so an unnormalised lookup files /g/ as a
    fricative and the schwa test then measures the wrong end of it."""
    kinds = {k: R.phoneme_class(p.ipa) for k, p in R.PHONEMES.items()}
    assert kinds["g"] == "stop" and kinds["ch"] == "stop" and kinds["j"] == "stop"
    assert kinds["m"] == "sonorant" and kinds["r"] == "sonorant"
    assert kinds["s"] == "fricative" and kinds["th-this"] == "fricative"
    assert {k for k, v in kinds.items() if v == "vowel"} == {
        k for k, p in R.PHONEMES.items() if p.example in
        ("cat", "bed", "sit", "dog", "cup", "put", "car", "now", "hair",
         "see", "moon", "door", "her", "day", "my", "boy", "go", "near")
    } - {"k", "d"}  # 'cat' and 'dog' are also consonant examples


def test_a_schwa_on_g_is_caught_like_any_other_stop():
    a = np.concatenate([click(0.12), buzz(0.22)])
    assert "schwa" in _codes(R.quality_report([clip("g", a)]))


def test_a_glide_is_not_judged_on_its_length():
    """/w/, /y/ and /h/ were never given a length to hit, so neither a long
    one nor a short one is a fault."""
    for label in ("w", "y", "h"):
        assert R.quality_report([clip(label, tone(320, 2.5))]) == []
        assert R.quality_report([clip(label, hiss(0.2))]) == []


def test_word_labels_come_from_the_editable_list(tmp_path):
    p = tmp_path / "words.txt"
    p.write_text("# a note\n[People]\nAlex\nMum  #ff0000\n\n[Toys]\nball\n")
    assert R.word_labels(p) == ["Alex", "Mum", "ball"]


# ----------------------------------------------------------------- cli


def test_main_end_to_end_on_a_word_list(tmp_path, capsys):
    words = tmp_path / "words.txt"
    words.write_text("[People]\nAlex\nMum\nNana\n")
    audio, _ = session([buzz(0.6), buzz(0.6, f0=160), buzz(0.6, f0=200)])
    path = write(tmp_path, audio)
    out = tmp_path / "words"

    code = R.main([str(path), "--part", "words", "--words", str(words),
                   "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0, text
    assert {p.name for p in out.glob("*.wav")} == {"alex.wav", "mum.wav", "nana.wav"}
    assert "Expected 3 items, matched up 3." in text
    assert "Everything looks good" in text


def test_main_reports_a_count_mismatch_without_writing_nonsense(tmp_path, capsys):
    audio, _ = session([hiss(1.5), buzz(1.5), click()])
    path = write(tmp_path, audio)
    code = R.main([str(path), "--part", "phonemes", "--dry-run"])
    text = capsys.readouterr().out
    assert code == 1
    assert "Expected 42 items, matched up 3." in text
    assert "--order columns" in text  # the order it assumed is stated, not hidden


def test_main_on_a_missing_file(tmp_path, capsys):
    assert R.main([str(tmp_path / "nope.m4a"), "--part", "words"]) == 2
    assert "Can't find" in capsys.readouterr().out


def test_main_on_the_passage_keeps_it_whole(tmp_path, capsys):
    # ~5.5 minutes is what PASSAGE.md should take; fake it with 20 long items.
    audio, _ = session([buzz(15.0, f0=110 + 5 * i) for i in range(22)], gap=0.4)
    path = write(tmp_path, audio)
    code = R.main([str(path), "--part", "passage", "--out", str(tmp_path)])
    text = capsys.readouterr().out
    assert code == 0, text
    a, sr = sf.read(tmp_path / "passage.wav", dtype="float32")
    assert sr == SR
    assert len(a) == pytest.approx(len(audio), rel=0.001)  # not split, not trimmed
    assert json.loads((tmp_path / "passage.json").read_text())["duration_s"] > 300


def test_a_truncated_passage_is_caught(tmp_path, capsys):
    audio, _ = session([buzz(20.0), buzz(20.0)])
    path = write(tmp_path, audio)
    assert R.main([str(path), "--part", "passage", "--dry-run"]) == 1
    assert "missing" in capsys.readouterr().out


# --------------------------------------------------------- optional fix


def test_clean_phoneme_strips_the_tail_if_ffmpeg_can_stretch():
    """The fallback for a schwa she is not going to re-record."""
    if subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                      capture_output=True).stdout.find(b"rubberband") < 0:
        pytest.skip("ffmpeg built without rubberband")
    a = np.concatenate([hiss(1.6), buzz(0.25)])
    out = R.clean_phoneme(clip("s", a))
    assert out.size and np.isfinite(out).all()
    assert len(out) / SR < len(a) / SR  # the "uh" is gone
