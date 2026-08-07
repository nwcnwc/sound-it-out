#!/usr/bin/env bash
# Record two seconds and say whether anything actually arrived.
#
# Written for ChromeOS/Crostini, where the container can present a perfectly
# healthy-looking microphone that delivers pure silence: the device exists,
# PipeWire lists it, it is unmuted and at full volume, and every sample is
# zero. Nothing inside Linux reports a problem, because as far as Linux is
# concerned there isn't one - ChromeOS is simply not passing the audio in.
set -uo pipefail
OUT=$(mktemp /tmp/miccheck-XXXX.wav)

echo "Recording 2 seconds - please say something out loud now..."
if ! ffmpeg -f pulse -i default -t 2 -y "$OUT" >/dev/null 2>&1; then
  echo "FAILED: could not open the microphone at all."
  echo "Check that PipeWire or PulseAudio is running: pgrep -a pipewire"
  exit 1
fi

python3 - "$OUT" <<'PY'
import sys, wave, array
with wave.open(sys.argv[1]) as w:
    frames = w.readframes(w.getnframes())
    width = w.getsampwidth()
# audioop is deprecated and gone in 3.13, and this needs no more than a max.
codes = {1: "b", 2: "h", 4: "i"}
a = array.array(codes.get(width, "h"))
a.frombytes(frames[: len(frames) - len(frames) % a.itemsize])
peak = (max(max(a), -min(a)) / float(2 ** (8 * width - 1))) if len(a) else 0.0
print(f"peak level: {peak:.5f}")
if peak == 0:
    print("""
RESULT: pure digital silence - not even background hiss.

On a Chromebook this is almost always the ChromeOS microphone permission for
Linux, which is separate from the browser's. Turn it on:

  Settings -> About ChromeOS -> Developers -> Linux development environment
  -> then enable "Allow Linux to access your microphone"

(On some versions: Settings, then search "microphone", and look for the Linux
entry rather than the site permissions one.)

Then restart the container so it picks the change up:
  - right-click the Terminal icon and choose "Shut down Linux", or
  - run:  sudo systemctl reboot     (from inside the container)

Run this script again afterwards. A working microphone reads well above
0.01 even in a quiet room.""")
    sys.exit(2)
elif peak < 0.01:
    print("\nRESULT: something is arriving, but it is very quiet. Check the input"
          "\nvolume, and that the right microphone is selected in ChromeOS.")
    sys.exit(3)
else:
    print("\nRESULT: the microphone is working.")
PY
rc=$?
rm -f "$OUT"
exit $rc
