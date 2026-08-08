# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Python sidecar.

Freezes gen/service.py - the JSON-lines-over-stdio process the Electron app
spawns - into one self-contained executable, so the end user never installs
Python, pip, or espeak-ng. That is the whole point: this app is for a family's
living room, not a developer's machine.

Build:
    pyinstaller --noconfirm --clean \
        --distpath dist/sidecar --workpath build/pyi build/sidecar.spec

Output: dist/sidecar/soundout-sidecar[.exe]

PyInstaller freezes for the machine it runs on and cannot cross-compile - a
macOS binary needs a Mac, an arm64 binary needs an arm64 Mac. See BUILDING.md.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

# SPECPATH is injected by PyInstaller and is this file's directory (build/).
ROOT = Path(SPECPATH).parent

binaries = []
datas = []
hiddenimports = []

# ---------------------------------------------------------------- espeak-ng
#
# THE ONE MOST LIKELY TO BREAK SILENTLY. Read this before changing it.
#
# phonemizer needs a native espeak-ng library plus its language dictionaries.
# There is no system package involved: espeak-ng ships *inside* the pure-Python
# `espeakng_loader` wheel, and kokoro_onnx/tokenizer.py points phonemizer at it
# with espeakng_loader.get_library_path() / .get_data_path().
#
# PyInstaller's dependency scanner never sees any of it. It follows imports and
# linker records; this library is opened at runtime by ctypes.CDLL on a path
# built from a string, and the dictionaries are plain data files. Without the
# two entries below the frozen sidecar imports cleanly, starts cleanly, and
# then fails on the first word it is asked to speak - which is exactly the kind
# of failure that survives all the way to a user's machine.
#
# The destination directories matter as much as the files. Both loader
# functions resolve `Path(__file__).parent / ...`, and PyInstaller sets
# __file__ for a frozen module to <bundle>/espeakng_loader/__init__.py. Put the
# library and the data under `espeakng_loader/` and the stock loader code works
# untouched. Put them anywhere else and it raises "data path not exists".
import espeakng_loader  # noqa: E402  (needed to locate the wheel's payload)

binaries += [(espeakng_loader.get_library_path(), "espeakng_loader")]
datas += [(espeakng_loader.get_data_path(), "espeakng_loader/espeak-ng-data")]

# ~19MB of dictionaries for ~100 languages when we use exactly one (en-gb).
# Left whole on purpose: pruning to en_dict alone saves ~18MB on a ~500MB
# installer while risking a hard crash the day anything asks for anotthe recorded voice.
# Not a trade worth making. If installer size ever does become the binding
# constraint, prune here, not by dropping the directory.

# --------------------------------------------------------------- onnxruntime
#
# The Kokoro TTS engine. `import onnxruntime` pulls in a compiled extension
# that dlopen()s libonnxruntime and the provider shared libraries beside it -
# again invisible to static analysis. pyinstaller-hooks-contrib ships
# hook-onnxruntime.py which does collect_dynamic_libs("onnxruntime") for us, so
# there is deliberately nothing here. Listed only so its absence reads as a
# decision rather than an oversight.

# ----------------------------------------------------------------- soundfile
#
# Same story: soundfile is a ctypes wrapper around libsndfile, which lives in
# _soundfile_data/ next to the module on Windows/macOS wheels and comes from
# the system on Linux. hook-soundfile.py in pyinstaller-hooks-contrib handles
# both cases. If a build ever warns "sndfile shared library not found", that
# hook found nothing and audio writing will fail at runtime - treat it as an
# error, not a warning.

# ------------------------------------------------------------------ metadata
#
# `import phonemizer` executes importlib.metadata.version("phonemizer-fork") at
# module scope, and kokoro_onnx logs importlib.metadata.version("kokoro-onnx")
# when a Kokoro object is constructed. Frozen bundles carry no .dist-info
# unless asked, so both raise PackageNotFoundError - phonemizer at import time,
# which means the sidecar dies before it prints anything useful.
#
# Note the *distribution* names: "phonemizer-fork", not "phonemizer".
datas += copy_metadata("phonemizer-fork")
datas += copy_metadata("kokoro-onnx")

# phonemizer/share/ holds the festival scheme file and the segments g2p tables.
# Not used by the espeak backend we run, but phonemizer/backend/__init__.py
# imports every backend, so they must be present for the import to succeed.
datas += collect_data_files("phonemizer")

# language_tags keeps the IANA subtag registry as JSON beside its code and
# reads it at import time. It is four levels down a chain nobody would guess
# at - phonemizer imports every backend, one of which is segments, which pulls
# in csvw, which imports language_tags - so nothing in our code mentions it and
# PyInstaller, which follows imports and not data, shipped the modules without
# the JSON.
#
# The result was total: the frozen sidecar could not import kokoro_onnx at all,
# so a build that packaged and installed perfectly could not speak a single
# word. It reached a release before it was caught, because the smoke test that
# found it was advisory. It is not advisory any more.
datas += collect_data_files("language_tags")

# The default word lists. Carried inside the frozen payload so the sidecar can
# seed a user's editable copy however the executable is laid out - the resources
# directory is right in a real install but absent when the sidecar runs on its
# own, and the failure mode was an unhandled FileNotFoundError on first plan.
datas += [(str(ROOT / "wordlists" / "sight-words.default.txt"), "wordlists")]

# kokoro_onnx reads its vocab/config from config.json via Path(__file__).parent.
datas += collect_data_files("kokoro_onnx", includes=["*.json"])

# ------------------------------------------------------------- our own code
#
# service.py imports the pipeline lazily, inside each method body, so that a
# `ping` does not pay for loading onnxruntime. PyInstaller does scan function
# bodies and would normally find these, but naming them makes the dependency
# explicit and survives someone moving an import behind a try/except.
#
# gen.clone is deliberately absent: service.py treats its absence as normal
# ("optional module; absence is normal, not an error") and it does not exist
# yet. Listing a module that is not there is a build warning, not an error, but
# it would be a lie about what ships.
hiddenimports += [
    "gen.soundout",
    "gen.wordlists",
    "gen.voice",
    "gen.levels",
]

# phonemizer picks its backend by name at runtime, so the espeak backend module
# is only ever reached through a string lookup.
hiddenimports += [
    "phonemizer.backend.espeak.espeak",
    "phonemizer.backend.espeak.wrapper",
]

# ------------------------------------------------------------------ excludes
#
# Nothing in the pipeline draws, plots, or opens a GUI - that is Electron's
# job. These get pulled in transitively and cost tens of MB each.
#
# Kept short on purpose. `unittest` and `pydoc` look like obvious wins but are
# reached from numpy's and rdflib's import paths on some versions, and an
# over-eager exclude list produces an ImportError that only shows up on one
# platform's build.
excludes = [
    "tkinter",
    "matplotlib",
    "PIL",
    "IPython",
    "pytest",
]


a = Analysis(
    [str(ROOT / "gen" / "service.py")],
    # gen/ is imported as a package, so the repo root must be importable.
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# The 311MB kokoro-v1.0.onnx and 27MB voices-v1.0.bin are NOT frozen in. They
# ship as electron-builder extraResources, so the sidecar must be handed their
# paths by the app rather than looking beside itself. Reasons: a onefile
# executable unpacks itself to a temp directory on every launch, and unpacking
# 340MB of weights each time the app starts is unusable; and models are the one
# part we may want to swap without rebuilding the binary.
#
# Cheap guard, because this would otherwise be caught only by noticing the
# installer had doubled in size.
_forbidden = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
for _dest, _src, _kind in a.datas + a.binaries:
    if any(_f in _dest for _f in _forbidden):
        raise SystemExit(
            f"sidecar.spec: model file {_dest!r} was pulled into the bundle. "
            "Models ship as extraResources - see electron-builder.yml."
        )

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="soundout-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed binaries trip antivirus heuristics on Windows.
    runtime_tmpdir=None,
    # True because this process IS a stdio protocol - Electron writes JSON
    # lines to its stdin and reads them from its stdout. PyInstaller's windowed
    # mode on Windows points stdout at NUL, which would silently break every
    # reply. The cost is that Windows shows a console window unless the app
    # spawns it with `windowsHide: true`; that flag is required, see BUILDING.md.
    console=True,
    disable_windowed_traceback=False,
    # Native arch only. PyInstaller cannot cross-compile, so a universal2 or
    # x86_64 macOS build has to come from a machine of that architecture - the
    # CI matrix runs a separate macOS runner per arch for exactly this reason.
    target_arch=None,
    # Deliberately unsigned. See the note in electron-builder.yml before
    # "fixing" this - it is a cost decision, not an omission.
    codesign_identity=None,
    entitlements_file=None,
)
