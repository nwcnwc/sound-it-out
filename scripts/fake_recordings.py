"""Fill the voice library with stand-in clips, so the rest of the app can be
tested without a working microphone.

THESE ARE NOT ANYONE'S VOICE. Every clip is the built-in Kokoro voice, written
into exactly the places and filenames the recording studio would have written -
so the app will behave as though a real session happened, and will report the
levels as "from recordings", because as far as it can tell they are.

Kokoro rather than tones or noise on purpose: the point is to exercise video
generation, and that only means anything if the audio is real speech with real
durations.

A marker file is written alongside so there is never any doubt about what these
are, and `--remove` takes them all away again without touching anything else.

    python scripts/fake_recordings.py            # generate
    python scripts/fake_recordings.py --remove   # delete only the stand-ins
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from gen import studio  # noqa: E402
from gen.paths import VOICE_DIR  # noqa: E402
from gen.soundout import SR, Voice, silence, tidy_word  # noqa: E402

MARKER = "STAND-IN-CLIPS.json"


def passage_text() -> list:
    from gen.paths import RESOURCES

    raw = (RESOURCES / "PASSAGE.md").read_text(encoding="utf-8")
    body = raw.split("## One", 1)[-1]
    out = []
    for block in body.split("\n\n"):
        line = " ".join(block.split())
        if not line or line.startswith("#") or line.startswith("*") or set(line) <= {"-"}:
            continue
        out.append(line.lstrip("# ").strip())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true",
                    help="delete the stand-in clips and nothing else")
    ap.add_argument("--skip-passage", action="store_true")
    ap.add_argument("--top-up", action="store_true",
                    help="generate only what is missing, leaving existing clips alone")
    args = ap.parse_args()

    marker = VOICE_DIR / MARKER

    if args.remove:
        if not marker.exists():
            print("No stand-in clips recorded here - nothing removed.")
            print("(That marker is what makes this safe: without it, this "
                  "script will not delete anything.)")
            return 1
        listed = json.loads(marker.read_text()).get("files", [])
        gone = 0
        for rel in listed:
            f = VOICE_DIR / rel
            if f.exists():
                f.unlink()
                gone += 1
        marker.unlink()
        print(f"Removed {gone} stand-in clips.")
        return 0

    if marker.exists() and not args.top_up:
        print("Stand-in clips are already here. Use --top-up to fill gaps, "
              "or --remove first.")
        return 1
    if not args.top_up and VOICE_DIR.exists() and any(VOICE_DIR.rglob("*.wav")):
        print(f"REFUSING: {VOICE_DIR} already contains recordings, and they are "
              "not stand-ins.\nMove or back them up first - this script will not "
              "overwrite real ones.")
        return 1

    voice = Voice(voice="af_heart", speed=0.9)
    written = []
    t0 = time.time()

    phonemes = studio.plan("phonemes")
    words = studio.plan("words")
    print(f"Generating {len(phonemes)} sounds and {len(words)} words "
          f"(built-in voice, standing in for a real session)...")

    for n, it in enumerate(phonemes, 1):
        if args.top_up and it.done():
            written.append(str(it.path().relative_to(VOICE_DIR)))
            continue
        audio = voice.phoneme(it.ipa)
        studio.save(it, audio)
        written.append(str(it.path().relative_to(VOICE_DIR)))
        if n % 10 == 0 or n == len(phonemes):
            print(f"  sounds {n}/{len(phonemes)}")

    for n, it in enumerate(words, 1):
        if args.top_up and it.done():
            written.append(str(it.path().relative_to(VOICE_DIR)))
            continue
        audio = tidy_word(voice.say(it.display))
        studio.save(it, audio)
        written.append(str(it.path().relative_to(VOICE_DIR)))
        if n % 20 == 0 or n == len(words):
            print(f"  words {n}/{len(words)}")

    if args.top_up and (VOICE_DIR / "passage.wav").exists():
        args.skip_passage = True
        written.append("passage.wav")
    if not args.skip_passage:
        paras = passage_text()
        print(f"  passage: {len(paras)} paragraphs "
              f"({sum(len(p.split()) for p in paras)} words) - this is the slow part")
        chunks = []
        for n, para in enumerate(paras, 1):
            chunks.append(voice.say(para))
            chunks.append(silence(0.6))
            if n % 5 == 0 or n == len(paras):
                print(f"    {n}/{len(paras)}")
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        sf.write(VOICE_DIR / "passage.wav",
                 np.concatenate(chunks).astype("float32"), SR)
        written.append("passage.wav")

    marker.write_text(json.dumps({
        "what": "Stand-in clips generated by scripts/fake_recordings.py.",
        "voice": "Kokoro af_heart (the built-in voice) - NOT a real person.",
        "why": "Lets video generation be tested without a working microphone.",
        "remove_with": "python scripts/fake_recordings.py --remove",
        "files": written,
    }, indent=1))

    total = sum(f.stat().st_size for f in VOICE_DIR.rglob("*.wav"))
    print(f"\nWrote {len(written)} clips ({total / 1048576:.1f} MB) to {VOICE_DIR}")
    print(f"Took {time.time() - t0:.0f}s. Remove them with --remove.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
