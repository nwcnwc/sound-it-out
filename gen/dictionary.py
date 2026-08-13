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

DICT_DIR = RESOURCES / "assets" / "dictionary"
GRAPHEMES_FILE = DICT_DIR / "graphemes.txt"
SYLLABLES_FILE = DICT_DIR / "syllables.txt"

# Kept so the module reads naturally where the grapheme dictionary is "the"
# dictionary, which is most places.
ALIGNED = GRAPHEMES_FILE

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


VOWEL_SOUNDS = frozenset(
    ["æ", "ɛ", "ɪ", "ɒ", "ʌ", "ʊ", "ə", "aɪ", "aʊ", "eɪ", "iː", "uː",
     "ɔː", "ɑː", "ɜː", "əʊ", "ɔɪ", "eə", "ɪə"])

_syllables = None


def syllables(word: str):
    """The word's syllables, or None if it is one syllable or unknown.

    A SEPARATE dictionary, not a view of the grapheme alignment. Nothing in
    "rabbit" being r/a/bb/i/t says whether it divides rab-bit or ra-bbit -
    that is a different question with different data behind it.
    """
    global _syllables
    if _syllables is None:
        _syllables = {}
        try:
            for line in SYLLABLES_FILE.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                w, _, split = line.partition(" ")
                _syllables[w] = split.split("-")
        except OSError:
            pass          # absent is survivable; callers treat it as unknown
    return _syllables.get(word.lower())


def onset_rime(word: str):
    """((onset letters, sound), (rime letters, sound)), or None.

    DERIVED from the grapheme alignment rather than stored, because it is a
    rule and not a fact: the rime is the first vowel grapheme and everything
    after it, the onset is whatever came before. Deriving it means the two
    views can never disagree about where the word divides, which is the whole
    reason there is one alignment and not two.

    None when the word has no onset ("at", "up" - the rime IS the word), when
    it has more than one syllable (onset and rime are properties of a
    syllable, and word families are built on single-syllable words), or when
    the dictionary cannot vouch for the word at all.
    """
    a = alignment(word)
    if not a or (syllables(word) or [word]) != [word.lower()]:
        return None
    for i, (g, s) in enumerate(a):
        if phonemes_in(s)[0] in VOWEL_SOUNDS:
            if i == 0:
                return None                      # no onset to speak of
            join = lambda part: ("".join(g for g, _ in part),
                                 "".join(s for _, s in part))
            return join(a[:i]), join(a[i:])
    return None


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


# The common-word list is web frequency (google-10000), which is the right
# source for "is this a real word people write" and the wrong one for "may a
# child see this". It carries profanity, first names, brand names and
# internet debris, all of which turned up in the first families() run: shit
# in -it, chan/dan/jan in -an, cnet and dui and ui as words.
#
# So the list is filtered here rather than trusted. This is a children's
# literacy app and the filter is not optional; it is deliberately explicit
# and over-broad, because a false exclusion costs one word in a family that
# has a dozen, and a false inclusion puts it on a screen in front of a child.
UNSUITABLE = frozenset("""
ass arse bitch bastard cock crap cunt damn dick dildo fag faggot fuck fucked
fucking hell homo jizz nigga nigger piss porn pussy queer rape rapist screw
sex sexy shag shit slut slag spic std tit tits twat wank whore xxx nude naked
nudes erotic escort viagra cialis casino gambling drug drugs weed coke booze
beer wine vodka whisky whiskey cigarette cigarettes tobacco gun guns ammo
kill killed killing murder dead death die died dying suicide blood gore war
""".split())

# Junk shapes rather than junk meanings: initialisms, brands and fragments.
# A word a child reads should be a word, and these are strings.
NOT_WORDS = frozenset("""
cnet ui dui phi tri pre ce je ne bo jo ko geo cho chan dat lan nat sen len
chen glen ben brad chad kay jay dee lee tee pee vee zee bra hugo dell msn aol
url asp php sql xml html http https www ftp pdf gif jpg mp3 dvd cd tv pc mac
ip isp faq ceo cfo cto usa uk eu un nyc la sf dc pm am est pst
""".split())


def suitable(word: str) -> bool:
    """Is this a word a child may meet in a family list?"""
    w = word.lower()
    return (w not in UNSUITABLE and w not in NOT_WORDS
            and any(c in "aeiouy" for c in w) and len(w) >= 2)


_families = None


def families(min_words: int = 4, max_len: int = 4, min_len: int = 3):
    """Word families: rimes shared by several short single-syllable words.

    [{rime, sound, words}, ...] most useful first - `at` with cat, hat, mat,
    sat and the rest behind it.

    This is what the phonics half of the curriculum is built on, and it is
    DERIVED from the rime view rather than curated by hand: a family is
    exactly a rime that enough real words share, which is a fact about the
    language and not an opinion about teaching.

    Word families matter more here than the usual amount. Blending c-a-t
    means holding three sounds in order and merging them, which leans on
    phonological working memory - the known weakness for the readers this is
    built for. A family leans on the strength instead: recognise `at`, change
    the front, and there is one thing to manipulate rather than three.
    """
    global _families
    if _families is None:
        from collections import defaultdict

        common = set()
        try:
            common = set((DICT_DIR / "common.txt")
                         .read_text(encoding="utf-8").split())
        except OSError:
            pass
        groups = defaultdict(list)
        for w in load():
            if not (min_len <= len(w) <= max_len):
                continue
            if w not in common or not suitable(w):
                continue
            r = onset_rime(w)
            if not r:
                continue
            # A teaching rime is vowel PLUS coda: -at, -ip, -un. An open rime
            # (-a, -o, -y) is not a family, it is a vowel with a crowd of
            # fragments and abbreviations behind it, which is what the first
            # run produced - "da ga ha ja ka ma" as the second-biggest family
            # in English.
            sounds = phonemes_in(r[1][1])
            if len(sounds) < 2 or sounds[-1] in VOWEL_SOUNDS:
                continue
            groups[(r[1][0].lower(), r[1][1])].append(w)
        _families = [
            {"rime": rime, "sound": sound, "words": sorted(ws)}
            for (rime, sound), ws in groups.items() if len(ws) >= min_words
        ]
        _families.sort(key=lambda f: -len(f["words"]))
    return _families


_common = None


def common_words() -> list:
    """The common-word list, in FREQUENCY order, most common first.

    Order is the whole value here. Alphabetical, the first multi-syllable
    words a learner would meet are abandoned, aberdeen and abortion; by
    frequency they are people, little, water, about.
    """
    global _common
    if _common is None:
        try:
            _common = (DICT_DIR / "common.txt").read_text(
                encoding="utf-8").split()
        except OSError:
            _common = []
    return _common


def frequency_rank() -> dict:
    """word -> position in the common list. Missing words rank last."""
    return {w: i for i, w in enumerate(common_words())}
