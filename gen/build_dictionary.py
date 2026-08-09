"""Build the shipped aligned dictionary from CMUdict.

    .venv/bin/python -m gen.build_dictionary

Fetches CMUdict (public domain) and the google-10000 common-words list,
converts ARPABET to the IPA this codebase speaks, ALIGNS each word's
letters to its sounds, and writes assets/dictionary/aligned.txt:

    said s=s ai=ɛ d=d
    nose n=n o=əʊ se=z

An entry means: this word may be built up, chunk by chunk, with each
chunk's letters highlighted while its sound plays - and the alignment is
trusted because every chunk correspondence in it is COMMON across English
(learned by expectation-maximisation over the whole dictionary, then
thresholded). A word whose best alignment needs a rare, lying
correspondence - "one" wanting o=/wʌ/ - is left out and shown whole,
which is exactly what phonics teachers do with it.

The aligner is deliberately small: chunks of 1-3 letters mapping to 0-2
phonemes (0 = silent letters, folded into the previous chunk for
display), EM-trained alignment probabilities, Viterbi decode per word.
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
OUT = RESOURCES / "assets" / "dictionary" / "aligned.txt"

ARPA_TO_IPA = {
    "AA": "ɒ", "AE": "æ", "AH": "ʌ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɜː",
    "EY": "eɪ", "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "iː",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "əʊ", "OY": "ɔɪ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "uː", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}

MAX_L, MAX_P = 3, 2      # chunk sizes: letters 1-3, phonemes 0-2
EM_ROUNDS = 4
# Viterbi naturally prefers FEWER chunks (each chunk adds a negative log
# probability), which bundles "was" into wa=wɒ s=z. A flat per-chunk bonus
# tips it back toward fine splits - w=w a=ɒ s=z - which are what a child
# should see, and which map to single recordable sounds besides.
CHUNK_BONUS = 1.2
# A correspondence must be seen at least this often across the whole
# dictionary to be teachable; rarer ones are spelling lying about itself.
MIN_COUNT = 40

# Exception correspondences phonics programs TEACH even though they are
# rare by dictionary count - each carries some of the most common words in
# the language. Hand-vetted; a correspondence goes here only if a teacher
# would write it on the board, never just to lift the coverage number.
TAUGHT_EXCEPTIONS = {
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


def align(word, phons, prob, bonus=0.0):
    """Best chunking of `word` against `phons` under `prob`. Returns a list
    of (letters, phoneme-tuple) or None. Standard DP over (i, j).

    `bonus` (per chunk, favouring fine splits) applies only to the FINAL
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
    """EM for chunk correspondence weights: seed uniformly over everything
    plausible, decode, re-count, repeat."""
    # seed: every chunk/phoneme-run co-occurrence within a loose window
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


def main():
    entries = load_cmu()
    print(f"{len(entries)} dictionary words")
    common = {w.strip().lower() for w in fetch(COMMON).splitlines()}

    counts = train(entries)
    # teachable correspondences only - and silent chunks only for the
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

    # Initialisms are not words: "dvd" is said as letter names, cannot be
    # sounded out, and must not count against coverage either.
    def is_word(w):
        return any(c in "aeiouy" for c in w)

    lines, aligned_common, total_common = [], 0, 0
    aligned_all = 0
    for w, ph in entries:
        a = align(w, ph, prob, bonus=CHUNK_BONUS)
        if w in common and is_word(w):
            total_common += 1
        if a is None:
            continue
        # fold silent chunks into the previous chunk for display
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
        aligned_all += 1
        if w in common and is_word(w):
            aligned_common += 1
        lines.append(w + " " + " ".join(f"{g}={''.join(p)}" for g, p in merged))

    lines.sort()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# word  letters=sound ...  built by gen/build_dictionary.py\n"
        "# from CMUdict (public domain); alignment learned by EM, rare\n"
        "# correspondences dropped so every chunk shown is teachable.\n"
        + "\n".join(lines) + "\n", encoding="utf-8")
    # The common words, separately: the catalog picks its example words
    # from these, because CMUdict's shortest words are names and noise -
    # "ring" teaches /ɪŋ/, "ibn" teaches nothing but doubt.
    (OUT.parent / "common.txt").write_text(
        "\n".join(sorted(w for w in common
                         if w.isalpha() and len(w) > 1)) + "\n",
        encoding="utf-8")
    print(f"wrote {aligned_all} aligned words "
          f"({aligned_all * 100 // len(entries)}% of all)")
    print(f"common words aligned: {aligned_common}/{total_common} "
          f"({aligned_common * 100 // max(total_common, 1)}%)")


if __name__ == "__main__":
    main()
