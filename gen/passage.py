"""The reading passage, recorded a section at a time.

The passage is the voice-cloning reference, and it used to be one unbroken
take of about five minutes. That is a reasonable thing to ask of a recording
studio and an unreasonable thing to ask of a parent with a child in the house:
five minutes of undisturbed quiet is exactly what she does not have. In
practice the session got interrupted, and what landed on disk was thirty-three
seconds of a five-minute script - a real, audible file that was simply not the
passage.

## Why sections are safe, and sentences would not be

Splitting a cloning reference has a real cost. What the clone learns from is
connected prosody - the rhythm and melody across a phrase, where the breath
falls, how a question rises. Chop that into words and you get a voice that can
say anything and sounds like nobody.

Sections are above that line. Each one is 20-70 seconds of continuous reading,
which is well over the few seconds of connected speech a reference needs, and
the joins land where the writer already put a break. PASSAGE.md has told her
"Take a break at any of the section breaks" since it was written; this only
makes the software agree with the document.

Sentence-level or paragraph-level splitting would not be safe, and is
deliberately not offered.

## How progress is kept

Each section is a file in `passage/`, and `passage.wav` is rebuilt from
whatever exists whenever one is saved. As with the rest of the studio, the
files on disk ARE the progress record: there is no index to fall out of step,
and re-recording section three means overwriting one file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from gen.paths import RESOURCES, VOICE_DIR
from gen.soundout import SR

# Read aloud unhurried. Only used to tell a finished section from an abandoned
# one, so roughly right is right enough.
WORDS_PER_MINUTE = 150.0

# Between sections in the assembled file. A join with no gap sounds clipped;
# too long a gap reads as a mistake in the recording.
JOIN_SILENCE = 0.5


def chunk_dir() -> Path:
    return VOICE_DIR / "passage"


def chunk_path(index: int) -> Path:
    return chunk_dir() / f"{index:02d}.wav"


def whole_path() -> Path:
    return VOICE_DIR / "passage.wav"


@dataclass
class Section:
    index: int
    title: str
    text: str
    words: int

    @property
    def expected_seconds(self) -> float:
        return self.words / WORDS_PER_MINUTE * 60.0

    def path(self) -> Path:
        return chunk_path(self.index)

    def done(self) -> bool:
        return self.path().exists()

    def seconds(self) -> float:
        p = self.path()
        if not p.exists():
            return 0.0
        try:
            info = sf.info(p)
            return info.frames / info.samplerate
        except Exception:
            return 0.0

    def as_dict(self):
        secs = self.seconds()
        return {
            "index": self.index,
            "title": self.title,
            "text": self.text,
            "words": self.words,
            "expectedSeconds": round(self.expected_seconds),
            "done": self.done(),
            "seconds": round(secs, 1),
            # Cut short is the failure this whole module exists to prevent, so
            # it is reported per section rather than only for the whole thing.
            "short": bool(secs) and secs < self.expected_seconds * 0.5,
        }


def _source() -> str:
    return (RESOURCES / "PASSAGE.md").read_text(encoding="utf-8")


def sections() -> list:
    """The passage split at its own section headings."""
    raw = _source()
    if "## " not in raw:
        return []
    # Everything before the first heading is instructions to the reader, not
    # something to read aloud.
    body = raw[raw.index("## "):]
    out = []
    for i, block in enumerate(re.split(r"(?m)^## ", body)):
        block = block.strip()
        if not block:
            continue
        title, _, rest = block.partition("\n")
        text = "\n\n".join(p.strip() for p in rest.split("\n\n") if p.strip())
        words = sum(1 for w in text.split() if any(c.isalpha() for c in w))
        if not words:
            continue
        out.append(Section(index=len(out), title=title.strip(),
                           text=text, words=words))
    return out


def plan() -> dict:
    secs = sections()
    dicts = [s.as_dict() for s in secs]
    done = sum(1 for d in dicts if d["done"])
    return {
        "sections": dicts,
        "done": done,
        "total": len(dicts),
        # Where to pick up. A parent doing this over several sittings should
        # not have to work out where she got to.
        "resumeAt": next((n for n, d in enumerate(dicts) if not d["done"]),
                         len(dicts)),
        "expectedSeconds": round(sum(s.expected_seconds for s in secs)),
        "recordedSeconds": round(sum(d["seconds"] for d in dicts), 1),
        "complete": bool(dicts) and done == len(dicts),
    }


def _preserve_legacy_whole() -> None:
    """Keep a passage recorded before sections existed.

    Someone who already read the whole thing in one go has a passage.wav that
    no section produced. The first section saved would rebuild over it, so it
    is copied aside first - losing a recording to a software change would be
    indefensible.
    """
    whole = whole_path()
    if not whole.exists() or chunk_dir().exists():
        return
    keep = VOICE_DIR / "passage.before-sections.wav"
    if not keep.exists():
        try:
            keep.write_bytes(whole.read_bytes())
        except OSError:
            pass  # never block a recording over a failed backup


def save_section(index: int, audio: np.ndarray) -> dict:
    """Write one section and reassemble the whole passage from what exists."""
    secs = sections()
    if not 0 <= index < len(secs):
        raise ValueError(f"There is no section {index} in the passage.")

    _preserve_legacy_whole()
    chunk_dir().mkdir(parents=True, exist_ok=True)
    sf.write(chunk_path(index), audio.astype("float32"), SR)
    return rebuild()


def rebuild() -> dict:
    """Concatenate every recorded section, in order, into passage.wav."""
    secs = sections()
    have = [s for s in secs if s.done()]
    if not have:
        return {"path": None, "seconds": 0.0, "sections": 0,
                "total": len(secs), "complete": False}

    gap = np.zeros(int(SR * JOIN_SILENCE), dtype="float32")
    pieces = []
    for n, s in enumerate(have):
        a, sr = sf.read(s.path(), dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        if sr != SR:
            from gen.recordings import resample
            a = resample(a, sr, SR)
        if n:
            pieces.append(gap)
        pieces.append(a)

    joined = np.concatenate(pieces).astype("float32")
    whole = whole_path()
    whole.parent.mkdir(parents=True, exist_ok=True)
    sf.write(whole, joined, SR)
    return {
        "path": str(whole),
        "seconds": round(len(joined) / SR, 1),
        "sections": len(have),
        "total": len(secs),
        "complete": len(have) == len(secs),
    }


def remove_section(index: int) -> bool:
    """Drop one section so it can be read again."""
    p = chunk_path(index)
    if not p.exists():
        return False
    p.unlink()
    rebuild()
    return True
