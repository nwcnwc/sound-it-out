"""Verify the reading passage covers every English phoneme.

A cloning reference is only as good as its coverage: any sound the model never
hears, it has to guess at. Rather than hope a hand-written passage is balanced,
phonemise it and count.

Run:  .venv/bin/python -m gen.check_passage
"""

import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# The phonemes of English in the IPA notation espeak-ng actually emits for
# en-gb. (Note it uses U+0261 script ɡ, and ɹ rather than r - matching on the
# wrong notation silently reports everything as missing.)
TARGETS = {
    # consonants
    "p": "pan", "b": "bat", "t": "top", "d": "dog", "k": "cat", "ɡ": "got",
    "f": "fan", "v": "van", "θ": "thin", "ð": "this", "s": "sun", "z": "zip",
    "ʃ": "shop", "ʒ": "vision", "tʃ": "chip", "dʒ": "jam", "m": "man",
    "n": "net", "ŋ": "ring", "h": "hat", "l": "leg", "ɹ": "run", "w": "wet",
    "j": "yes",
    # vowels
    "a": "cat", "ɛ": "bed", "ɪ": "sit", "ɒ": "dog", "ʌ": "cup", "ʊ": "put",
    "ɑː": "car", "iː": "see", "ɔː": "door", "uː": "moon", "ɜː": "her",
    "ə": "about", "eɪ": "day", "aɪ": "my", "ɔɪ": "boy", "əʊ": "go",
    "aʊ": "now", "iə": "near", "eə": "hair",
}

# /ʊə/ ("pure") is deliberately absent: in contemporary RP it has largely
# merged with /ɔː/, and espeak-ng does not emit it for en-gb. Chasing it would
# mean writing unnatural sentences for a distinction most speakers no longer make.

MIN_OCCURRENCES = 5  # below this a cloner has thin evidence for the sound


def phonemise(text):
    import espeakng_loader
    from phonemizer import phonemize
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    from phonemizer.separator import Separator

    # espeak-ng ships inside espeakng_loader (a kokoro-onnx dependency), so
    # there is no system package to install - just point phonemizer at it.
    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())

    return phonemize(
        text,
        language="en-gb",
        backend="espeak",
        separator=Separator(phone=" ", word=" | "),
        strip=True,
    )


def main():
    root = pathlib.Path(__file__).resolve().parent.parent
    raw = (root / "PASSAGE.md").read_text()

    # Strip markdown chrome and the instructions above the first section.
    body = raw.split("## One", 1)[1] if "## One" in raw else raw
    body = re.sub(r"^#+.*$", "", body, flags=re.M)
    body = re.sub(r"[*_>`]", "", body)
    body = re.sub(r"^-+$", "", body, flags=re.M)
    words = len(body.split())

    phones = collections.Counter(phonemise(body).replace("|", "").split())

    missing, thin, ok = [], [], []
    for p, example in TARGETS.items():
        n = phones.get(p, 0)
        (missing if n == 0 else thin if n < MIN_OCCURRENCES else ok).append(
            (p, example, n)
        )

    print(f"Passage: {words} words (~{words / 130:.1f} min read aloud)")
    print(f"Phoneme inventory: {len(TARGETS)} targets, "
          f"{len(ok)} well covered, {len(thin)} thin, {len(missing)} missing\n")

    if missing:
        print("MISSING - passage must be amended:")
        for p, ex, _ in missing:
            print(f"   /{p}/  as in '{ex}'")
        print()
    if thin:
        print(f"THIN (<{MIN_OCCURRENCES} occurrences):")
        for p, ex, n in sorted(thin, key=lambda x: x[2]):
            print(f"   /{p}/  as in {ex!r:10} x{n}")
        print()

    rare = sorted(ok, key=lambda x: x[2])[:8]
    print("Rarest covered sounds:")
    for p, ex, n in rare:
        print(f"   /{p}/  as in {ex!r:10} x{n}")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
