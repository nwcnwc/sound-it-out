"""Where each sound comes from.

Resolution order, per item:

    1. Mum's recording, if it exists          -> used verbatim, untouched
    2. Phonemes only: the starter voice       -> shipped human recordings
    3. Their cloned voice, if installed       -> generated
    4. The built-in Kokoro voice              -> generated

This is the whole point of the design: (1) covers levels 1-5, which is where
a new reader stays for a long time, and nothing there is synthesised. The fallbacks
exist so the app is useful on day one, before any recording has happened, and
so a single missing clip degrades one word rather than breaking a level.

The starter voice (2) is the 42 phoneme clips recorded by the developer and
shipped with the app. Isolated sounds are what synthesis is worst at - the
schwa-stripping in gen/soundout.py is damage control, not a fix - and they are
also the sounds a child hears most, so a fresh install starts from a real
human /s/ rather than a shaped synthetic one. It covers phonemes and nothing
else: words and sentences in a stranger's voice would miss the point of the
app, but an isolated speech sound carries almost no identity.
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from gen.paths import MODELS, STARTER_VOICE, VOICE_DIR
from gen.soundout import SR, Voice as KokoroVoice, slower, tidy_word


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

    def __init__(self, prefer_recordings=True, clone_profile=None):
        self.prefer_recordings = prefer_recordings
        self.clone_profile = clone_profile
        self._kokoro = None
        self._clone = None
        self.used = {"recorded": 0, "starter": 0, "cloned": 0, "generated": 0}

    # -- availability -----------------------------------------------------

    @staticmethod
    def capabilities() -> dict:
        words = VOICE_DIR / "words"
        phon = VOICE_DIR / "phonemes"
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
        built_in = (MODELS / "kokoro-v1.0.onnx").exists()
        return {
            "recordings": n_words > 0 or n_phon > 0,
            "recorded_words": n_words,
            "recorded_phonemes": n_phon,
            "recorded_sentences": n_sent,
            # `kokoro` is the published name in the UI contract; `fallback_voice`
            # is what levels.py reads. Same fact, both emitted - the UI reported
            # the built-in voice as missing when only one of them existed.
            "kokoro": built_in,
            "fallback_voice": built_in,
            "cloning": cloning,
            # Shipped phoneme clips - present in any intact install, but say
            # so rather than assume, the same as everything else here.
            "starter_phonemes": (
                len(list((STARTER_VOICE / "phonemes").glob("*.wav")))
                if (STARTER_VOICE / "phonemes").exists() else 0
            ),
        }

    # -- lazy backends ----------------------------------------------------

    @property
    def kokoro(self):
        if self._kokoro is None:
            self._kokoro = KokoroVoice(voice="af_heart", speed=0.9)
        return self._kokoro

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
        if sr != SR:  # recordings are normalised on import, but never assume
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
        a = self._recorded("words", text.lower())
        if a is not None:
            return slower(a, 0.80) if slow else a
        if self.clone_profile is not None:
            try:
                from gen import clone

                a = clone.synthesize(text, self.clone_profile)
                self.used["cloned"] += 1
                return slower(a, 0.80) if slow else a
            except Exception:
                pass  # fall through to the built-in voice rather than fail
        # Generated only. Recordings above are returned untouched.
        self.used["generated"] += 1
        a = tidy_word(self.kokoro.say(text))
        return slower(a, 0.80) if slow else a

    def phoneme(self, ipa: str) -> np.ndarray:
        a = self._recorded("phonemes", ipa)
        if a is not None:
            return a
        # The shipped starter voice: a real human saying the sound, used until
        # the family records their own (their recording above always wins).
        if self.prefer_recordings:
            a = self._lookup(STARTER_VOICE, "phonemes", ipa)
            if a is not None:
                self.used["starter"] += 1
                return a
        # Never cloned: isolated phonemes are exactly what cloning models are
        # worst at, and a wrong phoneme teaches a wrong sound. Built-in voice
        # (schwa-stripped and sustained) is the safer fallback.
        self.used["generated"] += 1
        return self.kokoro.phoneme(ipa)

    def blend(self, ipas) -> np.ndarray:
        """A partial syllable like /sæ/ - the halfway step between a letter
        and a word.

        Always generated: these are nonsense fragments, so there is nothing for
        their to have recorded. Synthesised from IPA rather than spelling, since
        "sa" read as text is anyone's guess but /sæ/ is exact.
        """
        key = "".join(ipas)
        a = self._recorded("blends", key)
        if a is not None:
            return a
        self.used["generated"] += 1
        return tidy_word(self.kokoro.say(key, phonemes=True))

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
            return a

        if self.clone_profile is not None:
            try:
                from gen import clone

                self.used["cloned"] += 1
                return slower(clone.synthesize(text, self.clone_profile), tempo)
            except Exception:
                pass
        self.used["generated"] += 1
        return slower(self.kokoro.say(text), tempo)

    def summary(self) -> str:
        u = self.used
        total = sum(u.values()) or 1
        return (f"{u['recorded']} from recordings, {u['starter']} starter "
                f"voice, {u['cloned']} cloned, {u['generated']} built-in "
                f"voice ({u['recorded'] * 100 // total}% genuinely their)")
