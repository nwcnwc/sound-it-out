#!/usr/bin/env bash
# One-time setup: Python env, Kokoro voice model, Andika font.
# Large binaries are not committed - this fetches them.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Python environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q kokoro-onnx soundfile numpy

echo "==> Kokoro voice model (~338MB)"
mkdir -p models
BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -f models/kokoro-v1.0.onnx ] || curl -L --progress-bar -o models/kokoro-v1.0.onnx "$BASE/kokoro-v1.0.onnx"
[ -f models/voices-v1.0.bin ]  || curl -L --progress-bar -o models/voices-v1.0.bin  "$BASE/voices-v1.0.bin"

echo "==> Andika font (SIL, OFL licensed - designed for literacy learners)"
mkdir -p assets/fonts ~/.local/share/fonts
if ! fc-list : family | grep -qi andika; then
  curl -sL -o assets/fonts/andika.zip https://software.sil.org/downloads/r/andika/Andika-6.200.zip
  unzip -oq assets/fonts/andika.zip -d assets/fonts
  find assets/fonts -name '*.ttf' -exec cp {} ~/.local/share/fonts/ \;
  fc-cache -f >/dev/null
fi

echo "==> Checking ffmpeg + Chrome"
command -v ffmpeg >/dev/null || { echo "MISSING: ffmpeg"; exit 1; }
command -v google-chrome >/dev/null || command -v chromium >/dev/null || { echo "MISSING: chrome/chromium"; exit 1; }

echo
echo "Done. Generate samples with:  .venv/bin/python -m gen.make_samples"
