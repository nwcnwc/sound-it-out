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


def test_walkthrough_is_line_then_words_then_pieces(library):
    S.add("The dog can nap.")
    items = S.walkthrough_items(S.status()[0]["key"])
    assert items[0].kind == "sentence"
    assert items[0].display == "The dog can nap."
    assert [i.kind for i in items[1:5]] == ["word"] * 4
    # everything after is a missing sound piece of the buildups
    assert items[5:] and all(i.kind == "phoneme" for i in items[5:])


def test_walkthrough_deduplicates_repeated_words(library):
    S.add("A dog and a cat.")
    items = S.walkthrough_items(S.status()[0]["key"])
    words = [i.display for i in items if i.kind == "word"]
    assert words == ["A", "dog", "and", "cat"]


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
    assert items[0].kind == "word" and items[0].display == "Chase"
    assert all(i.kind == "phoneme" for i in items[1:]), "then its pieces"


def test_a_letter_entry_needs_no_recording_at_all(library, monkeypatch):
    from gen import voice as V

    monkeypatch.setattr(V, "VOICE_DIR", library / "voice")
    S.add("s")
    assert S.walkthrough_items(S.status()[0]["key"]) == []
    # ready comes from the phoneme bank (the starter voice ships /s/)
    assert S.status()[0]["ready"]


def test_letter_and_word_entries_build(library, monkeypatch):
    S.add("s")
    S.add("the")
    S.add("sat")
    monkeypatch.setattr(levels.wordlists, "load", lambda *a, **k: [])
    segs = levels.build(13, StubVoice(),
                        {"reps": 3, "pauseSeconds": 1.5, "sentences": None})
    assert sum(1 for s in segs if s.item_end) == 3
    # "the" is a tricky word: it must appear whole, never letter by letter
    shown = {"".join(p for p, _ in s.parts) for s in segs}
    assert "the" in shown and "th" not in shown and "t" not in shown


def test_spoken_wholes_are_highlighted_and_pads_go_neutral(library, monkeypatch):
    """Colour means "being said right now". A spoken whole word is lit; the
    silence after it shows the same text neutral (long pads only - flicking
    the light at approach speed would be a strobe)."""
    from gen.soundout import Theme, plan_job, whole

    seg = whole("Chase", np.full(SR, 0.2, dtype="float32"), pad=1.0)
    assert seg.parts == [("Chase", True)]

    work = library / "job"
    plan = plan_job([seg], Theme("t", "#000", "#fff", "#ff0", "#333"), work)
    assert plan["frame_count"] == 2, "one lit frame, one neutral pad frame"
    assert len(plan["timeline"]) == 3  # lit, neutral, loop pad


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
    for w in ("sat", "dog", "ship", "stop", "hand", "see"):
        assert levels.decodable(w), w


def test_magic_e_words_build_as_onset_and_rime():
    """The RULES teach magic-e as onset + rime - they serve words no
    dictionary knows (names like Mabe), so they must stay correct even
    though the dictionary answers first for real words."""
    assert levels.split_graphemes("case") == [("c", "k"), ("ase", "eɪs")]
    assert levels.split_graphemes("like") == [("l", "l"), ("ike", "aɪk")]
    # and the dictionary path is live for the real words
    assert levels.decodable("case") and levels.decodable("Chase")
    parts = levels.word_parts("Chase")
    assert "".join(g for g, _ in parts) == "Chase"


def test_voiced_s_words_are_buildable_and_voiced():
    """"is" is /ɪz/, not /ɪs/ - the dictionary vouches for it now, and the
    lexicon remains the answer for anything the dictionary misses."""
    from gen import dictionary

    assert levels.decodable("is")
    sounds = "".join(p for _, p in levels.word_parts("is"))
    assert "z" in sounds and "s" not in sounds.replace("z", "")
    assert levels.WORD_SOUNDS["is"] == [("i", "ɪ"), ("s", "z")]


def test_the_dictionary_reversed_most_of_the_old_refusals():
    """With aligned chunks, the classic tricky words build up honestly."""
    for w in ("the", "said", "happy", "have", "care", "nose", "was", "of"):
        assert levels.decodable(w), w


def test_true_liars_are_still_shown_whole():
    """"one" wants o=/wʌ/ - a correspondence English never teaches - and
    unknown names with untrustworthy spellings fall back to the cautious
    rules."""
    assert not levels.decodable("one")
    assert not levels.decodable("zorbe")  # unknown magic-e lookalike
    # ...but a nonsense consonant-le name reads fine: zor-bul
    assert levels.decodable("zorble")


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


def test_soft_c_and_g_in_rimes():
    """"face" ends /eɪs/ and "cage" ends /eɪdʒ/ - the e softens c and g
    inside a rime, while an opening c stays hard."""
    assert levels.word_parts("face") == [("f", "f"), ("ace", "eɪs")]
    assert levels.word_parts("cage") == [("c", "k"), ("age", "eɪdʒ")]


# ------------------------------------------------------------------ rimes


def test_rimes_record_into_the_phoneme_bank(library):
    """A rime item saves under its IPA in phonemes/ - exactly where
    voice.phoneme() already looks, so a family recording one overrides the
    shipped clip with no new machinery."""
    items = studio.plan("rimes")
    assert len(items) == 65
    ase = next(i for i in items if i.key == "ase")
    assert ase.ipa == "eɪs" and ase.kind == "phoneme"
    assert ase.path().parent.name == "phonemes"
    assert "case" in ase.say


def test_rime_takes_are_two(library):
    assert studio.takes_for("rimes") == 2


def test_every_rime_prompt_carries_an_example_word(library):
    """"oo then j" is linguistics homework; "as in huge" is an instruction.
    Every rime must anchor its sound to a real word."""
    for it in studio.plan("rimes"):
        assert "as in" in it.say, f"rime '{it.key}' has no example word"


def test_redo_plans_contain_exactly_the_selection(library, monkeypatch):
    """Selecting one phoneme to redo must queue that phoneme and nothing
    else - the old flow deleted it, reopened the whole part at its first
    gap, and auto-ran into items never chosen."""
    from gen import service

    plan = service.m_studio_plan({"part": "phonemes", "keys": ["s"]})
    assert plan["redo"] is True and plan["total"] == 1
    assert plan["items"][0]["key"] == "s"
    assert plan["resumeAt"] == 0


def test_approach_sounds_compress_with_the_gaps():
    """Blending compresses the SOUNDS, not just the gaps - and capping evens
    the rhythm so the highlight cannot camp on a long-held clip and blink
    past a short one (the Grandma bug: her m dwarfed her d)."""

    class UnevenVoice(StubVoice):
        def phoneme(self, ipa):
            secs = 2.5 if ipa == "m" else 0.2
            return np.full(int(SR * secs), 0.2, dtype="float32")

    segs = levels._approach(UnevenVoice(), levels.word_parts("dm"), 1.5, passes=3)
    per_pass = [segs[i * 2:(i + 1) * 2] for i in range(3)]
    for d, m in per_pass[:2]:
        assert len(m.audio) / SR <= 1.11, "long holds are capped"
        assert len(d.audio) / SR == pytest.approx(0.2, abs=0.01), \
            "short sounds are untouched in the discrete passes"
    # the cap shrinks pass by pass, and the final touching pass is the
    # shortest of all - trimmed, crossfaded, no silence inside it
    m_lens = [len(p[1].audio) for p in per_pass]
    assert m_lens[0] > m_lens[1] > m_lens[2]
    d3, m3 = per_pass[2]
    assert d3.pad == 0, "no gap inside the touching pass"
    joined = np.concatenate([d3.audio, m3.audio])
    assert len(joined) < (len(per_pass[1][0].audio) + len(per_pass[1][1].audio)), \
        "the touching pass is tighter than the pass before it"


# ------------------------------------------------------------- dictionary


def test_the_shipped_dictionary_is_big_and_loads():
    from gen import dictionary

    d = dictionary.load()
    assert len(d) > 100_000
    assert dictionary.chunks("said") == [("s", "s"), ("ai", "ɛ"), ("d", "d")]
    assert dictionary.chunks("Said")[0] == ("S", "s"), "casing follows the word"
    assert dictionary.chunks("zorble") is None


def test_chunk_sounds_split_into_recordable_phonemes():
    from gen import dictionary

    assert dictionary.tokens("eɪk") == ["eɪ", "k"]
    assert dictionary.tokens("ɪz") == ["ɪ", "z"]
    assert dictionary.tokens("s") == ["s"]


def test_every_aligned_chunk_is_speakable_from_the_42():
    """The whole promise: any chunk the dictionary emits can be said by
    concatenating clips that exist in the shipped bank."""
    from gen import dictionary

    bank = {"aɪ", "aʊ", "eɪ", "iː", "uː", "ɔː", "ɑː", "ɜː", "əʊ", "ɔɪ",
            "eə", "ɪə", "tʃ", "dʒ", "æ", "ɛ", "ɪ", "ɒ", "ʌ", "ʊ", "ə",
            "b", "d", "ð", "f", "ɡ", "h", "j", "k", "l", "m", "n", "ŋ",
            "p", "ɹ", "s", "ʃ", "t", "θ", "v", "w", "z", "ʒ"}
    sounds = {s for entry in dictionary.load().values() for _, s in entry}
    bad = [s for s in sounds if any(t not in bank for t in dictionary.tokens(s))]
    assert not bad, f"unspeakable chunk sounds: {bad[:10]}"


def test_multi_sound_chunks_keep_all_their_sounds():
    """A chunk like an=/æn/ carries two sounds, and the pass caps must
    budget for both - Grandma's /n/ was amputated by a one-sound cap."""

    class TwoSoundVoice(StubVoice):
        def phoneme(self, ipa):
            from gen import dictionary
            n = len(dictionary.tokens(ipa))
            return np.full(int(SR * 0.45 * n), 0.2, dtype="float32")

    parts = [("a", "æ"), ("an", "æn")]
    segs = levels._approach(TwoSoundVoice(), parts, 1.5, passes=3)
    single, double = segs[2], segs[3]  # the touching pass
    assert len(double.audio) > 1.6 * len(single.audio), \
        "the two-sound chunk gets roughly double the time"


def test_piece_prompts_carry_word_recipe_and_notation(library):
    """A lazy-record piece must say which word it came from, spell out the
    sound combination in plain words, and name the notation too."""
    S.add("Grandma is happy.")
    items = S.walkthrough_items(S.status()[0]["key"])
    pieces = [i for i in items if i.kind == "phoneme"]
    assert pieces, "buildable words must queue their missing pieces"
    chunk = next(i for i in pieces if i.key == "æn")
    assert "Grandma" in chunk.say          # which word
    assert "then" in chunk.say             # the spoken recipe
    assert "/æn/" in chunk.say             # the notation


def test_the_touching_pass_never_swallows_a_stop():
    """A /d/ is nothing but its burst. Crossfading it in from zero deletes
    it - "the d gets completely lost" - so a stop lands clean at full
    strength after the briefest close, and its front edge is never
    trimmed."""

    class BurstVoice(StubVoice):
        def phoneme(self, ipa):
            if ipa == "d":
                a = np.zeros(int(SR * 0.2), dtype="float32")
                # the burst, after a realistic 30ms closure
                a[int(SR * 0.03):int(SR * 0.05)] = 0.9
                return a
            return np.full(int(SR * 0.45), 0.2, dtype="float32")

    segs = levels._touching(BurstVoice(), [("a", "æ"), ("d", "d")])
    merged = np.concatenate([s.audio for s in segs])
    d_slice = segs[1].audio
    assert float(np.abs(d_slice).max()) > 0.8, \
        "the burst survives at nearly full strength"
    # and the d's slice begins at (or before) the burst, not after it
    burst_at = int(np.argmax(np.abs(merged) > 0.5))
    total_before_d = len(segs[0].audio)
    assert burst_at >= total_before_d - int(SR * 0.01), \
        "the highlight flips to d before its burst fires"


def test_no_word_is_a_single_unsplittable_chunk_when_it_can_pair():
    """"is=ɪz" as one chunk made the buildup say "is" three times. When
    letters and sounds pair one to one, they pair - i gets /ɪ/, s gets
    /z/ - and the lexicon's hand splits win where they exist."""
    assert levels.word_parts("is") == [("i", "ɪ"), ("s", "z")]
    assert levels.word_parts("up") == [("u", "ʌ"), ("p", "p")]
    assert levels.word_parts("an") == [("a", "æ"), ("n", "n")]
    assert len(levels.word_parts("in")) == 2


def test_names_follow_the_syllable_rules():
    """Rules serve names, and names follow what children are taught: an
    open syllable's vowel says its long sound (Zu-ma is "zoo", not
    "zuh") and a final -a is the soft "uh"."""
    assert levels.split_graphemes("Zuma") == \
        [("Z", "z"), ("u", "uː"), ("m", "m"), ("a", "ə")]
    # closed syllables stay short: nonsense practice words are untouched
    assert levels.split_graphemes("vam") == [("v", "v"), ("a", "æ"), ("m", "m")]
    assert levels.split_graphemes("zib") == [("z", "z"), ("i", "ɪ"), ("b", "b")]


def test_stop_joins_close_gently_never_clack():
    """Chopping a voiced vowel to silence in 4ms is audible as a clack.
    The join into a stop now fades the voice out over ~35ms, holds a
    silent closure, then fires the burst - so the waveform never jumps."""

    class VowelBurst(StubVoice):
        def phoneme(self, ipa):
            if ipa == "b":
                a = np.zeros(int(SR * 0.2), dtype="float32")
                a[int(SR * 0.03):int(SR * 0.05)] = 0.9
                return a
            return np.full(int(SR * 0.45), 0.3, dtype="float32")

    segs = levels._touching(VowelBurst(), [("ru", "ɹʌ"), ("bb", "b")])
    merged = np.concatenate([s.audio for s in segs])
    # the vowel and the closure must be smooth - the burst itself is
    # allowed to be sudden, that is what a burst is
    boundary = len(segs[0].audio)
    closure_end = boundary + int(SR * 0.03)
    jumps = np.abs(np.diff(merged[:closure_end]))
    assert float(jumps.max()) <= 0.05, "the voice closes gently, no clack"
    # and the vowel actually reaches silence before the closure
    assert float(np.abs(merged[boundary - 24:boundary + 24]).max()) < 0.05
