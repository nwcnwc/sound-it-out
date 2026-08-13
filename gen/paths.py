"""Where things live, in development and once frozen.

PyInstaller unpacks a onefile build into a temporary directory, so the usual
`Path(__file__).parent.parent` points at a folder that is empty and about to be
deleted. Worse, it fails silently: models "aren't there", the word list comes
back empty, and nothing raises until generation produces nothing.

There are two kinds of path and they must not be confused:

    RESOURCES  read-only, ships with the app (models, default word lists)
    DATA       writable, per-user (their edited word lists, recordings, jobs)

They are the same directory in development and different once installed. On
macOS especially, the app bundle is read-only - anything writable must go to
Application Support or the first save fails on their machine and not on ours.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def _user_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Sound It Out"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "Sound It Out"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "sound-it-out"


if FROZEN:
    # electron-builder lays the sidecar out as resources/sidecar/<exe>, so the
    # shipped resources directory is two levels up from the executable.
    RESOURCES = Path(sys.executable).resolve().parent.parent
    DATA = _user_data_dir()
else:
    RESOURCES = Path(__file__).resolve().parent.parent
    DATA = RESOURCES

MODELS = RESOURCES / "models"
FONTS = RESOURCES / "app" / "fonts"

# The subdirectories of a voice bank, named for what they hold. Constants
# rather than string literals at twenty call sites, because that is how the
# old name drifted away from the truth without anyone noticing.
#
# SOUNDS holds everything keyed by an IPA label: the 42 phonemes, the magic-e
# recordings, and any grapheme pair somebody has recorded as one breath. It
# was called "phonemes" when phonemes were all it held, and stayed that way
# after it stopped being true - so a directory of 126 files was named for the
# 42 of them that fit the label.
SOUNDS = "sounds"
WORDS = "words"
SENTENCES = "sentences"
BANK_DIRS = (SOUNDS, WORDS, SENTENCES)

_LEGACY_SOUNDS = "phonemes"


def migrate_voice_layout(root) -> int:
    """Move an old `phonemes/` bank to `sounds/`. Returns files moved.

    Shipping the rename without this would make every existing user's
    recordings invisible at the next update - the app would look in sounds/,
    find nothing, and report a bank they spent forty minutes filling as
    empty. Their recordings are irreplaceable and this repo has already lost
    42 clips once (see VOICE_DIR below), so nothing here deletes: a name
    collision moves what it safely can and leaves the rest where it is.
    """
    root = Path(root)
    old, new = root / _LEGACY_SOUNDS, root / SOUNDS
    if not old.is_dir():
        return 0
    if not new.exists():
        n = len(list(old.glob("*.wav")))
        old.rename(new)          # atomic within one filesystem
        return n
    moved = 0
    for f in old.iterdir():
        if not f.is_file():
            continue
        dst = new / f.name
        if not dst.exists():     # never overwrite a newer recording
            f.rename(dst)
            moved += 1
    try:
        old.rmdir()              # only ever succeeds when it is empty
    except OSError:
        pass
    return moved

BUILD = DATA / "build"
JOBS = BUILD / "jobs"
AUDIO_CACHE = BUILD / "audio"
# Overridable so tests and experiments NEVER write into, or clear, the real
# recordings. This exists because they were once deleted by a cleanup step
# that assumed the directory held only test data - 42 recorded phonemes,
# unrecoverable, because the folder is gitignored and rm does not use Trash.
VOICE_DIR = Path(os.environ.get("SIO_VOICE_DIR") or (DATA / "assets" / "voice"))
# The starter voice: recorded phoneme clips that ship with the app, spoken by
# the developer. Used for any sound the family has not recorded themselves
# yet, so a fresh install teaches with a human voice rather than a synthesised
# one. Read-only and shipped, unlike VOICE_DIR - a family's own recordings
# always win, at which point these are simply never read.
STARTER_VOICE = RESOURCES / "assets" / "starter-voice"
WORDLISTS = DATA / "wordlists"


def _shipped_wordlists():
    """Where the default word lists can be found, most specific first.

    A frozen onefile build unpacks its own data to sys._MEIPASS, which is the
    only location guaranteed to exist however the executable is laid out. The
    resources directory is right in a real install but absent when the sidecar
    is run on its own - as CI does - and the failure mode was an unhandled
    FileNotFoundError rather than anything a user could act on.
    """
    here = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        here.append(Path(meipass) / "wordlists")
    here.append(RESOURCES / "wordlists")
    return [d for d in here if d.exists()]


def ensure_user_files():
    """Seed the writable area from shipped defaults on first run.

    Copy rather than symlink: they edit these, and an upgrade must not silently
    revert the user's own names back to the placeholders.
    """
    # Before anything else looks at the bank: an install upgrading from the
    # old layout must find its recordings where the new code expects them.
    migrate_voice_layout(VOICE_DIR)
    for d in (BUILD, JOBS, AUDIO_CACHE, VOICE_DIR, WORDLISTS):
        d.mkdir(parents=True, exist_ok=True)
    for shipped in _shipped_wordlists():
        if shipped == WORDLISTS:
            continue
        for src in shipped.glob("*.txt"):
            # "sight-words.default.txt" ships; "sight-words.txt" is what the
            # family edits. They are two files on purpose: when the app runs
            # from source the writable path is inside the repo, and the live
            # list - which holds a child's name, their parents, their pets -
            # was once committed to a public repo by a `git add -A` that could
            # not know what it was publishing. Only the placeholder version is
            # tracked now, and this is where the real one gets created.
            name = src.name.replace(".default.txt", ".txt")
            dst = WORDLISTS / name
            if not dst.exists():
                shutil.copy2(src, dst)


def describe() -> dict:
    return {
        "frozen": FROZEN,
        "resources": str(RESOURCES),
        "data": str(DATA),
        "starter_present": (STARTER_VOICE / SOUNDS).exists(),
    }
