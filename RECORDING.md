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

Some sounds can be held for a long breath. **Hold these for about 2 seconds:**

> `s` `f` `m` `n` `l` `r` `v` `z` `sh` `th` `ng` — and every vowel

Some sounds physically cannot be held — they're a tiny burst and then they're gone.
**Say these once, crisply, and don't try to stretch them:**

> `p` `t` `k` `b` `d` `g` `ch` `j`

That's not a limitation of the recording — it's how those sounds work. Nobody can hold
a *t*.

### What to say

Don't worry about symbols. For each row, **say the sound at the start of the example
word, on its own.** The word is only there to remind you which sound we mean.

**Consonants**

| Sound | as in | | Sound | as in |
|---|---|---|---|---|
| s | **s**un (hold it) | | m | **m**an (hold it) |
| t | **t**op (crisp) | | n | **n**et (hold it) |
| p | **p**an (crisp) | | ng | ri**ng** (hold it) |
| k | **c**at (crisp) | | l | **l**eg (hold it) |
| b | **b**at (crisp) | | r | **r**un (hold it) |
| d | **d**og (crisp) | | w | **w**et |
| g | **g**ot (crisp) | | y | **y**es |
| f | **f**an (hold it) | | h | **h**at |
| v | **v**an (hold it) | | sh | **sh**op (hold it) |
| z | **z**ip (hold it) | | ch | **ch**ip (crisp) |
| th | **th**in (hold it) | | j | **j**am (crisp) |
| th | **th**is (hold it, voiced) | | zh | vi**si**on (hold it) |

**Vowels** — hold every one for about 2 seconds.

| Sound | as in | | Sound | as in |
|---|---|---|---|---|
| a | c**a**t | | ee | s**ee** |
| e | b**e**d | | oo | m**oo**n |
| i | s**i**t | | or | d**oor** |
| o | d**o**g | | ur | h**er** |
| u | c**u**p | | ay | d**ay** |
| oo | p**u**t | | igh | m**y** |
| ar | c**ar** | | oy | b**oy** |
| ow | n**ow** | | oa | g**o** |
| air | h**air** | | ear | n**ear** |

---

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
