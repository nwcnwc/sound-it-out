"""Read the editable word lists.

One file is the single source of truth for both the recording checklist and
what appears on screen, so a word only ever has to be written down once.

Run directly to print the recording checklist:
    .venv/bin/python -m gen.wordlists
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDLISTS = ROOT / "wordlists"

# "Chase  #4da6ff"  ->  ("Chase", "#4da6ff")
LINE = re.compile(r"^(?P<word>[^#\[\]]+?)(?:\s+(?P<color>#[0-9a-fA-F]{3,8}))?\s*$")


@dataclass
class Group:
    name: str
    words: list = field(default_factory=list)  # (word, color|None)

    def __len__(self):
        return len(self.words)


def load(path=None) -> list:
    """Parse a word list into groups, tolerating anything a human might type."""
    path = Path(path) if path else WORDLISTS / "sight-words.txt"
    groups, current = [], None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = Group(line[1:-1].strip())
            groups.append(current)
            continue
        m = LINE.match(line)
        if not m:
            continue
        word = m.group("word").strip()
        if not word:
            continue
        if current is None:  # words before any [group] heading
            current = Group("Words")
            groups.append(current)
        current.words.append((word, m.group("color")))
    return [g for g in groups if g.words]


def all_words(groups=None) -> list:
    """Every word, de-duplicated, preserving order."""
    seen, out = set(), []
    for g in groups if groups is not None else load():
        for w, _ in g.words:
            k = w.lower()
            if k not in seen:
                seen.add(k)
                out.append(w)
    return out


def colors(groups=None) -> dict:
    return {
        w: c
        for g in (groups if groups is not None else load())
        for w, c in g.words
        if c
    }


def main():
    groups = load()
    words = all_words(groups)
    print("RECORDING CHECKLIST - sight words")
    print("=" * 42)
    print(f"{len(words)} words, roughly {len(words) * 12 // 60} minutes\n")
    print("Say each one normally, the way you'd say it in a sentence.")
    print("Leave a 2 second gap between words.\n")
    n = 0
    for g in groups:
        print(f"  [{g.name}]")
        for w, _ in g.words:
            n += 1
            print(f"    {n:3}. {w}")
        print()
    placeholders = [w for w in words if w.lower() in {"alex", "mum", "dad", "nana", "grandad"}]
    if placeholders:
        print("Note: the [People] group still has the example names in it.")
        print("      Edit wordlists/sight-words.txt to use your real ones.")


if __name__ == "__main__":
    main()
