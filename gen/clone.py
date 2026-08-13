"""Sound It Out - optional voice cloning for levels 6-8.

Levels 1-5 are their own recordings played back verbatim, and that is where the child
will be for a year or more. Cloning only fills the long tail - the 10k
dictionary and arbitrary sentences - which could never be recorded by hand. So
this module is optional *by construction*, not by convention:

  * nothing heavy is imported at module scope, so `import clone` costs nothing
    and cannot fail because torch is absent;
  * `is_available()` / `capabilities()` let the UI grey out levels 6-8 with an
    honest reason instead of exploding at generation time;
  * the model runs in a *separate interpreter* (`.venv-clone`), because
    chatterbox-tts pins `numpy<2` and installing it beside the app would
    downgrade numpy under kokoro-onnx and soundfile. The app's own environment
    never gains a single ML dependency.

Model: Chatterbox (Resemble AI), `chatterbox-tts` on PyPI. MIT for the code
*and* for the weights on Hugging Face - the usual trap is MIT code with
non-commercial weights, which is exactly what rules out the more popular
XTTS-v2. See docs/CLONING.md for quality, consent and timing.

Run `python -m gen.clone` for a status report.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gen.soundout import SR, slower  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = ROOT / "models" / "chatterbox"   # downloaded on demand, never shipped
# Both models may be installed at once - one for quality, one for when there is
# no time to wait - and their checkpoints share filenames (ve.safetensors,
# conds.pt) with different contents. They must not share a directory.
WEIGHTS_DIRS = {"english": WEIGHTS, "turbo": ROOT / "models" / "chatterbox-turbo"}
PROFILES = ROOT / "models" / "voices"      # their speaker profiles - hers, not ours
CACHE = ROOT / "build" / "audio-clone"
VENV = ROOT / ".venv-clone"

PACKAGE = "chatterbox-tts"
HF = "https://huggingface.co/{repo}/resolve/main/{name}"

# Chatterbox conditions on the *first* slice of whatever it is handed and drops
# the rest: 10s for the vocoder, 6s (english) or 15s (nano) for the token
# prompt. So a 6 minute passage is not 6 minutes of training data - it is a
# 6 minute pool to choose 20 clean seconds from.
REF_WINDOW = 20.0
MIN_REF = 8.0  # the model itself asserts >5s; below ~8s the prosody is thin

# Rough allowance for the Python side of the install (torch CPU wheel plus
# transformers, diffusers, librosa, gradio and friends). Measured value is in
# docs/CLONING.md; this only has to be good enough to refuse honestly.
STACK_BYTES = 2_600_000_000


class CloneError(RuntimeError):
    """Anything the UI should show the user verbatim."""


# --------------------------------------------------------------- variants


@dataclass(frozen=True)
class Variant:
    name: str
    repo: str
    files: tuple[str, ...]
    nbytes: int   # exact sum of the Hugging Face blob sizes, measured 2026-08
    rtf: float    # seconds of CPU per second of audio, order of magnitude
    note: str


VARIANTS = {
    # The 0.5B English model. This is the one the released package can load.
    "english": Variant(
        "english", "ResembleAI/chatterbox",
        ("ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors",
         "tokenizer.json", "conds.pt"),
        3_191_966_992, 128.0,
        "0.5B English. Best quality, and very slow on a CPU-only laptop.",
    ),
    # The fast one. Same family, distilled: fewer, larger steps to produce the
    # same audio, so it is far quicker on a CPU at some cost in expression.
    #
    # It is TURBO and not NANO, and the distinction cost a download to learn.
    # Resemble publish both, and nano is the smaller and faster of the two -
    # but chatterbox-tts 0.1.7 ships exactly one extra loader, tts_turbo, and
    # that loader reads t3_turbo_v1.safetensors. Nothing in the released
    # package can load nano's t3_nano_v1.safetensors at all. Pointing this
    # entry at the nano repo produced a 1.9 GB download and a FileNotFoundError
    # deep inside the loader.
    #
    # If a later release adds a nano loader, this is where it goes - as another
    # entry, not by editing this one, because the checkpoints are not
    # interchangeable.
    "turbo": Variant(
        "turbo", "ResembleAI/chatterbox-turbo",
        ("ve.safetensors", "t3_turbo_v1.safetensors", "s3gen_meanflow.safetensors",
         "conds.pt", "vocab.json", "merges.txt", "tokenizer_config.json",
         "special_tokens_map.json", "added_tokens.json"),
        2_987_600_000, 24.0,   # rtf measured below, not claimed
        "Distilled. Much faster on a laptop, and a little plainer.",
    ),
}
DEFAULT_VARIANT = "english"


# ------------------------------------------------------------ availability


def _python() -> Path | None:
    """The interpreter that has the ML stack, or None."""
    for p in (VENV / "bin" / "python", VENV / "Scripts" / "python.exe"):
        if p.exists():
            return p
    # Someone may have installed chatterbox into the main env deliberately.
    if importlib.util.find_spec("chatterbox") is not None:
        return Path(sys.executable)
    return None


def weights_dir(variant: str) -> Path:
    return WEIGHTS_DIRS.get(variant, WEIGHTS)


def profile_file(profile_dir, variant: str) -> Path:
    """Where a speaker profile for `variant` lives.

    One directory per voice, one file per model. A profile is a set of
    conditioning tensors shaped for the model that produced it - the 0.5B
    file will not load into the turbo model, and loading it would either throw
    or, worse, produce something that is not her voice. English keeps the
    original filename so profiles cloned before this existed still resolve.
    """
    d = Path(profile_dir)
    return d / ("profile.pt" if variant == "english" else f"profile.{variant}.pt")


def _manifest(variant: str = DEFAULT_VARIANT) -> dict:
    try:
        return json.loads((weights_dir(variant) / "manifest.json").read_text())
    except (OSError, ValueError):
        return {}


def _missing(v: Variant) -> list[str]:
    d = weights_dir(v.name)
    return [f for f in v.files if not (d / f).exists()]


def installed_variants() -> list:
    """Every model whose weights are complete, fastest last."""
    return [name for name, v in VARIANTS.items() if not _missing(v)]


_VERSION_CACHE: dict = {}


def _version(interp: Path | None) -> str | None:
    """Version of chatterbox-tts in `interp`, without importing anything.

    Memoised per process: the subprocess spawn costs half a second, and
    capabilities() wants the answer more than once per call. An install
    changing mid-process is not a case worth a slow first paint.
    """
    if interp is None:
        return None
    if interp in _VERSION_CACHE:
        return _VERSION_CACHE[interp]
    if interp == Path(sys.executable):
        try:
            v = importlib.metadata.version(PACKAGE)
        except importlib.metadata.PackageNotFoundError:
            v = None
        _VERSION_CACHE[interp] = v
        return v
    try:
        out = subprocess.run(
            [str(interp), "-c",
             f"import importlib.metadata as m;print(m.version('{PACKAGE}'))"],
            capture_output=True, text=True, timeout=30,
        )
        v = out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        v = None
    _VERSION_CACHE[interp] = v
    return v


def capabilities(variant: str | None = None) -> dict:
    """What the UI needs to describe this honestly.

    Never raises. `reason` is written to be shown to a non-technical user as-is
    - a usable sentence beats a traceback at generation time.

    ## What this is actually for, which is less than it looks

    Cloning used to be presented as unlocking the later levels. Measured
    against a complete recording session, it was generating exactly one thing:
    the whole-sentence read at the end of a level, because gen/voice.py had no
    lookup for a recorded sentence and went straight to synthesis. There are
    ten such sentences and they take about a minute to read.

    With those recordable, a parent who records everything gets levels 1-3 and
    7-9 entirely in her own voice and needs none of this. What is left
    synthesised is nonsense fragments like /sae/ and "pi" - not words, nothing
    anyone could record, and precisely what cloning models are worst at. They
    stay on the built-in voice deliberately.

    So this is genuinely optional, and the UI says so. Its real use is words
    added to the list later and not yet recorded: without it those fall back to
    a stranger's voice, and with it they sound like her.
    """
    # Which model is being asked about. With none named, prefer one that is
    # actually installed over the nominal default, so a user who installed only
    # the fast one is not told nothing is available.
    have = installed_variants()
    name = variant or (DEFAULT_VARIANT if DEFAULT_VARIANT in have
                       else (have[0] if have else DEFAULT_VARIANT))
    try:
        v = VARIANTS[name]
    except KeyError:
        v = VARIANTS[DEFAULT_VARIANT]
    variant = v
    try:
        interp = _python()
        missing = _missing(variant)
        profiles = sorted(p.name for p in PROFILES.glob("*")
                          if profile_file(p, variant.name).exists())
        free = shutil.disk_usage(ROOT).free
        need = variant.nbytes + (0 if interp else STACK_BYTES)

        if interp is None:
            reason = ("Not installed - and you probably do not need it. If you "
                      "record the sounds, words and sentences, every level is "
                      "already your own voice. This is for words you add later "
                      f"and have not recorded yet. One-off "
                      f"{variant.nbytes / 1e9:.1f} GB download.")
        elif missing:
            reason = (f"The voice model is part-downloaded ({len(missing)} of "
                      f"{len(variant.files)} files missing). Run the install again to resume.")
        elif not profiles:
            reason = ("The voice model is installed but no voice has been cloned "
                      "yet. Record the reading passage and clone from it.")
        else:
            reason = "Ready."

        return {
            "available": interp is not None and not missing,
            "reason": reason,
            # Nothing requires it any more; kept so an older UI still reads.
            "levels": [],
            "optional": True,
            "variant": variant.name,
            "installed_variants": have,
            # Everything the UI needs to offer a speed/quality choice without
            # knowing anything about models.
            "variants": [
                {
                    "name": k,
                    "installed": k in have,
                    "bytes": vv.nbytes,
                    "seconds_per_second": vv.rtf,
                    "note": vv.note,
                    "usable": k != "turbo" or (interp is not None and _supports_turbo(interp)),
                }
                for k, vv in VARIANTS.items()
            ],
            "variant_note": variant.note,
            "model": {"package": PACKAGE, "version": _version(interp),
                      "license": "MIT (code and weights)", "repo": variant.repo},
            "interpreter": str(interp) if interp else None,
            "weights_dir": str(WEIGHTS),
            "missing_files": missing,
            "profiles": profiles,
            "download_bytes": variant.nbytes,
            "install_bytes": need,
            "free_bytes": free,
            "enough_space": free > need * 1.1,
            "sample_rate": SR,
            # Measured, not guessed. The previous figure was 15s and the real
            # number on a 4-thread i3-10110U is around 128s - a difference
            # between "slow" and "leave it running overnight", which a parent
            # deserves to know before starting rather than after.
            "speed_note": (f"About {variant.rtf:g} seconds of computing for every "
                           "second of speech, on an ordinary laptop. Each sentence "
                           "is only ever made once - after that it is instant."),
            "seconds_per_second": variant.rtf,
        }
    except Exception as e:  # capabilities() must never be the thing that breaks
        return {"available": False, "reason": f"Voice cloning unavailable: {e}",
                "levels": [], "optional": True, "profiles": []}


def is_available() -> bool:
    """True if a sentence could be generated right now (engine, not voice).

    Deliberately does not require a cloned profile: "installed but no voice yet"
    is a different message from "not installed", and `capabilities()` carries
    both.
    """
    return bool(capabilities().get("available"))


# ---------------------------------------------------------------- install


def _space_check(v: Variant, need_stack: bool) -> None:
    """Refuse *before* a 3 GB download rather than 90% of the way through it."""
    need = v.nbytes + (STACK_BYTES if need_stack else 0)
    wd = weights_dir(v.name)
    have = sum((wd / f).stat().st_size for f in v.files if (wd / f).exists())
    need = int((need - have) * 1.1)  # 10% for pip's temp unpacking
    free = shutil.disk_usage(ROOT).free
    if free < need:
        raise CloneError(
            f"Not enough disk space: the {v.name} voice model needs about "
            f"{need / 1e9:.1f} GB free and there is {free / 1e9:.1f} GB. "
            "Levels 1-5 do not need this and keep working either way."
        )


def _download(url: str, dest: Path, on_bytes) -> None:
    """Resumable GET. A 3 GB download over a home connection will be interrupted."""
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = Request(url, headers={"User-Agent": "sound-it-out"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0  # server ignored the range, or the file changed underneath us
        total = int(r.headers.get("Content-Length") or 0) + have
        with open(part, "ab" if have else "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                on_bytes(len(chunk))
    got = part.stat().st_size
    if total and got != total:
        # Half a safetensors file fails much later and much more confusingly.
        raise CloneError(f"{dest.name} came down short ({got} of {total} bytes) "
                         "- run the install again to resume.")
    part.replace(dest)


def _pip_install(progress) -> Path:
    """Build the sidecar venv.

    Torch goes in first, from the CPU index: the default PyPI wheel is 767 MB
    and drags in ~2.5 GB of CUDA packages that are useless on the target
    laptops. `torch==2.6.0+cpu` satisfies chatterbox's `torch==2.6.0` pin, so
    installing it first stops pip resolving the CUDA build afterwards.
    """
    progress(0.02, "Creating the voice-model environment")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    py = _python()
    if py is None:
        raise CloneError("Could not create the voice-model environment.")
    steps = [
        (["-m", "pip", "install", "-q", "--upgrade", "pip"], "Preparing"),
        (["-m", "pip", "install", "torch==2.6.0", "torchaudio==2.6.0",
          "--index-url", "https://download.pytorch.org/whl/cpu"], "Downloading PyTorch (CPU)"),
        (["-m", "pip", "install", PACKAGE], f"Installing {PACKAGE}"),
        (["-m", "pip", "install", "soundfile"], "Installing audio support"),
    ]
    for i, (args, label) in enumerate(steps):
        progress(0.03 + 0.27 * i / len(steps), label)
        r = subprocess.run([str(py), *args], capture_output=True, text=True)
        if r.returncode:
            raise CloneError(f"{label} failed:\n{(r.stderr or r.stdout)[-2000:]}")
    return py


def install(progress_cb=None, variant: str = DEFAULT_VARIANT) -> dict:
    """Download and cache the cloning model. Resumable; safe to re-run.

    `progress_cb(fraction, message)` is called with 0.0-1.0 and a line fit to
    show a user. Fractions are honest about ordering but not about time: pip is
    the first 30%, the weights the rest, and on a slow connection the weights
    dominate anyway.
    """
    progress = progress_cb or (lambda f, m: None)
    if variant not in VARIANTS:
        raise CloneError(f"Unknown variant {variant!r}; expected one of {list(VARIANTS)}.")
    v = VARIANTS[variant]

    py = _python()
    _space_check(v, need_stack=py is None)   # BEFORE anything is written

    started = time.time()
    if py is None:
        py = _pip_install(progress)
    if variant == "turbo" and not _supports_turbo(py):
        raise CloneError(
            f"The installed {PACKAGE} ({_version(py)}) cannot load the fast model. "
            "The slower, better-sounding one still works."
        )

    wd = weights_dir(v.name)
    wd.mkdir(parents=True, exist_ok=True)
    done = sum((wd / f).stat().st_size for f in v.files if (wd / f).exists())
    done += sum((wd / (f + ".part")).stat().st_size for f in v.files
                if (wd / (f + ".part")).exists())
    state = {"done": done}

    def bump(n):
        state["done"] += n
        progress(0.30 + 0.68 * min(state["done"] / v.nbytes, 1.0),
                 f"Downloading voice model - {state['done'] / 1e9:.2f} of {v.nbytes / 1e9:.2f} GB")

    for name in v.files:
        dest = wd / name
        if dest.exists():
            continue
        progress(0.30 + 0.68 * min(state["done"] / v.nbytes, 1.0), f"Downloading {name}")
        _download(HF.format(repo=v.repo, name=name), dest, bump)

    (wd / "manifest.json").write_text(json.dumps({
        "variant": v.name, "repo": v.repo, "files": list(v.files),
        "bytes": v.nbytes, "package": PACKAGE, "version": _version(py),
        "installed": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, indent=2))
    progress(1.0, "Voice model installed")
    return {"variant": v.name, "seconds": round(time.time() - started, 1),
            "bytes": v.nbytes, "path": str(wd)}


def uninstall(keep_profiles: bool = True) -> dict:
    """Remove the model and its environment.

    Their cloned profiles are kept by default and deleted only if asked. They are
    derived from the recorded voice; silently binning them alongside a cache is not ours
    to do.
    """
    freed = 0
    targets = [*WEIGHTS_DIRS.values(), VENV, CACHE] + ([] if keep_profiles else [PROFILES])
    for d in targets:
        if d.exists():
            freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            shutil.rmtree(d)
    return {"freed_bytes": freed, "profiles_kept": keep_profiles}


def _supports_turbo(py: Path) -> bool:
    """Whether this install can load the fast model at all.

    The old check asked whether `from_local` had a `nano` parameter. It never
    has one - the signature is (ckpt_dir, device) - so this returned False on
    every version ever released, the fast variant was permanently unreachable,
    and a comment blamed an unreleased loader for it. What actually matters is
    whether the turbo module imports.

    The probe is CACHED on disk, and must be. Importing the turbo module
    means importing torch in a subprocess - measured at ~10 seconds - and
    capabilities() runs on every app launch, before the first screen paints.
    The answer only changes when the installed package changes, so the stamp
    is keyed by the package version and the probe runs once per install.
    """
    version = _version(py) or "unknown"
    stamp = VENV / f".turbo-probe-{version}"
    try:
        if stamp.exists():
            return stamp.read_text().strip() == "yes"
    except OSError:
        pass
    r = subprocess.run(
        [str(py), "-c",
         "from chatterbox.tts_turbo import ChatterboxTurboTTS, Conditionals;print('yes')"],
        capture_output=True, text=True,
    )
    ok = r.stdout.strip() == "yes"
    try:
        stamp.write_text("yes" if ok else "no")
    except OSError:
        pass  # no stamp just means probing again next launch
    return ok


# ------------------------------------------------------- reference audio


def _best_window(path: Path) -> tuple[np.ndarray, int, float]:
    """Pick the cleanest ~20s of a long recording.

    The model only looks at the first 10-15s of whatever it is handed, so
    passing the whole passage would clone whichever 15 seconds happened to be
    at the front - throat-clearing, the microphone being adjusted, the loudest
    "Good morning" of the session. Choosing deliberately is free and matters
    more than length: score windows by how much of them is continuous speech,
    penalise clipping hard, and start on a speech onset.
    """
    a, sr = sf.read(path, dtype="float32", always_2d=True)
    a = a.mean(axis=1)
    if len(a) < MIN_REF * sr:
        raise CloneError(
            f"{path.name} is only {len(a) / sr:.1f}s long; the voice model needs at "
            f"least {MIN_REF:.0f}s of connected speech (the reading passage is ideal)."
        )
    hop = int(sr * 0.05)
    n = len(a) // hop
    rms = np.array([np.sqrt(np.mean(a[i * hop:(i + 1) * hop] ** 2)) for i in range(n)])
    clip = np.array([np.mean(np.abs(a[i * hop:(i + 1) * hop]) > 0.99) for i in range(n)])
    voiced = rms > 0.15 * np.percentile(rms, 95)

    w = min(int(REF_WINDOW / 0.05), n)
    best, score = 0, -1e9
    for i in range(0, max(n - w, 0) + 1, 20):  # 1s hop
        s = voiced[i:i + w].mean() - 3.0 * clip[i:i + w].mean()
        if s > score:
            best, score = i, s
    # Trim to the first voiced frame so the clip does not open on a pause.
    on = np.flatnonzero(voiced[best:best + w])
    start = (best + int(on[0])) * hop if on.size else best * hop
    return a[start:start + int(REF_WINDOW * sr)], sr, start / sr


# ---------------------------------------------------------------- worker


class _Worker:
    """A persistent child interpreter holding the loaded model.

    Persistent because loading half a gigabyte of weights takes tens of seconds
    on a CPU, and the dictionary tier is thousands of items - a process per call
    would spend all its time in `torch.load`. A child at all because the model
    lives in a different venv, and because an OOM in a 3 GB model should not
    take the app down with it.
    """

    def __init__(self, py: Path, variant: str = DEFAULT_VARIANT):
        self.variant = variant
        # stderr goes to a file, not a pipe: torch and transformers emit enough
        # warnings at load to fill a 64K pipe buffer, and a full pipe nobody is
        # reading deadlocks the child halfway through loading the model.
        self.log = ROOT / "build" / "clone-worker.log"
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.p = subprocess.Popen(
            [str(py), "-m", "gen.clone", "--worker", variant], cwd=str(ROOT),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=open(self.log, "w"), text=True, bufsize=1,
        )

    def call(self, **req) -> dict:
        if self.p.poll() is not None:
            raise CloneError("The voice model process stopped unexpectedly.")
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            tail = self.log.read_text(errors="replace")[-2000:] if self.log.exists() else ""
            raise CloneError(f"The voice model process stopped unexpectedly.\n{tail}")
        out = json.loads(line)
        if "error" in out:
            raise CloneError(out["error"])
        return out

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


_WORKER: _Worker | None = None


def _worker(variant: str = DEFAULT_VARIANT) -> _Worker:
    """The child holding the loaded model, started on demand.

    One at a time, not one per variant: each model is gigabytes of resident
    weights, and holding both so a parent can switch without a pause would
    trade a few seconds for a few gigabytes on the laptops this has to run on.
    Switching variants replaces the worker.
    """
    global _WORKER
    if _WORKER is not None and (_WORKER.p.poll() is not None
                                or _WORKER.variant != variant):
        _WORKER.close()
        _WORKER = None
    if _WORKER is None:
        caps = capabilities(variant)
        if not caps["available"]:
            raise CloneError(caps["reason"])
        _WORKER = _Worker(Path(caps["interpreter"]), variant)
    return _WORKER


# ----------------------------------------------------------------- API


def clone_voice(reference_wav, out_dir, variant: str = DEFAULT_VARIANT) -> Path:
    """Build a speaker profile from their passage recording.

    Writes `profile.pt` (the model's conditioning tensors), the 20s excerpt it
    was built from, and a plain-text `profile.json`. The excerpt is kept so the
    profile can be rebuilt if the model is ever upgraded - and so there is one
    obvious file to delete if they wants it gone.
    """
    w = _worker(variant)  # fail before writing anything if the model is missing
    reference_wav, out_dir = Path(reference_wav), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    excerpt, sr, offset = _best_window(reference_wav)
    ref = out_dir / "reference.wav"
    if not ref.exists():
        sf.write(ref, excerpt, sr)
    info = w.call(op="clone", reference=str(ref),
                  out=str(profile_file(out_dir, variant)))
    # One json per model, so cloning the fast one does not overwrite the record
    # of the good one.
    name = "profile.json" if variant == "english" else f"profile.{variant}.json"
    (out_dir / name).write_text(json.dumps({
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": reference_wav.name,
        "excerpt_offset_s": round(offset, 2),
        "excerpt_seconds": round(len(excerpt) / sr, 2),
        "variant": variant,
        "package_version": info.get("version"),
        "sample_rate": SR,
        "consent": "Their recording, the recorded voice, their machine. Do not ship or share.",
    }, indent=2))
    return out_dir


def synthesize(text: str, profile, variant: str = DEFAULT_VARIANT) -> np.ndarray:
    """Speak `text` in the cloned voice. float32, mono, 24000 Hz - same as Voice.say()."""
    d = Path(profile["path"] if isinstance(profile, dict) else profile)
    pt = profile_file(d, variant) if d.is_dir() else d
    if not pt.exists():
        raise CloneError(
            f"No {variant} voice profile at {d} - clone one from the passage "
            "recording first."
        )
    # The variant is in the cache key: the two models say the same sentence
    # differently, and serving one from the other's cache would silently swap
    # her voice for a plainer one mid-video.
    key = hashlib.sha1(f"{text}|{variant}".encode()).hexdigest()[:16]
    out = CACHE / f"_synth-{key}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    _worker(variant).call(op="synth", text=text, profile=str(pt), out=str(out))
    a, sr = sf.read(out, dtype="float32")
    out.unlink(missing_ok=True)
    if sr != SR:
        raise CloneError(f"voice model returned {sr} Hz, expected {SR}")
    return a


class ClonedVoice:
    """Drop-in replacement for soundout.Voice at levels 6-8.

    Same shape as `Voice.say()` - text in, float32 at SR out, cached on disk by
    content - so the storyboard code does not care which one it is holding.
    Caching matters far more here than it does for Kokoro: a sentence costs
    tens of seconds of CPU once, and nothing thereafter.
    """

    def __init__(self, profile, speed=1.0, variant: str = DEFAULT_VARIANT):
        self.dir = Path(profile)
        self.speed = speed
        self.variant = variant
        self.cache = CACHE
        self.cache.mkdir(parents=True, exist_ok=True)

    def say(self, text, speed=None, phonemes=False) -> np.ndarray:
        if phonemes:
            # Chatterbox is grapheme-driven; there is no IPA back door. Levels
            # 3-5 use their recorded phonemes anyway, so this should never fire.
            raise CloneError("The cloned voice cannot speak IPA - use the recorded phonemes.")
        speed = self.speed if speed is None else speed
        key = hashlib.sha1(
            f"{text}|{self.dir.name}|{speed}|{self.variant}".encode()).hexdigest()[:16]
        path = self.cache / f"{key}.wav"
        if path.exists():
            samples, _ = sf.read(path, dtype="float32")
            return samples
        samples = synthesize(text, self.dir, self.variant)
        if abs(speed - 1.0) > 0.01:
            samples = slower(samples, speed)  # the model has no speed control
        sf.write(path, samples, SR)
        return samples


# --------------------------------------------------------- worker process


def _worker_main() -> None:
    """Child process: load once, then answer JSON lines on stdin.

    Everything torch touches lives below this line and runs in `.venv-clone`.

    ## stdout belongs to the protocol, and nothing else

    The model stack prints to stdout uninvited. Chatterbox's watermarker
    announces itself with "loaded PerthNet (Implicit) at step 250,000" the
    moment it loads, and that line arrived first on the pipe - so the parent
    read a banner where it expected JSON and cloning failed with a
    JSONDecodeError that named nothing useful.

    Suppressing that one message would be treating the symptom. Any library in
    a stack this size may print at any time, including from C, where replacing
    sys.stdout would not help. So file descriptor 1 is redirected to stderr for
    the whole process, and the protocol writes to a duplicate of the original -
    a handle nothing else can reach. Chatter goes to the log where it is
    harmless, and the channel carries only what this function puts on it.
    """
    # Do this before importing anything heavy - the banner fires at import.
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    protocol = os.fdopen(protocol_fd, "w", buffering=1)

    import torch  # noqa: F401  - present only in the sidecar environment

    variant = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VARIANT
    if variant not in VARIANTS:
        variant = DEFAULT_VARIANT
    ckpt = weights_dir(variant)
    device = "cpu"
    try:
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
    except Exception:
        pass

    if variant == "turbo":
        # from_local(ckpt_dir, device). There is no `nano=True` - passing one
        # raises TypeError, which is what the previous version did.
        from chatterbox.tts_turbo import ChatterboxTurboTTS as Model
        from chatterbox.tts_turbo import Conditionals
        model = Model.from_local(ckpt, device)
    else:
        from chatterbox.tts import ChatterboxTTS as Model
        from chatterbox.tts import Conditionals
        model = Model.from_local(ckpt, device)
    assert model.sr == SR, f"voice model is {model.sr} Hz, pipeline is {SR} Hz"

    version = _version(Path(sys.executable))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            op = req.get("op")
            if op == "clone":
                model.prepare_conditionals(req["reference"])
                model.conds.save(Path(req["out"]))
                res = {"ok": True, "version": version, "device": device}
            elif op == "synth":
                model.conds = Conditionals.load(req["profile"], map_location=device).to(device)
                wav = model.generate(req["text"])
                a = wav.squeeze(0).detach().cpu().numpy().astype("float32")
                sf.write(req["out"], a, model.sr)
                res = {"ok": True, "samples": int(a.size)}
            elif op == "info":
                res = {"ok": True, "version": version, "device": device, "variant": variant}
            else:
                res = {"error": f"unknown op {op!r}"}
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {e}"}
        protocol.write(json.dumps(res) + "\n")
        protocol.flush()


if __name__ == "__main__":
    if "--worker" in sys.argv:
        _worker_main()
    else:
        print(json.dumps(capabilities(), indent=2))
