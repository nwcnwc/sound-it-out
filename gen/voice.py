"""Where each sound comes from.

Resolution order, per item:

    1. Mum's recording, if it exists          -> used verbatim, untouched
    2. Their cloned voice, if installed         -> generated
    3. The built-in Kokoro voice              -> generated

This is the whole point of the design: (1) covers levels 1-5, which is where
a new reader stays for a long time, and nothing there is synthesised. The fallbacks
exist so the app is useful on day one, before any recording has happened, and
so a single missing clip degrades one word rather than breaking a level.
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from gen.paths import MODELS, VOICE_DIR
from gen.soundout import SR, Voice as KokoroVoice, slower, tidy_word


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
        self.used = {"recorded": 0, "cloned": 0, "generated": 0}

    # -- availability -----------------------------------------------------

    @staticmethod
    def capabilities() -> dict:
        words = VOICE_DIR / "words"
        phon = VOICE_DIR / "phonemes"
        n_words = len(list(words.glob("*.wav"))) if words.exists() else 0
        n_phon = len(list(phon.glob("*.wav"))) if phon.exists() else 0
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
            # `kokoro` is the published name in the UI contract; `fallback_voice`
            # is what levels.py reads. Same fact, both emitted - the UI reported
            # the built-in voice as missing when only one of them existed.
            "kokoro": built_in,
            "fallback_voice": built_in,
            "cloning": cloning,
        }

    # -- lazy backends ----------------------------------------------------

    @property
    def kokoro(self):
        if self._kokoro is None:
            self._kokoro = KokoroVoice(voice="af_heart", speed=0.9)
        return self._kokoro

    # -- lookups ----------------------------------------------------------

    def _recorded(self, kind: str, key: str):
        if not self.prefer_recordings:
            return None
        f = VOICE_DIR / kind / f"{_safe(key)}.wav"
        if not f.exists():
            return None
        data, sr = sf.read(f, dtype="float32")
        if sr != SR:  # recordings are normalised on import, but never assume
            return None
        self.used["recorded"] += 1
        return data

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
        return (f"{u['recorded']} from recordings, {u['cloned']} cloned, "
                f"{u['generated']} built-in voice "
                f"({u['recorded'] * 100 // total}% genuinely their)")
