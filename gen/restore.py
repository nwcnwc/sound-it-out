"""Preview conservative repairs to the recorded voice bank.

    python -m gen.restore                 # representative sample
    python -m gen.restore --all
    python -m gen.restore --clips s,f,cat

Writes A/B pairs and a listening page to build/restore-preview/. It NEVER
writes to the voice bank - see the guard in `_check_output_dir`. Applying
anything for real is a separate, deliberate step that does not live here.

## What it does, and why it is so little

Measured on the bank as recorded (cheap mic, untreated room, Chromebook):

    clipping        none
    DC offset       none
    level spread    tight - median peak -17 dBFS
    room tone       -55 dBFS
    mains           one weak line at 120 Hz, +7 dB over the floor
    fricatives      intact - /s/ carries 98% of its energy above 4 kHz and
                    rolls off at 11.5 kHz, hard against the 12 kHz Nyquist

So there is no disaster to undo, and the temptation to reach for noise
reduction has to be resisted. gen/studio.py already makes the argument, about
averaging takes rather than denoising, and it applies unchanged here:

    Blurring formants to reduce a little hiss is a bad trade when the whole
    point is teaching a child to hear the difference between /s/ and /f/.

Spectral-subtraction denoising does exactly that to a held /s/ - the fricative
IS broadband noise, so the algorithm cannot tell it from the room and takes
both. Everything below is therefore surgical: it removes energy at frequencies
that carry no speech, and nothing else.

    1. high-pass    rumble, handling, desk thumps. Fully passing by 65 Hz,
                    comfortably below the speaker's 90 Hz pitch floor.
    2. edge fade    the reason this exists is subtler than the other one, and
                    is probably the most audible of the three. gen/soundout.py
                    inserts DIGITAL silence between clips, but each clip keeps
                    60 ms of real room tone either side of it (studio._trim).
                    So -55 dBFS of tone switches on and off at every clip
                    boundary - and mastering to -14 LUFS lifts it about 15 dB
                    on the way out. Fading those edges removes the click-track
                    of room tone appearing and vanishing.

Filtering is zero-phase (applied as a gain curve in the frequency domain, on
reflect-padded audio) rather than a biquad. A held phoneme is a steady state
whose waveform shape is the thing being taught, and an IIR filter's phase
response smears exactly that. Zero-phase costs nothing here because these are
short offline clips, not a realtime path.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from gen.paths import BANK_DIRS, BUILD, SOUNDS, VOICE_DIR

OUT_DIR = BUILD / "restore-preview"

# Tuned to the speaker actually in the bank, measured rather than assumed:
# F0 median 118 Hz over 483 voiced frames of connected speech, p5 92 Hz,
# lowest 2% 90 Hz. Both settings below follow from that one number.
HP_STOP, HP_PASS = 30.0, 65.0   # fully passing well under the 90 Hz floor
NOTCH_HZ = ()                   # deliberately empty - see below
NOTCH_WIDTH = 2.5
FADE_MS = 25.0                  # sits inside studio._trim's 60 ms padding

# There is no mains notch, and the reason is a correction worth recording.
#
# An earlier pass "found" mains hum on 288 of 331 clips, worst on /v/, /z/ and
# /ð/, and this file notched 120 Hz to remove it. The detector was measuring
# the speaker's own fundamental. His F0 is 118 Hz; the voiced consonants
# scored worst precisely BECAUSE they are voiced, and a 120 Hz notch on a
# 118 Hz voice removes the voice.
#
# Genuine mains, measured on real room tone from passage.wav with no speech in
# it, came to one line at 120 Hz some 7 dB over the floor - marginal, and
# indistinguishable at that level from the same confound. Nothing is removed
# on that evidence.
#
# If a future speaker is notched, verify F0 FIRST (autocorrelation, not the
# strongest low spectral peak - that lands on a harmonic as often as not) and
# confirm the line survives in speech-free tone.


# --------------------------------------------------------------- safety


def _check_output_dir(out: Path) -> Path:
    """Refuse to write anywhere inside the recordings.

    The bank is irreplaceable and gitignored, and this repo has lost 42 clips
    to a cleanup step that assumed a directory held only test data. A preview
    tool has no business writing there at all, so it is not a matter of being
    careful - the path is checked and the program stops.
    """
    out = out.resolve()
    voice = VOICE_DIR.resolve()
    if out == voice or voice in out.parents or out in voice.parents:
        sys.exit(f"refusing to write to {out}: it overlaps the voice bank at {voice}")
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------- filters


def _gain_curve(f: np.ndarray) -> np.ndarray:
    """The whole repair, as one multiplicative response over frequency."""
    g = np.ones_like(f)

    # High-pass: raised cosine so there is no ringing from a brick wall.
    below = f <= HP_STOP
    ramp = (f > HP_STOP) & (f < HP_PASS)
    g[below] = 0.0
    g[ramp] = 0.5 - 0.5 * np.cos(np.pi * (f[ramp] - HP_STOP) / (HP_PASS - HP_STOP))

    # Notches: narrow Gaussian dips, one per measured mains line.
    for f0 in NOTCH_HZ:
        g *= 1.0 - np.exp(-(((f - f0) / NOTCH_WIDTH) ** 2))
    return g


def _filter(a: np.ndarray, sr: int) -> np.ndarray:
    """Zero-phase filtering via the frequency domain, on reflect-padded audio."""
    n0 = a.size
    pad = min(4096, max(1, n0 - 2))
    if n0 > pad + 1:
        padded = np.concatenate([a[pad:0:-1], a, a[-2:-pad - 2:-1]])
    else:
        padded, pad = a, 0
    spec = np.fft.rfft(padded)
    freqs = np.fft.rfftfreq(padded.size, 1.0 / sr)
    out = np.fft.irfft(spec * _gain_curve(freqs), n=padded.size)
    if pad:
        out = out[pad:pad + n0]
    return out[:n0].astype("float32")


def _edge_fade(a: np.ndarray, sr: int, ms: float = FADE_MS) -> np.ndarray:
    """Raised-cosine fade at both ends, never eating more than a quarter."""
    n = min(int(sr * ms / 1000.0), a.size // 4)
    if n < 8:
        return a
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n, dtype="float32"))
    out = a.copy()
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def restore(a: np.ndarray, sr: int) -> np.ndarray:
    return _edge_fade(_filter(a, sr), sr)


# ---------------------------------------------------------------- metrics


def _band_db(a: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Energy in a band, in dB relative to the clip's total."""
    n = min(8192, 1 << int(np.log2(max(a.size, 2))))
    if a.size < n:
        a = np.pad(a, (0, n - a.size))
    win = np.hanning(n)
    acc, cnt = np.zeros(n // 2 + 1), 0
    for i in range(0, a.size - n + 1, n // 2):
        acc += np.abs(np.fft.rfft(a[i:i + n] * win)) ** 2
        cnt += 1
    if cnt == 0:
        return -120.0
    p = acc / cnt
    f = np.fft.rfftfreq(n, 1.0 / sr)
    tot = p.sum()
    if tot <= 0:
        return -120.0
    return 10 * np.log10(max(p[(f >= lo) & (f < hi)].sum(), 1e-24) / tot)


def measure(a: np.ndarray, sr: int) -> dict:
    return {
        "peak": 20 * np.log10(max(float(np.abs(a).max()), 1e-12)),
        "rms": 20 * np.log10(max(float(np.sqrt(np.mean(a ** 2))), 1e-12)),
        "sub80": _band_db(a, sr, 0, 80),
        "line120": _band_db(a, sr, 116, 124),
        "hf4k": _band_db(a, sr, 4000, sr / 2),
    }


# ------------------------------------------------------------- selection


def _safe(name: str) -> str:
    return "".join(f"u{ord(c):04x}" if not c.isalnum() else c for c in name)


def _label(src: Path) -> str:
    """Readable name. Sentence stems are escaped twice over - once by
    sentence_key (spaces to underscores) and once by _safe (underscores to
    u005f) - so a whole line arrives as `au005fdogu005fsatu005fonu005fsam`,
    which is unusable on a page whose entire job is telling you what you are
    about to hear."""
    from gen.studio import _undo_safe

    stem = _undo_safe(src.stem)
    return stem.replace("_", " ") if src.parent.name == "sentences" else stem


# Chosen to stress the two things that could go wrong: damage to the sounds
# whose whole identity is high-frequency noise, and failure to fix the clips
# that actually measured worst.
SAMPLE = (
    [VOICE_DIR / SOUNDS / f"{_safe(p)}.wav"
     for p in ("s", "ʃ", "f", "θ", "z", "v", "tʃ", "ð")]          # fricatives
    + [VOICE_DIR / SOUNDS / f"{_safe(p)}.wav"
       for p in ("p", "k", "b", "eɪl")]                            # worst SNR
    + [VOICE_DIR / SOUNDS / f"{_safe(p)}.wav"
       for p in ("iː", "ɑː")]                                      # vowels
)


def pick(args) -> list:
    if args.all:
        found = [p for p in sorted(VOICE_DIR.rglob("*.wav"))
                 if not p.name.endswith(".previous.wav")]
    elif args.clips:
        wanted = [c.strip() for c in args.clips.split(",") if c.strip()]
        found = []
        for w in wanted:
            hits = [p for p in sorted(VOICE_DIR.rglob("*.wav"))
                    if not p.name.endswith(".previous.wav")
                    and (p.stem == w or p.stem == _safe(w))]
            if hits:
                found.extend(hits)
            else:
                print(f"  ?? no clip named {w!r}")
    else:
        found = list(SAMPLE)
        found += sorted((VOICE_DIR / "words").glob("*.wav"))[:4]
        found += sorted((VOICE_DIR / "sentences").glob("*.wav"))[:2]
    return [p for p in found if p.exists()]


# ------------------------------------------------------------------ main


PAGE_CSS = """
body{background:#0d1b2a;color:#f8f4e9;font:15px/1.5 system-ui,sans-serif;
     margin:0;padding:32px;max-width:1100px}
h1{font-size:20px;margin:0 0 4px} p.sub{color:#9fb3c8;margin:0 0 28px}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid #1e3148;
      vertical-align:middle}
th{color:#9fb3c8;font-weight:600;font-size:12px;text-transform:uppercase;
   letter-spacing:.06em}
td.name{font-weight:700;font-size:17px;white-space:nowrap}
td.grp{color:#5c6b7a;font-size:12px}
audio{height:32px;vertical-align:middle}
.num{font-variant-numeric:tabular-nums;text-align:right;font-size:13px}
.good{color:#7fd18b} .warn{color:#ffd166} .flat{color:#5c6b7a}
"""


def _delta_class(d: float, want_down: bool) -> str:
    if abs(d) < 0.5:
        return "flat"
    return "good" if (d < 0) == want_down else "warn"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="every clip in the bank")
    ap.add_argument("--clips", help="comma-separated clip names")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args(argv)

    out = _check_output_dir(Path(args.out))
    clips = pick(args)
    if not clips:
        sys.exit("no clips matched")

    print(f"reading  {VOICE_DIR}")
    print(f"writing  {out}\n")

    rows = []
    for src in clips:
        a, sr = sf.read(src, dtype="float32", always_2d=False)
        if a.ndim > 1:
            a = a.mean(axis=1)
        if a.size < 64:
            print(f"  skip {src.name}: too short")
            continue
        b = restore(a, sr)
        before, after = measure(a, sr), measure(b, sr)

        stem = f"{src.parent.name}--{src.stem}"
        sf.write(out / f"{stem}.before.wav", a, sr)
        sf.write(out / f"{stem}.after.wav", b, sr)

        # A/B in one file, level-matched, so the comparison is about tone and
        # not about which one happens to be louder.
        gain = 10 ** ((before["rms"] - after["rms"]) / 20)
        ab = np.concatenate([a, np.zeros(int(sr * 0.4), "float32"),
                             np.clip(b * gain, -1, 1)]).astype("float32")
        sf.write(out / f"{stem}.ab.wav", ab, sr)

        rows.append((src, stem, before, after))
        print(f"  {src.parent.name}/{_label(src)[:24]:<24} "
              f"sub80 {before['sub80']:>6.1f} -> {after['sub80']:>6.1f}   "
              f"120Hz {before['line120']:>6.1f} -> {after['line120']:>6.1f}   "
              f"HF {before['hf4k']:>6.1f} -> {after['hf4k']:>6.1f}")

    body = [f"<style>{PAGE_CSS}</style>",
            "<h1>Voice bank &mdash; repair preview</h1>",
            f"<p class='sub'>{len(rows)} clips. Nothing in "
            f"<code>{html.escape(str(VOICE_DIR))}</code> was modified. "
            "Numbers are dB relative to each clip's total energy; "
            "<b>HF should not move</b>.</p>",
            "<table><tr><th>clip</th><th>before</th><th>after</th>"
            "<th class='num'>&lt;80 Hz</th><th class='num'>120 Hz</th>"
            "<th class='num'>&gt;4 kHz</th></tr>"]
    for src, stem, bf, af in rows:
        d80, d120, dhf = (af["sub80"] - bf["sub80"], af["line120"] - bf["line120"],
                          af["hf4k"] - bf["hf4k"])
        body.append(
            f"<tr><td class='name'>{html.escape(_label(src))}"
            f"<div class='grp'>{html.escape(src.parent.name)}</div></td>"
            f"<td><audio controls preload='none' src='{stem}.before.wav'></audio></td>"
            f"<td><audio controls preload='none' src='{stem}.after.wav'></audio></td>"
            f"<td class='num {_delta_class(d80, True)}'>{d80:+.1f}</td>"
            f"<td class='num {_delta_class(d120, True)}'>{d120:+.1f}</td>"
            f"<td class='num {_delta_class(dhf, False)}'>{dhf:+.1f}</td></tr>")
    body.append("</table>")
    page = out / "index.html"
    page.write_text("\n".join(body), encoding="utf-8")

    print(f"\n{len(rows)} clips written. Listen:\n  xdg-open {page}")
    print("\nEach clip also has a .ab.wav - before, 0.4s gap, after, level-matched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
