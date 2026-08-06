#!/usr/bin/env bash
# One-time setup: Python env, Kokoro voice model, Andika font.
# Large binaries are not committed - this fetches them.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Python environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q kokoro-onnx soundfile numpy pyinstaller

echo "==> Kokoro voice model (~338MB)"
mkdir -p models
BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -f models/kokoro-v1.0.onnx ] || curl -L --progress-bar -o models/kokoro-v1.0.onnx "$BASE/kokoro-v1.0.onnx"
[ -f models/voices-v1.0.bin ]  || curl -L --progress-bar -o models/voices-v1.0.bin  "$BASE/voices-v1.0.bin"

# The app bundles Andika in app/fonts/ and loads it by @font-face, so a
# system-wide install is only needed for the development Chrome renderer on
# Linux. fc-list/fc-cache do not exist on macOS, so this is skipped there.
if [ "$(uname)" = "Linux" ] && command -v fc-list >/dev/null; then
  echo "==> Andika font (SIL, OFL - for the Linux dev renderer)"
  mkdir -p assets/fonts ~/.local/share/fonts
  if ! fc-list : family | grep -qi andika; then
    curl -sL -o assets/fonts/andika.zip https://software.sil.org/downloads/r/andika/Andika-6.200.zip
    unzip -oq assets/fonts/andika.zip -d assets/fonts
    find assets/fonts -name '*.ttf' -exec cp {} ~/.local/share/fonts/ \;
    fc-cache -f >/dev/null
  fi
fi

echo "==> Checking tools"
command -v ffmpeg >/dev/null || { echo "MISSING: ffmpeg - install it and re-run"; exit 1; }
# Chrome is NOT required to build or run the app: Electron renders frames with
# its own bundled Chromium. It is only the fallback renderer used when driving
# the pipeline from a terminal on Linux, so its absence is a note, not an error.
command -v google-chrome >/dev/null || command -v chromium >/dev/null || \
  echo "    (no system Chrome - fine; the app uses Electron's own)"

echo
echo "Done. Generate samples with:  .venv/bin/python -m gen.make_samples"
