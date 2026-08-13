"""Build the shipped aligned dictionary from CMUdict.

    .venv/bin/python -m gen.build_dictionary

Fetches CMUdict (public domain) and the google-10000 common-words list,
converts ARPABET to the IPA this codebase speaks, ALIGNS each word's
letters to its sounds, and writes assets/dictionary/aligned.txt:

    said s=s ai=ɛ d=d
    nose n=n o=əʊ se=z

An entry means: this word may be built up, unit by unit, with each unit's
letters highlighted while its sound plays - and the alignment is trusted
because every correspondence in it is COMMON across English
(learned by expectation-maximisation over the whole dictionary, then
thresholded). A word whose best alignment needs a rare, lying
correspondence - "one" wanting o=/wʌ/ - is left out and shown whole,
which is exactly what phonics teachers do with it.

The aligner is deliberately small: units of 1-3 letters mapping to 0-2
phonemes (0 = silent letters, folded into the previous unit for display),
EM-trained alignment probabilities, Viterbi decode per word.

A unit carrying one phoneme is a GRAPHEME; one carrying two is a GRAPHEME
PAIR. See README.md for the glossary.
"""

from __future__ import annotations

import math
import re
import urllib.request
from collections import defaultdict

from gen.paths import RESOURCES

CMUDICT = "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"
COMMON = ("https://raw.githubusercontent.com/first20hours/"
          "google-10000-english/master/google-10000-english.txt")
DICT_DIR = RESOURCES / "assets" / "dictionary"
OUT = DICT_DIR / "graphemes.txt"
SYLLABLES_OUT = DICT_DIR / "syllables.txt"

ARPA_TO_IPA = {
    "AA": "ɒ", "AE": "æ", "AH": "ʌ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɜː",
    "EY": "eɪ", "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "iː",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "əʊ", "OY": "ɔɪ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "uː", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}

MAX_L, MAX_P = 3, 2      # unit sizes: letters 1-3, phonemes 0-2
EM_ROUNDS = 4

# Viterbi naturally prefers FEWER units (each adds a negative log
# probability), which bundles "was" into wa=wɒ s=z. A flat per-unit bonus
# tips it back toward fine splits - w=w a=ɒ s=z - which are what a child
# should see, and which map to single recordable sounds besides.
UNIT_BONUS = 3.0

# A GRAPHEME spells exactly one phoneme, and that is what this dictionary
# emits. Two-phoneme units are refused outright rather than merely penalised,
# because there is no such thing as a two-phoneme grapheme except in the three
# cases below - a letter that genuinely makes two sounds with no way to split
# the spelling.
#
# Measured over the whole corpus, every other common two-phoneme
# correspondence is splittable and was a bundle we did not want: ing, ar, on,
# in, st, an, en, le, tr, nd... all of them two graphemes glued together.
# Whitelisting the real ones and forbidding the rest replaces the tuning
# problem with a structural one, and takes the CVC words from 2 of 63 correct
# to all 63 without a penalty term at all.
TWO_PHONEME_GRAPHEMES = {
    ("x", ("k", "s")),        # box, six - one letter, two sounds
    ("u", ("j", "uː")),       # use, cute - the "yoo" u
    ("qu", ("k", "w")),       # queen - taught whole, because q never
                              # appears without its u
}


def unit_allowed(g: str, p: tuple) -> bool:
    """One phoneme per unit, plus the three graphemes that truly make two."""
    if len(p) <= 1:
        return True
    return (g.lower(), p) in TWO_PHONEME_GRAPHEMES


# A correspondence must be seen at least this often across the whole
# dictionary to be teachable; rarer ones are spelling lying about itself.
MIN_COUNT = 40

# Exception correspondences phonics programs TEACH even though they are
# rare by dictionary count - each carries some of the most common words in
# the language. Hand-vetted; a correspondence goes here only if a teacher
# would write it on the board, never just to lift the coverage number.
TAUGHT_EXCEPTIONS = {
    # The five short vowels. These are the first five correspondences any
    # phonics program teaches, and EM had them holding 0.76%, 6.6%, 4.1%,
    # 3.1% and - for u=ʌ - ZERO percent of their letters. That is not
    # English being surprising, it is a local minimum: every time the
    # decoder chose ha=hæ the bundle took the count and h= and a= took
    # none, so the halves weakened and the bundle strengthened, round after
    # round, until short u could not be isolated in cup or sun at any bonus.
    ("a", ("æ",)), ("e", ("ɛ",)), ("i", ("ɪ",)),
    ("o", ("ɒ",)), ("u", ("ʌ",)),

    ("ai", ("ɛ",)),            # said, again
    ("f", ("v",)),             # of
    ("o", ("uː",)),            # to, do, who
    ("o", ("ʌ",)),             # month, mother, son, come
    ("ou", ("uː",)),           # you, group, soup
    ("oul", ("ʊ",)),           # could, would, should
    ("ea", ("ɛ",)),            # head, ready, weather
    ("y", ("ɪ",)),             # gym, system
    ("a", ("ɒ",)),             # was, what, want
    ("ey", ("iː",)),           # key, money
    ("ie", ("ɛ",)),            # friend
    ("ai", ("ə",)),            # certain, captain
    ("a", ("ɔː",)),            # water, walk, tall
    # Doubled consonants are one sound - every teacher writes that on the
    # board - but a bare double is rarer than the units that bundle it, and
    # rubble lost its alignment to that arithmetic.
    ("bb", ("b",)), ("cc", ("k",)), ("dd", ("d",)), ("ff", ("f",)),
    ("gg", ("ɡ",)), ("ll", ("l",)), ("mm", ("m",)), ("nn", ("n",)),
    ("pp", ("p",)), ("rr", ("ɹ",)), ("ss", ("s",)), ("tt", ("t",)),
    ("zz", ("z",)),
}


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode("utf-8", errors="ignore")


def load_cmu():
    entries = []
    for line in fetch(CMUDICT).splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        w = parts[0].lower()
        if "(" in w or not w.isalpha() or len(w) < 2:
            continue
        ipa = []
        ok = True
        for p in parts[1:]:
            bare = re.sub(r"\d", "", p)
            if p == "AH0":
                ipa.append("ə")
            elif bare in ARPA_TO_IPA:
                ipa.append(ARPA_TO_IPA[bare])
            else:
                ok = False
                break
        if ok and ipa:
            entries.append((w, tuple(ipa)))
    return entries


def align_best(word, phons, prob, bonus):
    """Grapheme-only if possible, otherwise the best alignment there is.

    Refusing a word outright because one of its units needs two phonemes is
    the wrong trade: a word split into graphemes with a single pair in it is
    still a word a child can be walked through, while a refused word is shown
    whole and sounded out not at all. Strict first, so the pair only appears
    where nothing else works - measured at under 1 word in 8, and those are
    the genuinely awkward ones (actual = /aektSuwel/, adjacent).
    """
    a = align(word, phons, prob, bonus, strict=True)
    return a if a is not None else align(word, phons, prob, bonus, strict=False)


def align(word, phons, prob, bonus=0.0, strict=False):
    """Best alignment of `word` against `phons` under `prob`. Returns a list
    of (letters, phoneme-tuple) or None. Standard DP over (i, j).

    `bonus` (per unit, favouring fine splits) applies only to the FINAL
    decode. Inside EM it must stay zero: a biased decode feeds biased
    counts to the next round, and the bias compounds until the learned
    statistics are about the bonus rather than about English."""
    n, m = len(word), len(phons)
    best = [[(-math.inf, None)] * (m + 1) for _ in range(n + 1)]
    best[0][0] = (0.0, None)
    for i in range(n + 1):
        for j in range(m + 1):
            score, _ = best[i][j]
            if score == -math.inf:
                continue
            for dl in range(1, MAX_L + 1):
                if i + dl > n:
                    break
                for dp in range(0, MAX_P + 1):
                    if j + dp > m or (dl == 0 and dp == 0):
                        continue
                    g = word[i:i + dl]
                    p = phons[j:j + dp]
                    s = prob.get((g, p))
                    if s is None:
                        continue
                    # The whitelist applies only to the FINAL decode, the
                    # same as `bonus`: EM must be left to learn what English
                    # actually does, and a biased decode feeds biased counts
                    # to the next round until the statistics are about the
                    # bias rather than the language.
                    if strict and not unit_allowed(g, p):
                        continue
                    cand = score + s + bonus
                    if cand > best[i + dl][j + dp][0]:
                        best[i + dl][j + dp] = (cand, (i, j, dl, dp))
    if best[n][m][0] == -math.inf:
        return None
    out = []
    i, j = n, m
    while (i, j) != (0, 0):
        _, back = best[i][j]
        i0, j0, dl, dp = back
        out.append((word[i0:i0 + dl], tuple(phons[j0:j0 + dp])))
        i, j = i0, j0
    return out[::-1]


def train(entries):
    """EM for correspondence weights: seed uniformly over everything
    plausible, decode, re-count, repeat."""
    # seed: every letters/phoneme-run co-occurrence within a loose window
    counts = defaultdict(float)
    for w, ph in entries:
        for i in range(len(w)):
            for dl in range(1, MAX_L + 1):
                if i + dl > len(w):
                    break
                for j in range(len(ph) + 1):
                    for dp in range(0, MAX_P + 1):
                        if j + dp > len(ph):
                            break
                        counts[(w[i:i + dl], tuple(ph[j:j + dp]))] += 1.0 / (dl + dp + 1)
    for _ in range(EM_ROUNDS):
        prob = to_logprob(counts)
        counts = defaultdict(float)
        for w, ph in entries:
            a = align(w, ph, prob)
            if a:
                for g, p in a:
                    counts[(g, p)] += 1.0
    return counts


def to_logprob(counts):
    total_by_g = defaultdict(float)
    for (g, _), c in counts.items():
        total_by_g[g] += c
    return {(g, p): math.log(c / total_by_g[g])
            for (g, p), c in counts.items() if c > 0}


def build_syllables(words) -> int:
    """Write word -> syllable split, from hyphenation patterns.

    A SEPARATE dictionary rather than a view of the grapheme one, because
    syllable boundaries genuinely are not derivable from a letters-to-sounds
    alignment: nothing in "rabbit" being r/a/bb/i/t says whether it divides
    rab-bit or ra-bbit. That is its own question with its own data.

    Hyphenation patterns are the data. They are not quite syllabification -
    they mark where a typesetter may break a line, which is conservative:
    "elephant" comes back ele-phant where a phonics teacher would say
    el-e-phant. Conservative is the right failure here, because a break in
    the wrong place teaches a wrong word shape, while a missing break just
    teaches a longer piece.

    Computed at build time and shipped as text, like the grapheme dictionary,
    so the app never needs pyphen at runtime and the frozen sidecar does not
    have to carry it.
    """
    try:
        import pyphen
    except ImportError:
        print("pyphen not installed - skipping the syllable dictionary")
        return 0
    dic = pyphen.Pyphen(lang="en_US")
    lines = []
    for w in sorted(words):
        if len(w) < 4:
            continue                      # nothing to divide
        split = dic.inserted(w)
        if "-" not in split:
            continue                      # one syllable; the word IS the unit
        lines.append(f"{w} {split}")
    SYLLABLES_OUT.parent.mkdir(parents=True, exist_ok=True)
    SYLLABLES_OUT.write_text(
        "# word  syl-la-ble-split   built by gen/build_dictionary.py\n"
        "# from en_US hyphenation patterns (pyphen). Break points, which are\n"
        "# conservative: a missing break is safer than a wrong one.\n"
        + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main():
    entries = load_cmu()
    print(f"{len(entries)} dictionary words")
    # A LIST, in the source's frequency order. It used to be a set written
    # out sorted, which threw the frequency away - and frequency is the only
    # thing that makes this list useful at all. Sorted alphabetically it just
    # returns the top of the alphabet, which is not the top of anything.
    #
    # This list is raw web-frequency data and is never shown to a child
    # directly. It feeds derivations and example-picking; the packs a parent
    # can tap are curated by hand.
    common_order = [w.strip().lower() for w in fetch(COMMON).splitlines()
                    if w.strip()]
    common = set(common_order)

    counts = train(entries)
    # teachable correspondences only - and silent units only for the
    # letters that genuinely go silent in English spelling
    kept = {k: c for k, c in counts.items() if c >= MIN_COUNT}
    # A taught exception must be COMPETITIVE, not merely present: "a" has a
    # six-figure count total, so a flat pseudo-count leaves a=ɒ at log-prob
    # -8 and every consonant+vowel bundle beats it. Give each exception a
    # fixed few percent of its grapheme's mass instead.
    grapheme_mass = defaultdict(float)
    for (g, _), c in counts.items():
        grapheme_mass[g] += c
    for (g, p) in TAUGHT_EXCEPTIONS:
        kept[(g, p)] = max(kept.get((g, p), 0.0),
                           float(MIN_COUNT), 0.08 * grapheme_mass[g])
    prob = to_logprob(kept)
    print(f"{len(prob)} teachable correspondences")

    # Initializms are not words: "dvd" is said as letter names, cannot be
    # sounded out, and must not count against coverage either.
    def is_word(w):
        return any(c in "aeiouy" for c in w)

    lines, aligned_common, total_common = [], 0, 0
    aligned_all = 0
    for w, ph in entries:
        a = align_best(w, ph, prob, UNIT_BONUS)
        if w in common and is_word(w):
            total_common += 1
        if a is None:
            continue
        # fold silent units into the previous unit for display
        merged = []
        for g, p in a:
            if not p and merged:
                pg, pp = merged[-1]
                merged[-1] = (pg + g, pp)
            elif not p and not merged:
                merged.append((g, p))  # leading silent letters stay put
            else:
                merged.append((g, p))
        if any(not p for _, p in merged):
            continue  # a word that is ONLY silence is not a word
        # A whole word as ONE unit has no buildup - "is=ɪz" is just the
        # word repeated. When letters and sounds pair one to one, split
        # them; the runtime applies the same guard to older data.
        if len(merged) == 1 and len(w) > 1:
            g, p = merged[0]
            if len(p) == len(g):
                merged = list(zip(list(g), [(x,) for x in p]))
        aligned_all += 1
        if w in common and is_word(w):
            aligned_common += 1
        lines.append(w + " " + " ".join(f"{g}={''.join(p)}" for g, p in merged))

    lines.sort()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# word  letters=sound ...  built by gen/build_dictionary.py\n"
        "# from CMUdict (public domain); alignment learned by EM, rare\n"
        "# correspondences dropped so every unit shown is teachable.\n"
        + "\n".join(lines) + "\n", encoding="utf-8")
    # The common words, separately: the catalog picks its example words
    # from these, because CMUdict's shortest words are names and noise -
    # "ring" teaches /ɪŋ/, "ibn" teaches nothing but doubt.
    (OUT.parent / "common.txt").write_text(
        "\n".join(w for w in common_order if w.isalpha() and len(w) > 1)
        + "\n", encoding="utf-8")
    # The grapheme-pair catalog, baked. It is derived from the file written
    # above, so it can only change when this script runs - and deriving it
    # walks every unit of all 110,000 entries, which is seconds nobody should
    # pay for at startup.
    from gen import dictionary

    dictionary._cache = None          # read what we just wrote, not a stale copy
    dictionary._catalog = None
    pairs = dictionary.derive_pair_catalog()
    (DICT_DIR / "pairs.txt").write_text(
        "# ipa\tspelling\texample\twords   built by gen/build_dictionary.py\n"
        "# Grapheme pairs: two adjacent graphemes a recording can join in one\n"
        "# breath. Example words are gated - see dictionary.good_example.\n"
        + "\n".join(f"{c['ipa']}\t{c['spelling']}\t{c['example']}\t{c['words']}"
                    for c in pairs) + "\n", encoding="utf-8")
    print(f"wrote {len(pairs)} grapheme pairs")

    n_syl = build_syllables({w for w, _ in entries})
    print(f"wrote {n_syl} syllable splits")
    print(f"wrote {aligned_all} aligned words "
          f"({aligned_all * 100 // len(entries)}% of all)")
    print(f"common words aligned: {aligned_common}/{total_common} "
          f"({aligned_common * 100 // max(total_common, 1)}%)")


if __name__ == "__main__":
    main()
