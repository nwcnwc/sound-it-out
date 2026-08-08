"""Tests for the sentence library and the read-along timing.

The library is the simplified flow: a sentence carries everything a video
needs, recorded as its words plus the whole line. The timing math is the
part with real room to be quietly wrong - a highlight that drifts from the
voice teaches the wrong word - so it gets the closest look.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen import levels, sentences as S, studio  # noqa: E402
from gen.soundout import SR  # noqa: E402


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SENTENCES_FILE", tmp_path / "sentences.txt")
    monkeypatch.setattr(studio, "VOICE_DIR", tmp_path / "voice")
    return tmp_path


# ---------------------------------------------------------------- library


def test_a_paragraph_becomes_one_entry_per_sentence(library):
    S.add("Sam sat on a mat. The dog can nap.")
    assert [s["text"] for s in S.status()] == \
        ["Sam sat on a mat.", "The dog can nap."]


def test_adding_the_same_sentence_twice_keeps_one(library):
    S.add("Sam sat.")
    S.add("Sam sat.")
    assert len(S.load()) == 1


def test_removing_keeps_the_others_in_order(library):
    S.add("One here. Two here. Three here.")
    S.remove(S.status()[1]["key"])
    assert [s["text"] for s in S.status()] == ["One here.", "Three here."]


def test_empty_input_is_refused_with_a_sentence(library):
    with pytest.raises(ValueError):
        S.add("   ")


def test_status_reports_what_is_actually_on_disk(library):
    S.add("Sam sat.")
    st = S.status()[0]
    assert st["missing"] == ["Sam", "sat"] and not st["lineRecorded"]

    # Record "sat" the way the studio would; only "Sam" should remain.
    items = S.walkthrough_items(st["key"])
    sat = next(i for i in items if i.display == "sat")
    sat.path().parent.mkdir(parents=True, exist_ok=True)
    import soundfile as sf
    sf.write(sat.path(), np.full(SR // 2, 0.2, dtype="float32"), SR)
    st = S.status()[0]
    assert st["missing"] == ["Sam"] and not st["ready"]


def test_walkthrough_is_words_then_the_line(library):
    S.add("The dog can nap.")
    items = S.walkthrough_items(S.status()[0]["key"])
    assert [i.kind for i in items] == ["word"] * 4 + ["sentence"]
    assert items[-1].display == "The dog can nap."


def test_walkthrough_deduplicates_repeated_words(library):
    S.add("A dog and a cat.")
    items = S.walkthrough_items(S.status()[0]["key"])
    assert [i.display for i in items[:-1]] == ["A", "dog", "and", "cat"]


# ------------------------------------------------------------ entry kinds


def test_the_library_holds_letters_words_and_sentences():
    assert S.entry_kind("s") == "letter"
    assert S.entry_kind("Chase") == "word"
    assert S.entry_kind("I") == "letter"
    assert S.entry_kind("Sam sat.") == "sentence"
    assert S.entry_kind("stop!") == "word"


def test_a_word_entry_needs_no_line_read(library):
    S.add("Chase")
    items = S.walkthrough_items(S.status()[0]["key"])
    assert [(i.kind, i.display) for i in items] == [("word", "Chase")]


def test_a_letter_entry_needs_no_recording_at_all(library, monkeypatch):
    from gen import voice as V

    monkeypatch.setattr(V, "VOICE_DIR", library / "voice")
    S.add("s")
    assert S.walkthrough_items(S.status()[0]["key"]) == []
    # ready comes from the phoneme bank (the starter voice ships /s/)
    assert S.status()[0]["ready"]


def test_letter_and_word_entries_build(library, monkeypatch):
    S.add("s")
    S.add("Chase")
    S.add("sat")
    monkeypatch.setattr(levels.wordlists, "load", lambda *a, **k: [])
    segs = levels.build(13, StubVoice(),
                        {"reps": 3, "pauseSeconds": 1.5, "sentences": None})
    assert sum(1 for s in segs if s.item_end) == 3
    # "Chase" is irregular: it must appear whole, never letter by letter
    shown = {"".join(p for p, _ in s.parts) for s in segs}
    assert "Chase" in shown and "Ch" not in shown and "C" not in shown


# ---------------------------------------------------------------- packs


def test_packs_add_ordinary_entries(library, monkeypatch):
    monkeypatch.setattr(levels.wordlists, "all_words", lambda: ["Chase", "Skye"])
    S.add_pack("letters")
    kinds = {s["kind"] for s in S.status()}
    assert kinds == {"letter"}
    assert len(S.load()) == len(levels.SATPIN + levels.SET2 + levels.SET3)


def test_packs_report_what_is_already_added(library, monkeypatch):
    monkeypatch.setattr(levels.wordlists, "all_words", lambda: [])
    S.add("vam")
    pack = next(p for p in S.packs() if p["id"] == "nonsense")
    assert pack["added"] == 1 and pack["count"] == len(levels.CVC_NONSENSE)


def test_adding_a_pack_twice_adds_nothing_new(library, monkeypatch):
    monkeypatch.setattr(levels.wordlists, "all_words", lambda: [])
    S.add_pack("nonsense")
    n = len(S.load())
    S.add_pack("nonsense")
    assert len(S.load()) == n


def test_themed_packs_are_sentences(library, monkeypatch):
    """A pack about Paw Patrol is lines a fan wants read, not an exercise
    dressed up as one - every themed entry must be a real sentence."""
    monkeypatch.setattr(levels.wordlists, "all_words", lambda: [])
    for pid in ("paw-patrol", "veggie-tales", "gods-world", "family-day"):
        S.add_pack(pid)
    assert all(s["kind"] == "sentence" for s in S.status())


def test_every_pack_declares_a_group(library, monkeypatch):
    monkeypatch.setattr(levels.wordlists, "all_words", lambda: [])
    assert all(p["group"] in ("favourites", "skills") for p in S.packs())


def test_the_ladder_pack_keeps_curriculum_order(library, monkeypatch):
    monkeypatch.setattr(levels.wordlists, "all_words", lambda: [])
    S.add_pack("ladder")
    texts = S.load()
    assert texts[0] == "at" and "Sam sat." in texts
    assert texts.index("at") < texts.index("Sam sat.")


# ----------------------------------------------------------------- timing


def test_spans_tile_the_audio_exactly():
    """The slices must concatenate back to the original audio - this is the
    property that makes a rough estimate safe, because sound and picture
    cannot drift apart."""
    a = np.random.default_rng(1).random(SR * 3).astype("float32") * 0.3
    spans = S.word_spans(a, ["the", "dog", "can", "nap"],
                         [8000, 12000, 10000, 11000])
    assert spans[0][0] == 0 and spans[-1][1] == len(a)
    assert all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1))


def test_longer_clips_get_longer_spans():
    a = np.full(SR * 2, 0.2, dtype="float32")
    spans = S.word_spans(a, ["dog", "elephant"], [8000, 24000])
    assert (spans[1][1] - spans[1][0]) > 2 * (spans[0][1] - spans[0][0])


def test_function_words_are_squeezed():
    """An isolated "the" is a full careful syllable; in flowing speech it is
    a fraction of that. Equal clips must not mean equal spans."""
    a = np.full(SR * 2, 0.2, dtype="float32")
    spans = S.word_spans(a, ["the", "dog"], [10000, 10000])
    assert (spans[0][1] - spans[0][0]) < (spans[1][1] - spans[1][0])


def test_missing_clips_fall_back_to_word_length():
    a = np.full(SR * 2, 0.2, dtype="float32")
    spans = S.word_spans(a, ["hippopotamus", "an"], [0, 0])
    assert (spans[0][1] - spans[0][0]) > (spans[1][1] - spans[1][0])


def test_room_tone_belongs_to_the_edge_words():
    """Half a second of silence before she speaks must not be spread across
    every word - it rides along with the first one."""
    a = np.zeros(SR * 2, dtype="float32")
    a[SR // 2:] = 0.2  # speech starts at 0.5s
    spans = S.word_spans(a, ["dog", "cat"], [10000, 10000])
    mid = spans[0][1]
    # the split lands in the speech region, near its middle
    assert abs(mid - (SR // 2 + (SR * 2 - SR // 2) // 2)) < SR // 10


def test_readalong_audio_is_the_original_audio():
    a = np.random.default_rng(2).random(SR).astype("float32") * 0.3
    segs = levels._readalong("the dog", a, [5000, 9000])
    joined = np.concatenate([s.audio for s in segs])
    assert np.array_equal(joined, a)
    # one word lit per segment, in order
    lit = [[w for (w, on) in s.parts if on] for s in segs]
    assert lit == [["the"], ["dog"]]


# ------------------------------------------------------------ decodability


def test_regular_words_are_decodable():
    for w in ("sat", "dog", "ship", "stop", "hand"):
        assert levels.decodable(w), w


def test_treacherous_words_are_not():
    """Words the table would sound out WRONG - not just unknown ones."""
    for w in ("the", "said", "Chase", "like", "one", "happy", "I"):
        assert not levels.decodable(w), w


# ------------------------------------------------------- the level builder


class StubVoice:
    def word(self, text, slow=False):
        return np.full(int(SR * 0.4), 0.2, dtype="float32")

    def phoneme(self, ipa):
        return np.full(int(SR * 0.2), 0.2, dtype="float32")

    def blend(self, ipas):
        return np.full(int(SR * 0.3), 0.2, dtype="float32")

    def sentence(self, text, tempo=0.68):
        return np.full(int(SR * 1.5), 0.2, dtype="float32")


def test_level_13_builds_and_marks_items(library, monkeypatch):
    S.add("Sam sat on a mat. The dog can nap.")
    monkeypatch.setattr(levels.wordlists, "load", lambda *a, **k: [])
    segs = levels.build(13, StubVoice(),
                        {"reps": 3, "pauseSeconds": 1.5, "sentences": None})
    assert segs and segs[-1].item_end
    assert sum(1 for s in segs if s.item_end) == 2


def test_level_13_with_nothing_selected_says_what_to_do(library, monkeypatch):
    S.add("Sam sat.")
    monkeypatch.setattr(levels.wordlists, "load", lambda *a, **k: [])
    with pytest.raises(ValueError, match="[Ss]entence"):
        levels.build(13, StubVoice(),
                     {"reps": 3, "pauseSeconds": 1.5, "sentences": []})


def test_irregular_words_are_never_sounded_out(library, monkeypatch):
    """"The" must appear whole - a c-h-a-s-e style buildup of an irregular
    word teaches wrong sounds, which is worse than teaching nothing."""
    S.add("The dog can nap.")
    monkeypatch.setattr(levels.wordlists, "load", lambda *a, **k: [])
    segs = levels.build(13, StubVoice(),
                        {"reps": 3, "pauseSeconds": 1.5, "sentences": None})
    # No segment may show a lone highlighted letter belonging to "The".
    for s in segs:
        shown = "".join(p for p, _ in s.parts)
        if shown.lower() in ("t", "th", "the"):
            lit = [p for p, on in s.parts if on]
            assert shown.lower() == "the" or not lit, \
                f"'The' was sounded out: {s.parts}"


# ------------------------------------------------------------ the word bank


def test_the_bank_catalog_is_what_is_on_disk(library, monkeypatch):
    """bank_plan lists the files, not any curriculum list - words recorded
    through sentences appear even though no list anywhere names them."""
    import soundfile as sf

    d = library / "voice" / "words"
    d.mkdir(parents=True)
    for w in ("zorble", "case"):
        sf.write(d / f"{w}.wav", np.full(SR // 2, 0.2, dtype="float32"), SR)
    (d / "case.previous.wav").write_bytes((d / "case.wav").read_bytes())

    items = studio.bank_plan()
    assert [i.display for i in items] == ["case", "zorble"]
    assert all(i.done() for i in items)


def test_bank_display_decodes_safe_names(library):
    assert studio._undo_safe("dogu0027s") == "dog's"
    assert studio._undo_safe("sun") == "sun"
