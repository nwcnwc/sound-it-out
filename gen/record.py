"""Record the whole sound bank from the terminal, one take per item.

    python -m gen.record tone                 # room tone first - do this
    python -m gen.record phonemes
    python -m gen.record words --redo
    python -m gen.record --all

## Why single takes

gen/studio.py records three takes of a phoneme and keeps the best, because an
isolated /t/ is genuinely hard to say without an "uh" on the end and picking
the best of three is what keeps a schwa out of the library.

That logic holds for a parent recording once. It does not hold for someone
recording the entire bank repeatedly: three takes of 330 items is a thousand
utterances, the speaker gets worse across that hour, not better, and the
scorer already knows the difference between a good take and a bad one.

So this records once and keeps moving. The scorer still runs on every take -
it just interrupts instead of comparing. A clean take advances by itself; a
fatal one (schwa, clipping, silence) stops and asks for another; a merely
weak one says what is wrong, keeps it, and lets you decide.

The result is the same library gen/studio.py writes, in the same places,
scored by the same code. It is a different pace, not a different standard.

## Why the room tone comes first

`record tone` captures 30 seconds of the room saying nothing. It is not
subtracted from anything later - noise is random, so subtracting a recording
of it from a different recording of it adds noise rather than removing it.
It earns its place three other ways:

  1. it tells you the room is quiet enough BEFORE you spend an hour in it
  2. it calibrates the silence gate below, so auto-stop works in your room
     rather than at some threshold guessed on someone else's
  3. it lets tonight be compared against last night, which is the only way
     to catch the drift between sessions that no per-clip measurement sees

## Capture

ffmpeg to PulseAudio. ffmpeg is already a hard dependency of the video
pipeline, so this adds nothing to install - which matters more than it
sounds, because the alternative (sounddevice/PortAudio) is a wheel that has
to build, on a machine whose whole job is to be a cheap Chromebook.
"""

from __future__ import annotations

import argparse
import select
import subprocess
import sys
import termios
import tty
from pathlib import Path

import numpy as np
import soundfile as sf

from gen import sentences as S
from gen import studio
from gen.paths import BANK_DIRS, STARTER_VOICE, VOICE_DIR
from gen.soundout import SR
from gen.voice import sentence_key

# The two banks, and why writing to one is not the same as writing to both.
#
#   user     assets/voice/          gitignored, this machine only
#   starter  assets/starter-voice/  tracked in git, SHIPS in the release
#
# gen/voice.py resolves a sound by trying the user's recordings first and the
# starter set only if that misses. For most people that is the whole story:
# they record, and their own voice wins.
#
# It is not the whole story for whoever records the starter set, because they
# are both people at once. Recording only into `starter` leaves their own app
# still playing the older clips in `user` - so the shipped default changes and
# the thing they audition does not, which is the wrong way round for catching
# a bad take. Hence `both`, which is the sane default for that one person.
TARGETS = {"user": VOICE_DIR, "starter": STARTER_VOICE}

# Room tone is a diagnostic, not content: it calibrates the gate and compares
# sessions. It must never land in the starter set, which is tracked and would
# ship 30 seconds of someone's kitchen to every install.
TONE_PATH = VOICE_DIR / "room-tone.wav"
TONE_SECONDS = 30

BLOCK = 1024                 # samples per read; ~43 ms at 24 kHz
MAX_SECONDS = 12.0           # hard cap, so a stuck gate cannot run forever
LEAD_SECONDS = 8.0           # give up waiting for speech after this
HANG_MS = 900                # silence after speech before auto-stop
FLOOR_FALLBACK = 0.004       # gate floor with no room tone measured

PARTS = ("phonemes", "magic-e", "pairs", "words", "sentences")

# What --all records, and in what order. "magic-e" is deliberately absent.
#
# Every one of its 60 distinct sounds is also in "pairs", and both parts key
# their file by IPA - so /aɪb/ is written by the rime "ibe" and again by the
# pair "ib", to the same aɪb.wav. Recording both is one wasted take in sixty
# and the second one silently wins. gen/studio.py already half-knows this: its
# pairs section notes that "magic-e recordings made before this list existed
# appear here as done".
#
# The part still exists and can be asked for by name. Its prompts are the
# better ones for those sixty - "Say the ending 'ibe' ... No word around it",
# against the pair list's "Say 'ib' as in 'tribe'", which names a spelling
# that does not appear in the anchor word.
ALL_ORDER = ("phonemes", "pairs", "words", "sentences")


# ------------------------------------------------------------------ plan

def plan_for(part: str, path: Path | None = None) -> list:
    """What to record, for one part.

    Phonemes, magic-e and grapheme pairs are fixed inventories of the language
    and come
    from gen/studio.py unchanged. Words and sentences do NOT: both are read
    out of one file, one sentence per line, and the words are the words IN
    those sentences rather than a second list kept alongside.

    That is the whole point of the arrangement. A word list maintained apart
    from the sentence list drifts from it in both directions - words recorded
    that nothing ever says, and sentences that need a word nobody recorded -
    and the second kind is silent until a video reaches that word and has no
    voice for it. Deriving one from the other cannot drift.

    gen/sentences.py already owns the file and its parsing, including the
    distinction between a line that is a letter, a single word, or a real
    sentence. A one-word line has no separate whole-line read - the word IS
    the line - and a single letter has nothing to record here at all, because
    the 42 sounds are recorded once as phonemes and shared by everything.
    """
    if part in ("phonemes", "magic-e", "pairs"):
        return studio.plan(part)

    if path is not None:
        S.SENTENCES_FILE = path        # module owns the location; honor --file
    entries = S.load()

    if part == "sentences":
        return [studio.Item(key=sentence_key(t), kind="sentence", display=t,
                            length="line",
                            say="Read the whole line the way you would to a "
                                "child - not word by word.")
                for t in entries if S.entry_kind(t) == "sentence"]

    if part == "words":
        # First appearance order, not alphabetical: recording "Chase is on the
        # case" as chase/is/on/the/case keeps you in the context you just read,
        # which is faster and produces a more natural take than jumping between
        # unrelated words.
        seen, items = set(), []
        for text in entries:
            if S.entry_kind(text) == "letter":
                continue
            for raw in text.split():
                w = S._clean(raw)
                if not w or w.lower() in seen:
                    continue
                seen.add(w.lower())
                items.append(studio.Item(
                    key=w.lower(), kind="word", display=w, length="free",
                    say="Say it normally, the way you would in a sentence."))
        return items

    raise ValueError(f"unknown part {part!r}")


def missing_sight_words(path: Path | None = None) -> list:
    """Sight words that no sentence contains, and so nothing will record.

    wordlists/sight-words.txt still decides what appears on screen, so a word
    there but in no sentence is a word a video can show and cannot say.
    """
    from gen import wordlists

    try:
        listed = [w for w in wordlists.all_words()]
    except Exception:
        return []
    have = {i.key for i in plan_for("words", path)}
    return [w for w in listed if w.lower() not in have]


def roots_for(target: str) -> list:
    """Directories a take is written to, primary first."""
    if target == "both":
        return [TARGETS["user"], TARGETS["starter"]]
    return [TARGETS[target]]


def _at(root: Path, fn, *a):
    """Run a studio call with its bank pointed at `root`.

    studio.Item.path() reads gen.studio's module-level VOICE_DIR, so rebinding
    it is what redirects both the write and the done() probe. Restored in a
    finally, because a half-redirected module would write the next part to the
    wrong bank entirely.
    """
    old = studio.VOICE_DIR
    studio.VOICE_DIR = root
    try:
        return fn(*a)
    finally:
        studio.VOICE_DIR = old


def save_all(roots: list, item, audio) -> list:
    return [_at(r, studio.save, item, audio) for r in roots]


def done_in(root: Path, item) -> bool:
    return _at(root, item.done)


# ------------------------------------------------------------------ term

class Term:
    """Raw-mode keyboard with a cooked-mode escape hatch."""

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        try:
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            self.raw = True
        except (termios.error, ValueError):
            self.saved, self.raw = None, False   # piped stdin; keys unavailable
        return self

    def __exit__(self, *a):
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def key(self, timeout=None):
        """One keypress, or '' if `timeout` elapses first."""
        if not self.raw:
            return sys.stdin.readline()[:1] or "q"
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return sys.stdin.read(1) if r else ""


C = {"dim": "\x1b[2m", "b": "\x1b[1m", "r": "\x1b[0m", "red": "\x1b[31m",
     "grn": "\x1b[32m", "yel": "\x1b[33m", "cyn": "\x1b[36m", "clr": "\x1b[2K\r"}


def say(s=""):
    print(s, flush=True)


def rule(width=64):
    say(C["dim"] + "─" * width + C["r"])


def db(x):
    return 20 * np.log10(max(float(x), 1e-9))


def meter(rms, width=26):
    """A level bar in dBFS, green in the useful range, red near clipping."""
    d = db(rms)
    fill = int(np.clip((d + 60) / 60, 0, 1) * width)
    col = C["red"] if d > -3 else C["grn"] if d > -30 else C["yel"]
    return f"{col}{'█' * fill}{C['dim']}{'░' * (width - fill)}{C['r']} {d:>6.1f} dB"


# --------------------------------------------------------------- capture

def _ffmpeg(device: str):
    return subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "pulse", "-i", device, "-ac", "1", "-ar", str(SR),
         "-f", "f32le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)


def capture(term: Term, device: str, gate: float, seconds=None, label="REC"):
    """Record until silence, a keypress, or the cap. Returns float32 mono.

    Returns None if the user pressed q. The gate is derived from measured room
    tone where available, because a threshold that works in a quiet bedroom
    mistakes a fridge for speech in a kitchen.
    """
    proc = _ffmpeg(device)
    buf, started, quiet = [], False, 0
    hang = int(SR * HANG_MS / 1000)
    cap = int(SR * (seconds or MAX_SECONDS))
    lead = int(SR * LEAD_SECONDS)
    total = 0
    try:
        while True:
            raw = proc.stdout.read(BLOCK * 4)
            if not raw:
                break
            block = np.frombuffer(raw, dtype="<f4")
            buf.append(block)
            total += block.size
            rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0

            if seconds is None:
                if rms > gate:
                    started, quiet = True, 0
                elif started:
                    quiet += block.size
                elapsed = total / SR
                tag = f"{C['red']}●{C['r']} {label}" if started else \
                      f"{C['dim']}○ waiting{C['r']}"
                print(f"{C['clr']}  {tag} {elapsed:>5.1f}s  {meter(rms)}"
                      f"   {C['dim']}[enter] stop{C['r']}", end="", flush=True)
                if started and quiet >= hang:
                    break
                if not started and total >= lead:
                    break
            else:
                left = max(0.0, seconds - total / SR)
                print(f"{C['clr']}  {C['red']}●{C['r']} {label} "
                      f"{left:>5.1f}s left  {meter(rms)}", end="", flush=True)

            if total >= cap:
                break
            k = term.key(0)
            if k in ("\n", "\r", " "):
                break
            if k == "q":
                print(C["clr"], end="")
                return None
    finally:
        proc.kill()
        proc.stdout.close()
        proc.wait()
    print(C["clr"], end="", flush=True)
    return np.concatenate(buf).astype("float32") if buf else np.zeros(0, "float32")


# ------------------------------------------------------------- room tone

def measured_gate() -> float:
    """Silence threshold from the recorded room tone, or a safe default."""
    if not TONE_PATH.exists():
        return FLOOR_FALLBACK
    a, _ = sf.read(TONE_PATH, dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(axis=1)
    floor = float(np.sqrt(np.mean(a ** 2)))
    # Four times the room, and never below the fallback: speech onset clears
    # this comfortably, a fridge cycling does not.
    return max(floor * 4.0, FLOOR_FALLBACK)


def do_tone(term: Term, device: str) -> int:
    say(f"\n  {C['b']}Room tone{C['r']} - {TONE_SECONDS} seconds of the room, "
        f"saying nothing.\n")
    say(f"  {C['dim']}Sit still. Don't talk, don't type, don't move the "
        f"laptop.{C['r']}")
    say(f"  {C['dim']}This calibrates the auto-stop and lets tonight be "
        f"compared to last night.{C['r']}\n")
    say(f"  [enter] start   [q] quit")
    if term.key() == "q":
        return 1

    prev = None
    if TONE_PATH.exists():
        a, _ = sf.read(TONE_PATH, dtype="float32", always_2d=False)
        prev = db(np.sqrt(np.mean((a if a.ndim == 1 else a.mean(1)) ** 2)))

    audio = capture(term, device, 0.0, seconds=TONE_SECONDS, label="tone")
    if audio is None or audio.size == 0:
        say("  nothing captured")
        return 1

    floor = db(np.sqrt(np.mean(audio ** 2)))
    peak = db(np.abs(audio).max())
    TONE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TONE_PATH.exists():
        TONE_PATH.replace(TONE_PATH.with_suffix(".previous.wav"))
    sf.write(TONE_PATH, audio, SR)

    say(f"\n  floor {C['b']}{floor:.1f} dBFS{C['r']}   peak {peak:.1f} dBFS")
    if prev is not None:
        d = floor - prev
        word = ("the same as" if abs(d) < 1.5 else
                f"{abs(d):.1f} dB {'louder' if d > 0 else 'quieter'} than")
        col = C["grn"] if abs(d) < 1.5 else C["yel"]
        say(f"  {col}{word}{C['r']} last session")
        if abs(d) >= 1.5:
            say(f"  {C['dim']}Worth finding out why before you record - "
                f"that difference is audible across a video.{C['r']}")
    if floor > -45:
        say(f"  {C['yel']}This room is noisy. Check fridge, fans, "
            f"windows.{C['r']}")
    elif floor < -58:
        say(f"  {C['grn']}Good and quiet.{C['r']}")
    say(f"\n  saved {TONE_PATH}")
    say(f"  gate set to {db(measured_gate()):.1f} dBFS\n")
    return 0


# ----------------------------------------------------------------- prune

def prunable() -> tuple:
    """(deletable, kept) user clips, judged against the starter bank.

    A user clip is deletable only if the starter bank has a counterpart that
    actually OPENS and contains samples. Size is not enough: a 44-byte WAV is
    a header with no audio, and deleting a good recording because a broken
    file exists next to it is the exact shape of the mistake this repo has
    already made once - see gen/paths.py on the 42 lost phonemes.

    Only the three content folders are considered. passage*, room-tone and
    anything else in the bank is never a candidate, because nothing in the
    starter set can replace it.
    """
    deletable, kept = [], []
    for sub in BANK_DIRS:
        d = VOICE_DIR / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.wav")):
            if f.name.endswith(".previous.wav"):
                continue
            s = STARTER_VOICE / sub / f.name
            ok = False
            if s.exists():
                try:
                    a, _ = sf.read(s, dtype="float32", always_2d=False)
                    ok = a.size > 0 and float(np.abs(a).max()) > 0.0
                except Exception:
                    ok = False
            (deletable if ok else kept).append(f)
    return deletable, kept


def do_prune(term: Term, confirm: bool) -> int:
    deletable, kept = prunable()
    say(f"\n  {C['b']}Prune{C['r']} - drop user clips the starter bank can "
        f"already speak.\n")
    say(f"  {VOICE_DIR}")
    say(f"    {C['red']}delete{C['r']}  {len(deletable):>4}  "
        f"{C['dim']}verified playable in starter{C['r']}")
    say(f"    {C['grn']}keep{C['r']}    {len(kept):>4}  "
        f"{C['dim']}no usable starter counterpart{C['r']}")
    extra = [p for p in VOICE_DIR.iterdir()
             if p.name not in BANK_DIRS]
    say(f"    {C['grn']}keep{C['r']}    {len(extra):>4}  "
        f"{C['dim']}never a candidate: "
        f"{', '.join(sorted(p.name for p in extra)[:4])}{C['r']}")

    if not deletable:
        say("\n  nothing to do\n")
        return 0
    if not confirm:
        say(f"\n  {C['dim']}Dry run. Nothing was deleted.{C['r']}")
        say(f"  {C['dim']}Re-run with --yes to delete the "
            f"{len(deletable)}.{C['r']}\n")
        return 0

    say(f"\n  {C['yel']}Delete {len(deletable)} recordings?{C['r']}  "
        f"{C['dim']}[y] yes   anything else cancels{C['r']}")
    if term.key() != "y":
        say("  canceled\n")
        return 1
    n = 0
    for f in deletable:
        try:
            f.unlink()
            n += 1
        except OSError as e:
            say(f"  {C['red']}{f.name}: {e}{C['r']}")
    say(f"\n  deleted {n}; {len(kept)} user clips remain, and the app now "
        f"falls through to starter for the rest\n")
    return 0


# ------------------------------------------------------------ the session

def show(item, i, n, part):
    say()
    rule()
    # Padding is computed on the visible text, not the formatted string -
    # str.rjust counts ANSI escapes as characters and throws the column out.
    counter = f"{i + 1} / {n}"
    pad = max(1, 64 - 2 - len(part) - len(counter))
    say(f"  {C['dim']}{part}{' ' * pad}{counter}{C['r']}")
    rule()
    say()
    say(f"      {C['b']}{C['cyn']}{item.display}{C['r']}")
    say()
    for line in _wrap(item.say, 62):
        say(f"      {line}")
    lo, hi, ideal = studio.LENGTH_TARGET[item.length]
    say(f"\n      {C['dim']}{item.length} - aim for about "
        f"{ideal:g}s{C['r']}")
    say()


def _wrap(text, width):
    out, line = [], ""
    for w in text.split():
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


def run_part(term: Term, part: str, device: str, redo: bool,
             start: int, limit: int = 0, seen: set | None = None,
             path: Path | None = None, target: str = "user",
             only: str = "") -> int:
    roots = roots_for(target)
    items = plan_for(part, path)
    if only:
        want = {w.strip().lower() for w in only.split(",") if w.strip()}
        # An exact key wins. Two sounds share the display "th" - the one in
        # "thin" and the one in "this" - and their keys are th and th-this,
        # so naming a key must mean that sound and not both of them.
        exact = [it for it in items if it.key.lower() in want]
        loose = [it for it in items
                 if it.display.lower() in want or (it.ipa or "").lower() in want]
        named = {it.key.lower() for it in exact}
        items = exact + [it for it in loose if it.key.lower() not in named
                         and it.display.lower() not in named]
        if not items:
            say(f"  nothing in {part!r} matches {sorted(want)}")
            return 0
        redo = True                 # naming an item is asking to redo it
    if not redo:
        # "Already recorded" means present in the PRIMARY bank. With --to both
        # that is the user's, so a clip missing only from starter is still
        # re-recorded rather than silently skipped - the two are kept in step
        # by writing both, not by probing both.
        pending = [it for it in items if not done_in(roots[0], it)]
        if not pending:
            say(f"\n  {part}: all {len(items)} already recorded "
                f"{C['dim']}(--redo to do them again){C['r']}")
            return 0
        items = pending
    # Two parts can name the same destination file (see ALL_ORDER). Recording
    # it twice in one run wastes a take and the later one silently wins, so a
    # path handled earlier in this session is skipped however it got here.
    if seen is not None:
        items = [it for it in items if it.path() not in seen]
    items = items[start:]
    if limit:
        items = items[:limit]
    gate = measured_gate()
    if not TONE_PATH.exists():
        say(f"\n  {C['yel']}No room tone recorded - auto-stop is using a "
            f"default threshold.{C['r']}")
        say(f"  {C['dim']}`python -m gen.record tone` first is worth the "
            f"30 seconds.{C['r']}")

    n, i, kept = len(items), 0, 0
    while i < n:
        item = items[i]
        show(item, i, n, part)
        say(f"  {C['dim']}[enter] record   [s] skip   [b] back   [q] quit{C['r']}")
        k = term.key()
        if k == "q":
            break
        if k == "s":
            i += 1
            continue
        if k == "b":
            i = max(0, i - 1)
            continue

        audio = capture(term, device, gate)
        if audio is None:
            break
        if audio.size == 0:
            say(f"  {C['red']}nothing captured{C['r']}")
            continue

        # One take, scored by the same code that scores three. choose() already
        # words its verdict differently for a single take ("Got it" rather than
        # "Best of the takes"), so nothing here needs special-casing.
        result = studio.choose([audio], item)

        if result["allFailed"]:
            bad = next((t for t in result["takes"] if t["fatal"]), None)
            say(f"  {C['red']}✗ {bad['fatal'] if bad else 'unusable'}{C['r']}")
            say(f"  {C['dim']}[enter] try again   [s] skip   [q] quit{C['r']}")
            k = term.key()
            if k == "q":
                break
            if k == "s":
                i += 1
            continue

        save_all(roots, item, result["audio"])
        if seen is not None:
            seen.add(item.path())
        kept += 1
        best = next(t for t in result["takes"] if t["index"] == result["best"])
        mark = C["yel"] + "~" if result["weak"] else C["grn"] + "✓"
        say(f"  {mark} {result['reason']}{C['r']}   {C['dim']}"
            f"{best['seconds']:.2f}s   peak {db(best['peak']):.1f} dBFS{C['r']}")
        for a in result["advice"]:
            say(f"    {C['yel']}{a}{C['r']}")

        if result["weak"]:
            say(f"  {C['dim']}[enter] keep and move on   [r] redo   "
                f"[q] quit{C['r']}")
            k = term.key()
            if k == "q":
                break
            if k == "r":
                continue
        i += 1

    full = plan_for(part, path)
    for r in roots:
        say(f"\n  {part} -> {r.name}: kept {kept}, "
            f"{sum(1 for it in full if done_in(r, it))} of {len(full)} "
            f"recorded overall")
    say()
    return 0


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("part", nargs="?", default=None,
                    help="tone | prune | " + " | ".join(PARTS))
    ap.add_argument("--yes", action="store_true",
                    help="prune: actually delete (still asks once)")
    ap.add_argument("--all", action="store_true",
                    help="every part, in teaching order")
    ap.add_argument("--redo", action="store_true",
                    help="include items already recorded")
    ap.add_argument("--from", dest="start", type=int, default=0,
                    help="skip the first N items")
    # Chunks are 398 items and studio.plan() returns them most-useful-first,
    # because each one only REPLACES an automatic blend of sounds already
    # recorded - the bank works without any of them. So the sane way to
    # record pairs is the top of the list, an evening at a time, rather
    # than treating 398 as a target.
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N items (0 = no limit)")
    # Replacing one sound is the common repair - a single bad take, found
    # weeks later in a finished video. Without this the only way to reach it
    # was --redo on the whole part, which re-records 42 sounds to fix one.
    ap.add_argument("--only", default="",
                    help="comma-separated items to record, by key or by what "
                         "is shown (e.g. --only aw,s,th). Implies --redo.")
    ap.add_argument("--device", default="default", help="PulseAudio source")
    ap.add_argument("--to", dest="target", default="user",
                    choices=("user", "starter", "both"),
                    help="which bank to write: user (default), starter "
                         "(ships in the release), or both")
    ap.add_argument("--file", default=None,
                    help="sentence list (default wordlists/sentences.txt); "
                         "words are derived from it")
    args = ap.parse_args(argv)

    if not args.part and not args.all:
        ap.print_help()
        return 2

    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    with Term() as term:
        if args.part == "tone":
            return do_tone(term, args.device)
        if args.part == "prune":
            return do_prune(term, args.yes)
        parts = ALL_ORDER if args.all else (args.part,)
        seen: set = set()
        path = Path(args.file) if args.file else None
        if path and not path.exists():
            say(f"no such file: {path}")
            return 2
        for r in roots_for(args.target):
            say(f"  writing to {C['b']}{r}{C['r']}")
        if args.target in ("starter", "both"):
            # Everyone who installs the app gets these. A bad take here is a
            # bad take on every machine, so it is worth one keystroke.
            say(f"  {C['yel']}The starter bank SHIPS - every install gets "
                f"these recordings.{C['r']}")
            say(f"  {C['dim']}They are tracked in git and replace what is "
                f"there.{C['r']}")
            say(f"\n  Write to the shipped bank?  {C['dim']}[y] yes   "
                f"anything else cancels{C['r']}")
            if term.key() != "y":
                say("  cancelled\n")
                return 1
        say()
        for w in missing_sight_words(path):
            say(f"  {C['yel']}sight word {w!r} is in no sentence - "
                f"nothing will record it{C['r']}")
        for p in parts:
            if p not in PARTS:
                say(f"unknown part {p!r}; expected tone or one of "
                    f"{', '.join(PARTS)}")
                return 2
            if run_part(term, p, args.device, args.redo, args.start,
                        args.limit, seen, path, args.target, args.only):
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
