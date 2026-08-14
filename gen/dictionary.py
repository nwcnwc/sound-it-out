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


def derive_pair_catalog():
    """Work the catalog out from scratch. Build time only - see pair_catalog.

    Every guard lives here: the example gate, the shortest-and-commonest
    ranking, dropping a pair no ordinary word demonstrates, and the hand-
    picked magic-e anchors.
    """
    """Every GRAPHEME PAIR the dictionary uses, most useful first.

    Each entry: {ipa, spelling, example, words} - the spelling is the most
    common way that sound is written, the example is a short real word
    carrying it, and words is how many dictionary words use it. This is
    the Sound Bank's pair list: everything here plays as a crossfade of the
    two recorded phonemes until somebody records it as one breath.
    """
    if True:
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
                # An example is printed on a screen a parent reads WITH their
                # child, so it is gated before it is ranked. This used to be a
                # preference only - "common words score better" - which is how
                # cigarette, suicide, orgy and orgasm ended up as the examples
                # for four sounds, alongside the proper names stawski and
                # waitzkin straight out of CMUdict.
                if not good_example(word):
                    continue
                roomy = len(word) >= len(letters) + 2
                # SHORT first, then common. Ranking by frequency alone gave
                # "during" for -ing and "information" for -ati, both perfectly
                # common and neither a word a child would pick out. A short
                # word is also a word they can read.
                # A child's word beats a short word beats a common one. The
                # ordering matters: ranking by frequency first gave "during"
                # for -ing and "station" for -ati, both ordinary and neither
                # a word a child would pick out of a list.
                fit = (0 if word in CHILD_WORDS else 1,
                       0 if len(word) <= 5 else 1 if len(word) <= 7 else 2,
                       0 if roomy and len(entry) <= 3 else 1,
                       frequency_rank().get(word, 10 ** 6), len(word), word)
                if sound not in example or fit < example[sound]:
                    example[sound] = fit
        # No example, no entry.
        #
        # A join is offered so somebody can smooth a seam they will actually
        # hear. If no short, common, child-appropriate word demonstrates it,
        # the seam is not in anything they are going to make - and the row is
        # just noise in a list of two hundred. This is what drops mc, tz, ce,
        # lu, rew and yo, which were there because the corpus contains
        # mcdonald and pizza and this app never will.
        # A letter name is its own best example: /ɛs/ shown as "espn" tells
        # nobody it is the letter S.
        _catalog = [
            {"ipa": s, "spelling": spellings[s].most_common(1)[0][0],
             "example": (f'the letter {LETTER_NAMES[s].upper()}'
                         if s in LETTER_NAMES else example[s][5]),
             "words": n}
            for s, n in count.most_common()
            if s in example or s in LETTER_NAMES
        ]
        # The magic-e rime sounds stay listed even when the aligner never
        # chose them for a dictionary word: recordings of them serve the
        # spelling-rule path (names, nonsense), and a recording must never
        # become invisible to the person who made it.
        from gen.starter import all_magic_e

        have = {c["ipa"] for c in _catalog}
        from gen.studio import MAGIC_E_EXAMPLES

        for spelling, ipa in all_magic_e():
            if ipa not in have:
                have.add(ipa)
                # "ufe" as in "ufe" tells nobody anything. studio already
                # keeps a real word carrying each ending's SOUND - roof for
                # ufe, soup for upe, zoom for ume - chosen for the ear rather
                # than the spelling, which is the whole point of an anchor.
                # Exempt from good_example(): these were picked by hand to
                # carry each ending's SOUND - "beef" for ufe, "eel" for ele -
                # which is a better test than how often the web says them.
                _catalog.append({"ipa": ipa, "spelling": spelling,
                                 "example": MAGIC_E_EXAMPLES.get(spelling, ""),
                                 "words": 0})
    return _catalog


PAIRS_FILE = DICT_DIR / "pairs.txt"


def pair_catalog():
    """Every GRAPHEME PAIR the dictionary uses, most useful first.

    Read from a shipped file, not worked out on demand. Deriving it means
    walking all 110,000 entries and every unit in them, which took seconds -
    paid by whoever opened the Sound Bank, every time the sidecar started.
    It derives from a dictionary that only changes when gen/build_dictionary
    runs, so it is computed there and shipped alongside it, the same as
    graphemes.txt and syllables.txt.

    Each entry: {ipa, spelling, example, words} - the spelling is the most
    common way that sound is written, the example a short real word carrying
    it, and words how many dictionary words use it.
    """
    global _catalog
    if _catalog is None:
        _catalog = []
        try:
            for line in PAIRS_FILE.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                ipa, spelling, example, n = line.split("\t")
                _catalog.append({"ipa": ipa, "spelling": spelling,
                                 "example": example, "words": int(n)})
        except OSError:
            # Running from a checkout with no baked file. Derive it rather
            # than return nothing, and pay the seconds once.
            _catalog = derive_pair_catalog()
    return _catalog


# The 26 letter NAMES, which are not the same thing as the 26 letter sounds.
# "S" is said /ɛs/ and sounds /s/, and a child needs both - the name to sing
# the alphabet and say which letter this is, the sound to read with.
#
# 22 of the 26 names are two sounds or more, which is why they kept turning up
# in the grapheme-pair list carrying examples like "espn", "dns" and "ssn".
# Those were never initialism debris: /ɛs/ IS the name of S, and the honest
# example for it is the letter.
LETTER_NAMES = {
    "eɪ": "a", "biː": "b", "siː": "c", "diː": "d", "iː": "e", "ɛf": "f",
    "dʒiː": "g", "eɪtʃ": "h", "aɪ": "i", "dʒeɪ": "j", "keɪ": "k", "ɛl": "l",
    "ɛm": "m", "ɛn": "n", "əʊ": "o", "piː": "p", "kjuː": "q", "ɑːɹ": "r",
    "ɛs": "s", "tiː": "t", "juː": "u", "viː": "v", "dʌbəljuː": "w",
    "ɛks": "x", "waɪ": "y", "ziː": "z",
}


_split_cache = {}


def phonemes_in(sound: str):
    """Split a unit's sound into single phonemes ("eɪk" -> eɪ, k).

    Memoised. There are a few thousand distinct sounds in the dictionary and
    this is asked about every unit of every one of 110,000 words - 671,556
    calls building the same few thousand answers, and 17 million startswith()
    against the 43-phoneme table to do it.
    """
    hit = _split_cache.get(sound)
    if hit is not None:
        return hit
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
    _split_cache[sound] = out
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
sex sexy sexual sexuality intercourse orgasm orgasms orgy orgies erotic
erotica porn porno pornography nude nudes naked nudity strip stripper
breast breasts boob boobs butt buttocks genital genitals penis vagina
condom condoms virgin virginity fetish bdsm escort escorts brothel
prostitute prostitution incest rape rapist molest molested pedophile
ass arse bitch bastard cock crap cunt damn dick dildo fag faggot fuck
fucked fucking hell homo jizz nigga nigger piss pussy queer screw shag
shit slut slag spic std tit tits twat wank whore xxx bollocks bugger

drug drugs cocaine heroin meth methamphetamine marijuana cannabis weed
opium morphine addict addiction addicted overdose narcotic narcotics
alcohol alcoholic booze beer wine vodka whisky whiskey rum gin liquor
drunk drunken cigarette cigarettes cigar tobacco smoking nicotine vape
viagra cialis casino gambling betting lottery

kill killed killing killer murder murdered homicide suicide suicidal
death dead die died dying corpse coffin funeral grave burial
blood bloody gore violent violence assault abuse abused abusive
gun guns rifle pistol shotgun ammo bullet bomb bombing weapon weapons
war warfare terror terrorist terrorism torture hostage massacre
abortion miscarriage cancer tumor tumour disease infection
""".split())

# Membership in the common list is not enough on its own: it is web text, so
# "sex" sits at rank 169 and "porn" at 632, above "cat" at 1733. The list
# above is the backstop for exactly those - the ones common enough that no
# frequency cut will ever exclude them.
#
# The cut does the rest of the work, and does it better than a blocklist can,
# because a blocklist only ever excludes what somebody thought of. Every good
# example word is rare enough to be well inside it: water 314, box 426,
# bank 848, dog 1020, happy 1253, ring 1490, cat 1733, ball 1860. Everything
# that caused trouble sits far outside: orgy 4795, suicide 5715, screw 7168,
# cigarette 8075, orgasm 9479 - and stawski and waitzkin, both proper names
# out of CMUdict, are not in the common list at all.
# The fallback cut, for joins no child word demonstrates.
#
# Loosening it past this buys pairs whose only example is "memorabilia" or
# "workstation" - a join that appears nowhere a child will read is a join
# nobody needs to smooth, so the cut is doing real work rather than being a
# safety measure. Safety is the blocklist and the child-first ranking:
# checked at the loosest possible setting, no unsuitable word reaches an
# example at all.
EXAMPLE_MAX_RANK = 5000

# Words a child actually meets, which is a different question from words the
# web says often - and the web list was answering the wrong one. Measured:
# rabbit ranks 6548, elephant 8767, banana 9370, and kitten, carrot, zebra
# and bucket are not in the ten thousand at all. A rank cut tuned to exclude
# the unsuitable was throwing out 24 of 25 ordinary children's words with
# them, and picking "station" and "during" instead.
#
# So this is the FIRST place an example is looked for. The frequency list
# stays as the fallback, for joins no child word happens to demonstrate.
CHILD_WORDS = frozenset("""
mom dad mommy daddy mum baby brother sister grandma grandpa nana family
boy girl kid child friend man woman people
cat dog puppy kitten bird fish duck cow pig horse sheep goat hen chick
rabbit bunny mouse frog bear lion tiger monkey elephant giraffe zebra
snake turtle owl fox deer wolf whale shark dolphin penguin
bee ant bug butterfly spider worm snail ladybug
apple banana orange grape berry cherry lemon melon peach pear plum
bread cake cookie candy jam honey egg cheese milk juice water
soup rice pasta pizza sandwich burger chip carrot potato bean pea corn
tomato onion salad dinner lunch breakfast supper snack
head hair face eye ear nose mouth tooth teeth tongue lip chin neck
arm hand finger thumb leg foot toe knee tummy back
hat coat shirt sock shoe boot glove scarf dress skirt sweater pants
house home room bed door window floor wall roof stair garden yard
kitchen bathroom bedroom table chair sofa lamp mirror clock shelf
cup plate bowl spoon fork knife pot pan bottle box bag basket
toy ball doll block puzzle bike wagon kite drum bell balloon teddy
book story page picture crayon pencil pen paper paint glue
car bus truck train plane boat ship rocket tractor van jeep taxi
sun moon star sky cloud rain snow wind storm rainbow
tree leaf flower grass seed root branch wood stone rock sand
hill river lake sea beach farm park road bridge
red blue green yellow black white brown pink purple orange gray
big little small tall short long fast slow hot cold wet dry
happy sad funny silly kind good bad new old soft hard loud quiet
run jump walk skip hop sit stand sleep eat drink play sing dance
look see hear smell touch hold give take open shut push pull
wash brush comb dig ride swim climb throw catch kick clap wave
laugh cry smile hug kiss help wait stop go come stay
day night morning today tomorrow week year birthday
mcdonald pizza burger

grew drew blew flew threw knew crew brew stew screw chew
hook hood book look took cook shook foot wood good stood
bull full pull push bush put bug hug rug mug jug tug dug
went sent bent tent lent kept slept crept swept felt melt
told sold hold gold cold fold bold held
made came gave saved waved named
found round sound ground pound bound
best rest nest test west chest guest
sing ring king wing thing bring swing string spring
hand land sand band stand grand
jump bump lump pump stump
sick kick pick lick tick trick stick thick quick chick brick
bell tell well sell fell shell smell spell
back pack rack sack track black snack crack
duck luck truck stuck
bank tank thank drank sank blank
milk silk
lamp camp stamp
mask task
gift lift
nest best
help yelp
belt melt
farm arm harm
corn horn born torn thorn
bird third girl
turn burn hurt
park dark mark shark spark
storm form
short sport
start smart chart
""".split())

# Junk shapes rather than junk meanings: initialisms, brands and fragments.
# A word shown to a child should be a word, and these are strings.
NOT_WORDS = frozenset("""
cnet ui dui phi tri pre ce je ne bo jo ko geo cho chan dat lan nat sen len
chen glen ben brad chad kay jay dee lee tee pee vee zee bra hugo dell msn aol
url asp php sql xml html http https www ftp pdf gif jpg mp3 dvd cd tv pc mac
ip isp faq ceo cfo cto usa uk eu un nyc la sf dc pm am est pst dns cnn bbc
ac dc ok tv pm inc ltd corp yahoo google amazon ebay paypal microsoft apple
doge nasdaq nato fbi cia irs dmv atm gps usb
georgia texas florida ohio boston chicago denver dallas
amd espn uri gen doge lucia guam kenya ecuador puerto
dvd cpu dna rna nasa ibm att verizon comcast
""".split())

def suitable(word: str) -> bool:
    """Is this a word a child may meet at all?"""
    w = word.lower()
    return (w not in UNSUITABLE and w not in NOT_WORDS
            and any(c in "aeiouy" for c in w) and len(w) >= 2)


def good_example(word: str) -> bool:
    """May this word be shown as the example for a sound?

    Stricter than suitable(), because an example is printed on a screen a
    parent reads next to their child. Three gates, and a word must pass all:

        it is a real common word     - excludes CMUdict's proper names,
                                       stawski and waitzkin among them
        it is COMMONLY common        - rank inside EXAMPLE_MAX_RANK
        it is not on the blocklist   - for the ones frequency cannot catch
    """
    w = word.lower()
    if not suitable(w):
        return False
    # Three letters at least. "ac" is in the common list and is not a word;
    # nothing shorter than three letters teaches anyone what a sound is.
    if len(w) < 3:
        return False
    # A child's word first. Otherwise a word the web says often, which is
    # a weaker signal but keeps a join from being dropped for want of one.
    if w in CHILD_WORDS:
        return True
    r = frequency_rank().get(w)
    return r is not None and r < EXAMPLE_MAX_RANK


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

    Order is the whole value here. Sorted alphabetically this list is
    useless for choosing words - the top of the alphabet is not the top of
    anything a child needs - so it is kept in the source's frequency order.

    Frequency is still only a starting point: the corpus is web text, so the
    commonest long words in it are things like "business" and "copyright".
    Anything shown to a child is curated on top of this, never taken from it
    raw. See sentences.LONGER_PACK.
    """
    global _common
    if _common is None:
        try:
            _common = (DICT_DIR / "common.txt").read_text(
                encoding="utf-8").split()
        except OSError:
            _common = []
    return _common


_rank = None


def frequency_rank() -> dict:
    """word -> position in the common list. Missing words rank last.

    Cached. It was not, and it is called from inside the loop over 110,000
    dictionary entries - twice per candidate, once by good_example() and once
    to rank it - so it rebuilt a ten-thousand-entry dict several tens of
    thousands of times. pair_catalog() took 74 seconds, and the app blocks on
    it the first time anything asks for a sound's example.
    """
    global _rank
    if _rank is None:
        _rank = {w: i for i, w in enumerate(common_words())}
    return _rank
