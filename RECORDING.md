# Recording session guide

For the parent doing the recording. About 40 minutes. A phone is fine.

Everything you record here becomes the voice your child hears every day. Levels 1–5 use
your recordings **exactly as you say them** — nothing is synthesised. Only the later
levels, which are a long way off, use a computer-generated version of your voice.

---

## Before you start

- **Quiet room.** Turn off fans, dishwasher, TV. Soft furnishings help; a bedroom is
  better than a kitchen.
- **Phone about a hand's width from your mouth**, slightly off to the side so your
  breath doesn't hit the mic.
- **Voice memo app is fine.** One long recording per section is easier than 110 files —
  we'll split them up afterwards.
- **Leave a clear gap** (2 seconds of silence) between each item. That's what lets us
  split them automatically.
- **If you fluff one, just pause and say it again.** We keep the last good take.
- Don't perform. Ordinary, warm, how you'd talk to them.

---

## Part 1 — The sounds (~15 min)

This is the most important part, and the easiest to get subtly wrong.

### The one rule that matters

**Say the pure sound, with no "uh" on the end.**

- `t` is a short, crisp *t* — **not** "tuh"
- `s` is a long hiss, *sssss* — **not** "suh"
- `m` is a long hum, *mmmmm* — **not** "muh"

Why this matters: if you record "cuh", "a", "tuh", then your child hears "cuh-a-tuh", which
doesn't turn into "cat". This is the single most common reason home phonics stalls.

### Stretch the ones that stretch

Some sounds can be held for a long breath. **Hold these for a second or two —
longer than feels natural, but don't strain:**

> `s` `f` `m` `n` `l` `r` `v` `z` `sh` `th` `ng` — and every vowel

Some sounds physically cannot be held — they're a tiny burst and then they're gone.
**Say these once, crisply, and don't try to stretch them:**

> `p` `t` `k` `b` `d` `g` `ch` `j`

That's not a limitation of the recording — it's how those sounds work. Nobody can hold
a *t*.

### What to say

**Open the app, go to “Your voice”, and press “Show what to say”.** It prints a
numbered list in the exact order the app expects, so nothing can get out of step.

That matters more than it sounds: the app matches what it hears to the list *by
position*. If item 7 and item 8 are swapped, every name from there on is wrong.

The printed list also tells you, for each sound, whether to hold it or keep it
crisp. There is no table to interpret and no order to guess at.

> Earlier versions of this guide printed the sounds as two side-by-side columns.
> That was a mistake: a two-column table can be read across or downwards, and the
> two give different orders. The generated list replaced it.

**Or skip the phone entirely.** The same screen has **“Record the sounds”**,
which shows each sound on screen, records a few goes, keeps the best one, and
tells you straight away if something needs another try. That is the easier path,
and the one to use if the computer is to hand.

## Part 2 — The sight words (~15 min)

Say each word **normally**, the way you'd say it in a sentence. Don't sound it out,
don't over-enunciate. Just the word, warmly.

### The words are yours to choose

Open **[`wordlists/sight-words.txt`](wordlists/sight-words.txt)** in any text editor
(Notepad, TextEdit, anything) and make it your list. Add words, delete words, change
them. One word per line. Lines starting with `#` are just notes.

**The same file does two jobs**, so you only write your list once:

1. it becomes your recording checklist, and
2. it becomes what your child actually sees on the TV.

Add "Bluey" and you'll be asked to record "Bluey", and then "Bluey" starts appearing in
their videos. There's no second step.

The **[People]** group is the one to change first. It ships with example names — Alex,
Mum, Dad, Nana, Grandad — and those should be your real ones: their brothers and sisters,
your pets, anyone they see often. This group matters more than the rest put together.
The research on reading and Down syndrome is specific about it: start with words that
mean something to them personally, because those are the ones they'll learn fastest.

Start small. Ten words they love beats fifty they don't.

### Print your checklist

Once you've edited the file, this prints your list back with numbers, ready to record
from:

```
python -m gen.wordlists
```

*(Later on, the app will have a proper screen for this — no text files. For now this is
the quickest way to get your own words in.)*

---

## Part 3 — The reading passage (~6 min) — **please don't skip this**

Read **[PASSAGE.md](PASSAGE.md)** out loud, start to finish, naturally — as if reading
to your child. Normal pace, normal expression. Let the questions sound like questions.

It's six short sections with breaks, so you can stop and start.

This part is never played back to them. It's what lets the computer learn the shape of
your voice — the rhythm, the melody, how your sentences rise and fall. Single words
can't teach it any of that, because single words don't contain it. This passage is the
difference between the later levels sounding like you and sounding like a robot wearing
your voice.

**Why that particular passage, and not just any book?** It's written to contain every
single sound in English several times over — verified by machine, 43 of 43 covered,
nothing scarce. A random book leaves gaps, and any sound the computer never hears from
you, it has to invent. That's why one or two sentences read a little oddly; they're
there to catch the rare sounds like the *oy* in "boy" and the *s* in "treasure".

---

## When you're done

Send the files over however is easiest. Nothing needs renaming or trimming — the
splitting is automatic.
