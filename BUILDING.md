# Building Sound It Out

Three installers from one codebase: a `.dmg` for macOS, an NSIS `.exe` for
Windows, an `.AppImage` for Linux. Each one carries everything — Electron, the
frozen Python sidecar, the Kokoro weights, the Andika fonts, the recorded
phoneme clips. The machine it lands on is assumed to have no internet and no
developer tools.

## The two halves

| Half | What it is | Built by |
|---|---|---|
| Electron app | `app/` — window, renderer, frame rendering via Chromium | electron-builder |
| Python sidecar | `gen/service.py` frozen to one executable, JSON lines over stdio | PyInstaller |

The sidecar exists so the end user never installs Python, pip, or espeak-ng.
The app spawns it and talks to it over stdin/stdout.

## Build it

Two commands, in this order — electron-builder expects the frozen sidecar to
already be sitting in `dist/sidecar/`.

```bash
./setup.sh                          # once: venv, Kokoro models, Andika
.venv/bin/pip install pyinstaller   # once
npm install                         # once

source .venv/bin/activate    # npm run sidecar calls `python`, so the venv
                             # must be the active one
npm run sidecar              # freeze gen/service.py -> dist/sidecar/
npm run dist                 # wrap it -> dist/installers/
```

On Windows that first line is `.venv\Scripts\activate`.

`npm run dist` builds for whatever machine you are on. To be explicit:

```bash
npx electron-builder --mac dmg --arm64
npx electron-builder --win nsis --x64
npx electron-builder --linux AppImage --x64
```

Output lands in `dist/installers/`. Expect roughly 500MB per installer — the
Kokoro weights are 338MB of that and are not compressible.

### Per-platform prerequisites

**macOS** — Xcode command line tools. Nothing else.

**Windows** — Python 3.11 from python.org (not the Store build; the Store's
sandboxed filesystem confuses PyInstaller). Node 22.

**Linux** — for the AppImage you need FUSE (`libfuse2` or `libfuse2t64`), and
for the frame-render smoke test you need `xvfb` plus Chromium's shared
libraries. `frames.js` opens a real `BrowserWindow` with `offscreen: false`, so
even a headless render needs an X server:

```bash
xvfb-run -a npx electron app/render-cli.js <jobDir>
```

Chromium's other container/CI problem — a 64MB `/dev/shm` it aborts on — is
already handled: `app/render-cli.js` appends `--disable-dev-shm-usage` and
`--no-sandbox` itself, so there is nothing to pass on the command line.

## PyInstaller cannot cross-compile

This is the single biggest constraint on the build, and there is no way around
it. PyInstaller freezes for the OS **and** the CPU architecture of the machine
it runs on. It bundles a native bootloader, a native CPython, and native
extension modules — there is no target flag, and `--target-arch` on macOS only
selects between slices that are already present in the wheels.

In practice:

- A **macOS** build requires a Mac. No Docker image, no Linux runner, no
  workaround.
- An **Apple Silicon** dmg requires an Apple Silicon Mac; an **Intel** dmg
  requires an Intel Mac (or Rosetta with an x86_64 Python, which is fiddly
  enough that CI just uses two runners).
- A **Windows** build requires Windows. Wine does not work.

This is why `.github/workflows/build.yml` has four matrix entries for three
platforms: `macos-latest` (arm64) and `macos-13` (x64) are separate jobs
producing separate dmgs. Building both mac dmgs on one runner would put an
arm64 sidecar inside the Intel installer, which installs perfectly and then
dies the first time the app tries to speak.

If you only have one Mac, build for that architecture and let CI produce the
other.

## What CI does

`.github/workflows/build.yml`, triggered on `workflow_dispatch` and on `v*`
tags. Per runner:

1. Checkout, Node 22, Python 3.11.
2. Linux only: `xvfb`, Chromium's shared libraries, FUSE, `libsndfile1`.
3. `pip install kokoro-onnx soundfile numpy pyinstaller`.
4. Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the same release URLs
   `setup.sh` uses. Cached by model version, so this is a one-time 338MB.
5. `pyinstaller build/sidecar.spec` → `dist/sidecar/soundout-sidecar[.exe]`.
6. Smoke-test the sidecar by speaking its protocol at it: a `ping` and a
   `capabilities` request, then `shutdown`. This is a hard failure.
7. Smoke-test the *speech* path with a `plan` request — advisory only. Step 6
   passes even with espeak-ng missing from the bundle, because service.py
   imports the TTS stack lazily; `plan` is the first thing that actually loads
   phonemizer.
8. Linux only: render one frame under `xvfb-run` to prove Chromium and the
   font path work. Advisory.
9. `npm ci`, then `npx electron-builder` for that platform.
10. Upload the installer (14 days) and the raw sidecar (7 days) as artifacts.

`fail-fast` is off, so one platform breaking still gets you the other three
artifacts. The repo is private on a paid plan; runner minutes are not a
constraint, so the workflow prefers doing the obvious thing four times over
doing something clever once.

### Before the first CI run

`.gitignore` currently ignores `build/`, which includes `build/sidecar.spec`.
Until that is un-ignored the CI checkout will not contain the spec and the
freeze step fails with "spec file not found". One line fixes it:

```gitignore
build/
!build/sidecar.spec
```

## Installing an unsigned build

Neither the Mac app nor the Windows installer is code-signed, and that is
deliberate. Signing costs $99/yr for an Apple Developer account plus roughly
$200/yr for a Windows code-signing certificate, renewed forever, for a private
family app installed on a handful of machines. The alternative cost is one
click at install time, once per machine. See the note in
`electron-builder.yml` before changing this.

### macOS

Double-clicking the app the first time gives *"Sound It Out" cannot be opened
because it is from an unidentified developer* (or, on Sonoma and later,
*"…" is damaged and can't be opened*, which is Gatekeeper being unhelpful
rather than an actual corrupt download).

1. Drag the app from the dmg to **Applications** as usual.
2. Double-click it. Let the warning appear, then dismiss it.
3. Open **System Settings → Privacy & Security**.
4. Scroll to the **Security** section. There is a line reading
   *"Sound It Out" was blocked from use because it is not from an identified
   developer*, with an **Open Anyway** button next to it.
5. Click **Open Anyway**, then **Open** in the confirmation dialog.

**This is once per machine, not once per launch.** macOS records the decision;
every launch after this is a normal double-click. It has to be repeated only if
the app is deleted and reinstalled, or a new version is installed.

The older right-click → **Open** trick still works on some versions and is
worth trying first if the Privacy & Security pane shows nothing — the button
only appears within about an hour of the blocked launch attempt, so if it is
missing, double-click the app again and go straight back to Settings.

### Windows

SmartScreen shows a blue **"Windows protected your PC"** panel with only a
*Don't run* button visible.

1. Click **More info** — this reveals the app name and publisher.
2. Click **Run anyway**.

Once per downloaded installer. The installed app launches normally afterwards.

### Linux

Nothing to bypass. Mark it executable and run it:

```bash
chmod +x "Sound It Out-0.1.0.AppImage"
./"Sound It Out-0.1.0.AppImage"
```

## What ends up where

Inside the packaged app, `process.resourcesPath` contains:

```
models/          kokoro-v1.0.onnx, voices-v1.0.bin
wordlists/       user-editable .txt files
assets/commons/  hand-checked recorded phoneme clips
sidecar/         soundout-sidecar[.exe]
app.asar         the Electron app
app.asar.unpacked/app/fonts/   Andika, unpacked on purpose
```

The fonts are unpacked because `frames.js` hands Chromium a `file://` URL for
each `.ttf`, and Chromium's network stack cannot read inside an asar archive.
Packed, every frame silently falls back to a system font — which means the
two-story `a` and `g` that the Andika choice exists to avoid.

The models stay outside the PyInstaller bundle because a onefile executable
unpacks its entire payload to a temp directory on every single launch, and
unpacking 338MB each time the app starts is not usable.

## Things that break quietly

**espeak-ng.** The one to check first when the app starts fine and then cannot
speak. `phonemizer` loads a native espeak-ng library and its language
dictionaries out of the `espeakng_loader` wheel by *path*, via `ctypes` — no
import for PyInstaller to follow, no linker record to scan. `build/sidecar.spec`
places both under `espeakng_loader/` in the bundle, which is exactly where the
loader's `Path(__file__).parent` lookup expects them. Move them and it raises
`data path not exists` at the first word.

**Version metadata.** `import phonemizer` calls
`importlib.metadata.version("phonemizer-fork")` at module scope. Frozen bundles
carry no `.dist-info` unless asked, so without `copy_metadata` the sidecar dies
on import, before it can log anything.

**`ROOT` under a frozen bundle.** Both `gen/service.py` and `gen/soundout.py`
locate everything from `Path(__file__).resolve().parent.parent`. That is
correct when running from a checkout and wrong once frozen: PyInstaller sets
`__file__` to a path inside the temp directory it unpacks itself into, so
`ROOT / "models"` points at a directory that does not exist and `build/jobs`
lands somewhere that is deleted when the process exits. Packaging cannot fix
this from the outside — the resolution has to become something like:

```python
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent.parent   # Resources/
else:
    ROOT = Path(__file__).resolve().parent.parent
```

with the job directory moved to the user's app-data directory rather than
anywhere under `Resources/`, which is read-only on macOS. The CI "speech path"
smoke test is the canary for this.

**The Windows console window.** The sidecar is frozen with `console=True`,
because PyInstaller's windowed mode on Windows points stdout at `NUL` — which
would silently break every reply on a process whose entire interface is stdio.
The app must therefore spawn it with `windowsHide: true`, or Windows users get
a black console window alongside the app.
