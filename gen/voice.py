"""Where each sound comes from.

Resolution order, per item:

    1. Mom's recording, if it exists          -> used verbatim, leveled
    2. The starter voice, shipped             -> the developer's recordings
    3. Their cloned voice, if installed       -> generated

There is no synthesiser at the end of the chain any more. Every voice in
this app belongs to a person: the family's first, the developer's starter
bank underneath (which covers every pack word, line, sound and rime), and
the family's own clone for anything typed but not yet recorded. When none
of those can say a thing, the app says SO - by name, with what to do -
instead of handing the line to a machine.

This is the whole point of the design: (1) covers levels 1-5, which is where
a new reader stays for a long time, and nothing there is synthesised. The fallbacks
exist so the app is useful on day one, before any recording has happened, and
so a single missing clip degrades one word rather than breaking a level.

"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from gen.paths import SENTENCES, SOUNDS, STARTER_VOICE, VOICE_DIR, WORDS
from gen.soundout import SR, loud, slower, tidy_word


class MissingVoice(ValueError):
    """Nobody recorded this, and no human voice can be borrowed for it.

    Raised with a sentence the UI can show as-is. This is deliberately an
    error rather than a synthetic fallback: a robot reading to a child was
    the thing this app was built to avoid.
    """


# The same sound written two ways, and a recording of one must satisfy a
# request for the other.
#
# This is not pedantry. The recording table transcribes the vowel in "cat" as
# /a/, the way modern British dictionaries do; levels.py writes it /æ/, the way
# espeak needs it for synthesis. Both are right for their own job, and neither
# should change - but the lookup between them was exact, so every "a" in the
# curriculum fell back to the built-in voice even after she had recorded it.
# "a" is in the first chapter (s, a, t, p, i, n), so this was audible in almost
# every video the app made.
#
# Aliases apply to the lookup only. What gets sent to the synthesiser is
# untouched, because there /æ/ and /a/ genuinely are not interchangeable.
PHONEME_ALIASES = {
    "æ": ("a",),
    "a": ("æ",),
    "ɛ": ("e",),
    "e": ("ɛ",),
    # espeak emits U+0261 (script g), keyboards produce U+0067.
    "\u0261": ("g",),
    "g": ("\u0261",),
    # The schwa. No phonics session records an isolated /\u0259/ - it is the
    # unstressed "uh", and teachers SAY "uh" - so the recorded /\u028c/ answers
    # for it. An exact \u0259 recording, if anyone ever makes one, still wins,
    # because aliases are only consulted after the exact name misses.
    "\u0259": ("\u028c",),
}


def sentence_key(text: str) -> str:
    """Stable, filesystem-safe key for a whole sentence.

    Shared with gen/studio.py: what the studio saves and what this looks for
    have to agree exactly, or a recorded sentence is silently never found.
    """
    import re

    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80]


def _safe(name: str) -> str:
    """Filesystem-safe key. IPA symbols are not portable filenames - Windows
    in particular rejects several, and case-insensitive filesystems collide
    on /s/ vs /S/."""
    return "".join(f"u{ord(c):04x}" if not c.isalnum() else c for c in name)


class VoiceSource:
    """Resolves words and phonemes to audio, preferring real recordings."""

    def __init__(self, prefer_recordings=True, clone_profile=None,
                 use_magic_e=True, use_joins=True):
        """`use_magic_e` and `use_joins` decide whether a RECORDED
        multi-sound clip is allowed to replace the join it would otherwise
        be built from.

        Until now a recording always won, everywhere, with no way to say
        otherwise - which is right while every recording is good and wrong
        the moment one is not. A noisy magic-e take silently displaced a
        clean join in every word containing that ending, in every video,
        with nothing on screen saying so.

        The 42 single sounds are not covered by either flag. They are not a
        shortcut for anything; they are what everything else is built from.
        """
        self.prefer_recordings = prefer_recordings
        self.clone_profile = clone_profile
        self.use_magic_e = use_magic_e
        self.use_joins = use_joins
        self._clone = None
        self.used = {"recorded": 0, "starter": 0, "cloned": 0}

    def _may_use_clip_for(self, ipa: str) -> bool:
        """May a recorded clip of this whole sound be used, or must it be
        joined from its members?"""
        from gen import dictionary

        if len(dictionary.phonemes_in(ipa)) < 2:
            return True                      # one of the 42; always
        from gen.starter import all_magic_e

        if ipa in {i for _, i in all_magic_e()}:
            return self.use_magic_e
        return self.use_joins

    # -- availability -----------------------------------------------------

    @staticmethod
    def capabilities() -> dict:
        words = VOICE_DIR / "words"
        phon = VOICE_DIR / SOUNDS
        n_words = len(list(words.glob("*.wav"))) if words.exists() else 0
        n_phon = len(list(phon.glob("*.wav"))) if phon.exists() else 0
        sent = VOICE_DIR / "sentences"
        n_sent = len(list(sent.glob("*.wav"))) if sent.exists() else 0
        cloning = False
        try:
            from gen import clone

            cloning = clone.is_available()
        except Exception:
            cloning = False  # optional module; absence is normal, not an error
        starter = (
            len(list((STARTER_VOICE / SOUNDS).glob("*.wav")))
            if (STARTER_VOICE / SOUNDS).exists() else 0
        )
        return {
            "recordings": n_words > 0 or n_phon > 0,
            "recorded_words": n_words,
            "recorded_phonemes": n_phon,
            "recorded_sentences": n_sent,
            # The shipped starter voice IS the fallback now - there is no
            # synthesiser behind it. Present in any intact install, but say
            # so rather than assume, the same as everything else here.
            "fallback_voice": starter > 0,
            "cloning": cloning,
            "starter_phonemes": starter,
        }

    # -- lookups ----------------------------------------------------------

    @staticmethod
    def _lookup(root, kind: str, key: str):
        """Find a clip under one voice directory, trying aliased spellings."""
        f = root / kind / f"{_safe(key)}.wav"
        if not f.exists():
            # Try the other transcription of the same sound before giving up.
            for alt in PHONEME_ALIASES.get(key, ()):
                g = root / kind / f"{_safe(alt)}.wav"
                if g.exists():
                    f = g
                    break
            else:
                return None
        data, sr = sf.read(f, dtype="float32")
        if sr != SR:  # recordings are normalized on import, but never assume
            return None
        return data

    def _recorded(self, kind: str, key: str):
        if not self.prefer_recordings:
            return None
        a = self._lookup(VOICE_DIR, kind, key)
        if a is not None:
            self.used["recorded"] += 1
        return a

    def word(self, text: str, slow=False) -> np.ndarray:
        # Every return passes through loud(): gain only, so a quiet
        # recording session does not become a quiet television. Content is
        # still verbatim - see loud() for what that distinction means.
        a = self._recorded("words", text.lower())
        if a is not None:
            return loud(slower(a, 0.80) if slow else a)
        # The starter voice covers the shipped packs' words too, so a fresh
        # install reads "Chase is on the case." with a human throughout -
        # replaced word by word as the family records their own.
        if self.prefer_recordings:
            a = self._lookup(STARTER_VOICE, "words", text.lower())
            if a is not None:
                self.used["starter"] += 1
                return loud(slower(a, 0.80) if slow else a)
        if self.clone_profile is not None:
            from gen import clone

            a = tidy_word(clone.synthesize(text, self.clone_profile))
            self.used["cloned"] += 1
            return loud(slower(a, 0.80) if slow else a)
        raise MissingVoice(
            f"Nobody has recorded “{text}” yet. Record it on the Sentences "
            "page, or install the voice pack so new words can be said in "
            "your voice."
        )

    def can_say(self, text: str) -> bool:
        """Is there a recording of this whole word, in either bank?

        Whole words are never assembled, so "can this be said" is exactly
        "has somebody said it". Callers that choose their own words - the
        word-family level picks from a corpus list - use this to pick words
        the bank actually has rather than raising at the reader.
        """
        key = sentence_key(text) if " " in text else text.lower()
        kind = SENTENCES if " " in text else WORDS
        return (self._lookup(VOICE_DIR, kind, key) is not None
                or self._lookup(STARTER_VOICE, kind, key) is not None)

    def phoneme(self, ipa: str) -> np.ndarray:
        a = self._one_sound(ipa) if self._may_use_clip_for(ipa) else None
        if a is not None:
            return loud(a)
        # A grapheme-pair sound with no clip of its own - "eɪk", "æn" - is said by
        # running its member sounds together, each from a real recording.
        # This is what makes every aligned dictionary unit speakable
        # without anyone recording ten thousand of them.
        from gen import dictionary
        from gen.soundout import _xfade, cap, content

        parts = dictionary.phonemes_in(ipa)
        if len(parts) > 1:
            clips = []
            for p in parts:
                c = self._one_sound(p)
                if c is None:
                    break
                # condition each member first: a swelling vowel capped raw
                # keeps its swell and loses its voice (lollipop's op)
                clips.append(cap(content(c), 0.45))
            else:
                out = clips[0]
                n = int(SR * 0.03)
                for c in clips[1:]:
                    out = _xfade(out, c, n)
                return loud(out)
        # Never cloned: isolated phonemes are exactly what cloning models are
        # worst at, and a wrong phoneme teaches a wrong sound.
        raise MissingVoice(
            f"The sound “{ipa}” has no recording. Record it in Setup under "
            "the sounds or the word endings."
        )

    def _one_sound(self, ipa: str):
        """A single clip for `ipa`, hers first, starter second, or None."""
        a = self._recorded(SOUNDS, ipa)
        if a is not None:
            return a
        if self.prefer_recordings:
            a = self._lookup(STARTER_VOICE, SOUNDS, ipa)
            if a is not None:
                self.used["starter"] += 1
                return a
        return None

    def blend(self, ipas) -> np.ndarray:
        """A partial syllable like /sæ/ - the halfway step between a letter
        and a word.

        Addressed by IPA rather than spelling, since "sa" read as text is
        anyone's guess but /sæ/ is exact.

        A recording of the whole blend wins if somebody has made one. Failing
        that it is JOINED from its member sounds, exactly as phoneme() joins a
        two-phoneme label - same crossfade, same clips, same bank. Nothing is
        synthesised here and nothing is cloned.

        This used to raise instead, on the grounds that only a legacy path
        asked for blends. It was not only a legacy path: levels 4 and 6 - the
        two-sounds-together level and the building-up journey that is the
        centre of the whole curriculum - both go through here, and both failed
        outright for every word.
        """
        key = "".join(ipas)
        a = self._recorded("blends", key)
        if a is not None:
            return loud(a)
        return self.phoneme(key)

    def sentence(self, text: str, tempo=0.68) -> np.ndarray:
        # Her own read of the whole line, if there is one.
        #
        # This lookup did not exist, which made the sentence read the one thing
        # in the app that could never be her voice however much she recorded -
        # and the only thing voice cloning was actually generating. A recorded
        # sentence is returned untouched: she reads at her own pace, and the
        # tempo below exists to stop a synthesised line running away, not to
        # slow down a real person.
        a = self._recorded("sentences", sentence_key(text))
        if a is not None:
            return loud(a)
        # Starter line reads ship for the pack sentences, same as words:
        # a human read-along on day one, hers the moment she records it.
        if self.prefer_recordings:
            a = self._lookup(STARTER_VOICE, "sentences", sentence_key(text))
            if a is not None:
                self.used["starter"] += 1
                return loud(a)

        if self.clone_profile is not None:
            from gen import clone

            self.used["cloned"] += 1
            return loud(slower(clone.synthesize(text, self.clone_profile), tempo))
        raise MissingVoice(
            f"Nobody has read “{text}” yet. Record it on the Sentences page, "
            "or install the voice pack so new lines can be read in your voice."
        )

    def summary(self) -> str:
        u = self.used
        total = sum(u.values()) or 1
        return (f"{u['recorded']} from recordings, {u['starter']} starter "
                f"voice, {u['cloned']} cloned "
                f"({u['recorded'] * 100 // total}% genuinely their)")
