"""The shipped pronunciation dictionary: letters aligned to sounds.

Built by gen/build_dictionary.py from CMUdict; loaded lazily from
assets/dictionary/aligned.txt. An entry is permission to build a word up:
every unit in it is a correspondence common enough across English (or
explicitly taught) to be honest on screen. Words absent from the file are
either unknown (names, nonsense - the spelling rules take over) or were
refused because their spelling lies ("one"), and are shown whole.

## Two kinds of unit, and why only one of them has a name

An alignment unit is some letters and the sound they make. Most carry ONE
phoneme, and a run of letters spelling one phoneme is a GRAPHEME - `c`, `a`,
`t`, and equally `sh`, `ck`, `igh`. That is the standard term and it is
exact.

Some carry TWO phonemes: `at` = /æt/, `ca` = /kæ/. Phonics has no name for
these, because they are not a unit anyone teaches - depending on the word one
may land on a rime (`at` in cat), an onset plus its vowel (`ca` in cat), or a
consonant blend (`st` in stop). They exist here for one reason: a recording
of /kæ/ is a single human breath where /k/ + /æ/ is two clips with a seam.

Since every one of them is exactly two ADJACENT GRAPHEMES merged, they are
called GRAPHEME PAIRS. The name is made up, because the thing is; it says
what it is rather than borrowing a term that means something else.

See README.md for the full glossary.
"""

from __future__ import annotations

from gen.paths import RESOURCES

ALIGNED = RESOURCES / "assets" / "dictionary" / "aligned.txt"

_cache = None

# Every sound an alignment unit can carry, longest first, for splitting a
# unit's sound into the phonemes the voice bank records. "eɪk" is /eɪ/ then
# /k/.
PHONEMES = sorted(
    ["aɪ", "aʊ", "eɪ", "iː", "uː", "ɔː", "ɑː", "ɜː", "əʊ", "ɔɪ", "eə",
     "ɪə", "tʃ", "dʒ", "æ", "ɛ", "ɪ", "ɒ", "ʌ", "ʊ", "ə", "b", "d", "ð",
     "f", "ɡ", "h", "j", "k", "l", "m", "n", "ŋ", "p", "ɹ", "s", "ʃ",
     "t", "θ", "v", "w", "z", "ʒ"],
    key=len, reverse=True)


def load() -> dict:
    global _cache
    if _cache is None:
        _cache = {}
        try:
            for line in ALIGNED.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                word, *units = line.split()
                _cache[word] = [tuple(u.split("=", 1)) for u in units]
        except OSError:
            pass  # no dictionary is survivable: the rules still work
    return _cache


def alignment(word: str):
    """The aligned (letters, sound) pairs for `word`, cased like the word
    itself, or None if the dictionary cannot vouch for it."""
    entry = load().get(word.lower())
    if entry is None:
        return None
    out, i = [], 0
    for letters, sound in entry:
        out.append((word[i:i + len(letters)], sound))
        i += len(letters)
    return out


_catalog = None


def pair_catalog():
    """Every GRAPHEME PAIR the dictionary uses, most useful first.

    Each entry: {ipa, spelling, example, words} - the spelling is the most
    common way that sound is written, the example is a short real word
    carrying it, and words is how many dictionary words use it. This is
    the Sound Bank's pair list: everything here plays as a crossfade of the
    two recorded phonemes until somebody records it as one breath.
    """
    global _catalog
    if _catalog is None:
        from collections import Counter, defaultdict

        common = set()
        try:
            common = set((ALIGNED.parent / "common.txt")
                         .read_text(encoding="utf-8").split())
        except OSError:
            pass

        count = Counter()
        spellings = defaultdict(Counter)
        example = {}
        for word, entry in load().items():
            for letters, sound in entry:
                if len(phonemes_in(sound)) < 2:
                    continue
                count[sound] += 1
                spellings[sound][letters.lower()] += 1
                # A good example is a COMMON simple word with the pair in
                # context: "bring" teaches /ɪŋ/, but "ing" on its own and
                # "ibn" the name teach doubt. So: common, short, few units,
                # and meaningfully longer than the pair itself.
                roomy = len(word) >= len(letters) + 2
                fit = (0 if word in common else 1,
                       0 if roomy and len(word) <= 7 and len(entry) <= 3 else 1,
                       len(word), word)
                if sound not in example or fit < example[sound]:
                    example[sound] = fit
        _catalog = [
            {"ipa": s, "spelling": spellings[s].most_common(1)[0][0],
             "example": example[s][3], "words": n}
            for s, n in count.most_common()
        ]
        # The magic-e rime sounds stay listed even when the aligner never
        # chose them for a dictionary word: recordings of them serve the
        # spelling-rule path (names, nonsense), and a recording must never
        # become invisible to the person who made it.
        from gen.starter import all_magic_e

        have = {c["ipa"] for c in _catalog}
        for spelling, ipa in all_magic_e():
            if ipa not in have:
                have.add(ipa)
                _catalog.append({"ipa": ipa, "spelling": spelling,
                                 "example": spelling, "words": 0})
    return _catalog


def phonemes_in(sound: str):
    """Split a unit's sound into single phonemes ("eɪk" -> eɪ, k)."""
    out, i = [], 0
    while i < len(sound):
        for p in PHONEMES:
            if sound.startswith(p, i):
                out.append(p)
                i += len(p)
                break
        else:
            out.append(sound[i])
            i += 1
    return out
