# How the voice works

Two questions are answered for every word, by two separate systems.

Vocabulary here is the one defined in [the README glossary](../README.md#glossary):
a **grapheme** is letters spelling one phoneme, a **grapheme pair** is an alignment
unit carrying two, and **unit** covers either.

## 1. What should be said — the aligned dictionary

`assets/dictionary/aligned.txt` (built by `gen/build_dictionary.py`, loaded
by `gen/dictionary.py`): 110,000 words, each split into units of letters
matched to the sound those letters make in that word:

    grandma  g=ɡ r=ɹ an=æn d=d ma=mɒ
    said     s=s ai=ɛ d=d

Most units are graphemes — `g=ɡ`, `s=s`, `ai=ɛ`. A few carry two phonemes
and are grapheme pairs — `an=æn`, `ma=mɒ`.

The alignment is learned (EM over all of CMUdict), rare "lying"
correspondences are dropped, and a hand-vetted set of taught exceptions
(ai=/ɛ/ in said, oul=/ʊ/ in could) is kept competitive. A word the
dictionary cannot vouch for falls through, in order, to:

1. the small voiced-s lexicon (`levels.WORD_SOUNDS`),
2. the spelling rules (`levels.split_graphemes`) - these serve names and
   nonsense words, which no dictionary knows,
3. refusal: a word whose spelling genuinely lies ("one") is shown whole
   and spoken whole, exactly as reading teachers treat it.

Coverage: 94% of the 10,000 most common words, 93% of all 117k, each one
split the way a phonics teacher would board it.

## 2. How each unit sounds — the sound bank

Every unit carries a sound label (/æn/). It is played by, in order:

1. **the family's recording** of that exact sound (aliases included -
   /æ/ answers for /a/, the recorded /ʌ/ answers for the schwa),
2. **the shipped starter clip** - the 42 phonemes plus the 60 magic-e
   recordings,
3. **a join**: the label is split into its member phonemes
   (`dictionary.phonemes_in`) and the clips are crossfaded together -
   /æn/ = /æ/ + /n/.

The invariant, enforced by test: every unit sound the dictionary can ever
emit decomposes into the 42 phonemes, so everything is speakable and
nothing new ever HAS to be recorded. Recorded grapheme-pair clips are a
quality upgrade, not a requirement - a clip saved as
`phonemes/<sound>.wav` automatically beats the join everywhere, for the
family and the starter voice alike, because the bank is keyed by sound.

That is the whole justification for grapheme pairs existing. A pair is not
a teaching unit and is never claimed to be one; it is the difference
between /kæ/ as one human breath and /k/ + /æ/ as two clips with a seam.

Measured across the dictionary: 406 distinct unit sounds - 38 single
phonemes played straight from the 42, 30 covered by magic-e recordings,
338 played as joins. The most-used joined pairs (ɪŋ, ɪn, æn, ən, əl...)
are the natural candidates if smoother audio is ever wanted.

## Whole words and lines

Words and whole-line reads are never assembled from sounds - connected
speech has melody that joins do not. They resolve: the family's clip →
the starter bank's clip (pack content ships fully recorded) → the
family's clone (optional voice pack) → an honest error naming the word
and what to do about it. Isolated sounds are never cloned: cloning is
worst at exactly them, and a wrong sound teaches a wrong thing. There is
no synthesiser anywhere.

Sounding out is the one place assembly is correct rather than tolerated -
there the seam is the lesson. Even there the longest recorded thing wins:
a recorded pair before two phonemes joined, because a seam the child is
not meant to hear should not be there.

## Time budgets in the buildup

Approach passes cap each unit's clip so the highlight sweeps evenly -
budgeted PER SOUND (`_sounds_in`), because a pair like /æn/ carries two
phonemes and a one-sound budget amputates the second. The final pass
crossfades the units into one continuous almost-word before the real
word answers.
