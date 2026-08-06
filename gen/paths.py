"""Where things live, in development and once frozen.

PyInstaller unpacks a onefile build into a temporary directory, so the usual
`Path(__file__).parent.parent` points at a folder that is empty and about to be
deleted. Worse, it fails silently: models "aren't there", the word list comes
back empty, and nothing raises until generation produces nothing.

There are two kinds of path and they must not be confused:

    RESOURCES  read-only, ships with the app (models, default word lists)
    DATA       writable, per-user (her edited word lists, recordings, jobs)

They are the same directory in development and different once installed. On
macOS especially, the app bundle is read-only - anything writable must go to
Application Support or the first save fails on her machine and not on ours.
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

BUILD = DATA / "build"
JOBS = BUILD / "jobs"
AUDIO_CACHE = BUILD / "audio"
VOICE_DIR = DATA / "assets" / "voice"
WORDLISTS = DATA / "wordlists"


def ensure_user_files():
    """Seed the writable area from shipped defaults on first run.

    Copy rather than symlink: she edits these, and an upgrade must not silently
    revert her family's names back to the placeholders.
    """
    for d in (BUILD, JOBS, AUDIO_CACHE, VOICE_DIR, WORDLISTS):
        d.mkdir(parents=True, exist_ok=True)
    shipped = RESOURCES / "wordlists"
    if shipped.exists() and shipped != WORDLISTS:
        for src in shipped.glob("*.txt"):
            dst = WORDLISTS / src.name
            if not dst.exists():
                shutil.copy2(src, dst)


def describe() -> dict:
    return {
        "frozen": FROZEN,
        "resources": str(RESOURCES),
        "data": str(DATA),
        "models_present": (MODELS / "kokoro-v1.0.onnx").exists(),
    }
