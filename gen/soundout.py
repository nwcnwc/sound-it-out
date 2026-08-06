"""Sound It Out - video generation pipeline.

This is the real pipeline the app will use:
  Kokoro (TTS) -> storyboard -> headless Chrome (HTML/CSS frames) -> ffmpeg (mp4)

Rendering goes through Chrome so that sample output is pixel-identical to what
the Electron app will show. Frames are rendered one per *visual state*, not one
per video frame, because the display is static text with discrete highlight
changes - so a 20 minute video is a few hundred PNGs, not 36,000.
"""

from __future__ import annotations

import hashlib
import html
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
BUILD = ROOT / "build"
SAMPLES = ROOT / "samples"
SR = 24000

# ---------------------------------------------------------------- themes


@dataclass
class Theme:
    """Visual treatment. These are the variables we want feedback on."""

    name: str
    bg: str
    fg: str
    highlight: str
    dim: str
    weight: int = 700
    # per-word colour override, e.g. Paw Patrol character colours
    word_colors: dict = field(default_factory=dict)


THEMES = {
    # Deep navy, warm cream text. Easy on the eyes for long loops in a dim room.
    "night": Theme("night", "#0d1b2a", "#f8f4e9", "#ffd166", "#5c6b7a"),
    # Warm off-white, like a book page. Closest to print he'll meet elsewhere.
    "paper": Theme("paper", "#fdfaf3", "#2b2b2b", "#d62828", "#b8b2a7"),
    # Maximum contrast. The accessibility-safe default.
    "contrast": Theme("contrast", "#000000", "#ffffff", "#4cc9f0", "#4a4a4a"),
}


# ------------------------------------------------------------------- tts


class Voice:
    """Kokoro wrapper with on-disk caching, keyed by (text, voice, speed)."""

    def __init__(self, voice="af_heart", speed=1.0):
        from kokoro_onnx import Kokoro

        self.k = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
        self.voice = voice
        self.speed = speed
        self.cache = BUILD / "audio"
        self.cache.mkdir(parents=True, exist_ok=True)

    def say(self, text, speed=None, phonemes=False) -> np.ndarray:
        speed = self.speed if speed is None else speed
        key = hashlib.sha1(
            f"{text}|{self.voice}|{speed}|{phonemes}".encode()
        ).hexdigest()[:16]
        path = self.cache / f"{key}.wav"
        if path.exists():
            samples, _ = sf.read(path, dtype="float32")
        else:
            samples, sr = self.k.create(
                text, voice=self.voice, speed=speed, lang="en-us", is_phonemes=phonemes
            )
            assert sr == SR, f"unexpected sample rate {sr}"
            sf.write(path, samples, SR)
        # Isolated consonants come back with a schwa attached - strip it.
        if phonemes and len(text) == 1:
            samples = trim_schwa(samples, text)
        return samples


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype="float32")


# --------------------------------------------------------- schwa removal

# Kokoro appends a schwa to isolated consonants: asked for /s/ it produces
# "sss-uh", asked for /t/ it produces "tuh". Measured on af_heart, the tail is
# unmistakable - spectral centroid collapses from ~7000Hz to ~1400Hz while RMS
# *rises*. That is a vowel, and it is fatal here: "cuh-a-tuh" does not blend
# into "cat", and schwa-polluted consonants are the single most common reason
# home phonics fails. So we cut the tail off.

VOWELS = set("æɑɒɔəɜɛɪiʊuʌeaoyɐɘɵʏøœɞʉɨ")
SONORANTS = set("mnŋlrɹjwɫ")  # voiced+low-frequency; centroid test won't work


def _buckets(a, ms=25):
    n = int(SR * ms / 1000)
    for i in range(len(a) // n):
        w = a[i * n : (i + 1) * n]
        rms = float(np.sqrt(np.mean(w**2)))
        if rms < 0.01:
            yield i, n, rms, 0.0
            continue
        S = np.abs(np.fft.rfft(w * np.hanning(len(w))))
        f = np.fft.rfftfreq(len(w), 1 / SR)
        yield i, n, rms, float((S * f).sum() / max(S.sum(), 1e-9))


def _fade(a, ms=18):
    n = min(int(SR * ms / 1000), len(a))
    if n > 1:
        a = a.copy()
        a[-n:] *= np.linspace(1.0, 0.0, n, dtype="float32")
    return a


def trim_schwa(a: np.ndarray, ipa: str) -> np.ndarray:
    """Cut the trailing schwa from an isolated consonant clip."""
    if not a.size or ipa in VOWELS:
        return a  # a vowel is supposed to be a sustained vowel

    # Kokoro leaves leading near-silence (measured up to 400ms on /g/), which
    # would throw off every offset below. Cut to the real onset first.
    loud = np.where(np.abs(a) > 0.02)[0]
    if not loud.size:
        return a
    a = a[max(0, loud[0] - int(SR * 0.01)) :]

    b = list(_buckets(a))
    live = [x for x in b if x[2] >= 0.01]
    if not live:
        return a

    if ipa in SONORANTS:
        # /m/, /n/, /l/ are voiced and low-frequency, so the centroid test
        # can't separate them from the schwa. But they lead with the murmur
        # and decay into it - so keep the leading portion.
        cut = live[0][0] + 7  # ~175ms from onset
    else:
        # Obstruents: find the high-frequency burst/frication, then cut where
        # the centroid falls back into vowel territory.
        peak = max(live, key=lambda x: x[3])[0]
        cut = None
        run = 0
        for i, _, rms, cen in b:
            if i <= peak:
                continue
            run = run + 1 if (cen and cen < 2000 and rms > 0.02) else 0
            if run >= 2:
                cut = i - 1
                break
        # The centroid test misses cases where the schwa never dips below the
        # threshold (measured: /k/, /f/, /g/). No human can release a stop with
        # zero vocalic noise either - the teaching guidance is just "as short as
        # possible" - so fall back to a hard cap from the burst.
        cap = peak + (3 if ipa in "ptkbdg" else 6)  # stops 75ms, fricatives 150ms
        cut = cap if cut is None else min(cut, cap)

    end = min(max(cut, 2) * int(SR * 0.025), len(a))
    return _fade(a[:end])


# ------------------------------------------------------------ storyboard


@dataclass
class Segment:
    """One visual state held for the length of its audio plus a pause."""

    parts: list  # list of (text, is_highlighted)
    audio: np.ndarray
    pad: float = 0.0  # silence after, in seconds
    scale: float = 1.0  # relative font size
    color: str | None = None  # override theme fg

    @property
    def duration(self) -> float:
        return len(self.audio) / SR + self.pad


def whole(text, audio, pad=0.0, scale=1.0, color=None) -> Segment:
    """A segment showing `text` with no letter highlighted."""
    return Segment([(text, False)], audio, pad, scale, color)


# -------------------------------------------------------------- render


HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:1920px; height:1080px; overflow:hidden; }}
body {{
  background:{bg}; display:flex; align-items:center; justify-content:center;
  /* 5% TV safe area - older sets overscan and would clip the edges */
  padding:54px 96px;
}}
.word {{
  font-family:'Andika'; font-weight:{weight}; font-size:{size}px;
  color:{fg}; letter-spacing:0.04em; line-height:1.15;
  text-align:center; white-space:pre-wrap; word-break:break-word;
}}
.hl {{ color:{highlight}; }}
.dim {{ color:{dim}; }}
</style></head><body><div class="word">{spans}</div></body></html>"""


def _font_size(text: str, scale: float) -> int:
    """Fit to the 1728px safe width. Andika averages ~0.54em per glyph.

    Cap is 560px rather than the frame height: on a TV viewed from a sofa,
    bigger is better, and short words should fill the screen rather than
    float in the middle of it.
    """
    n = max(len(text), 1)
    if "\n" in text or n > 28:  # multi-line: fit the longest line
        longest = max(len(l) for l in text.split("\n"))
        return int(min(300, 1728 / (longest * 0.54)) * scale)
    return int(min(560, 1728 / (n * 0.54)) * scale)


def render_frame(seg: Segment, theme: Theme, out: Path):
    text = "".join(p for p, _ in seg.parts)
    spans = "".join(
        f'<span class="{"hl" if on else ("dim" if any(o for _, o in seg.parts) else "")}">'
        f"{html.escape(p)}</span>"
        for p, on in seg.parts
    )
    page = HTML.format(
        bg=theme.bg,
        fg=seg.color or theme.word_colors.get(text.strip(), theme.fg),
        highlight=theme.highlight,
        dim=theme.dim,
        weight=theme.weight,
        size=_font_size(text, seg.scale),
        spans=spans,
    )
    tmp = out.with_suffix(".html")
    tmp.write_text(page)
    subprocess.run(
        [
            "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
            "--hide-scrollbars", "--force-device-scale-factor=1",
            "--default-background-color=00000000",
            f"--screenshot={out}", "--window-size=1920,1080",
            f"file://{tmp}",
        ],
        check=True, capture_output=True,
    )
    tmp.unlink()


def build_video(segments: list, theme: Theme, out: Path, loop_pad=1.0):
    """Render segments to an mp4 with frame-accurate audio sync."""
    work = BUILD / f"frames-{out.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # One PNG per unique visual state - dedupe so repeats cost nothing.
    seen, concat, audio = {}, [], []
    for i, seg in enumerate(segments):
        sig = json.dumps([seg.parts, seg.scale, seg.color])
        if sig not in seen:
            png = work / f"f{len(seen):04d}.png"
            render_frame(seg, theme, png)
            seen[sig] = png
        concat.append((seen[sig], seg.duration))
        audio.append(seg.audio)
        if seg.pad:
            audio.append(silence(seg.pad))

    audio.append(silence(loop_pad))
    concat.append((concat[-1][0], loop_pad))

    wav = work / "audio.wav"
    sf.write(wav, np.concatenate(audio), SR)

    lst = work / "list.txt"
    lines = [f"file '{p.name}'\nduration {d:.4f}" for p, d in concat]
    lines.append(f"file '{concat[-1][0].name}'")  # concat demuxer needs the last repeated
    lst.write_text("\n".join(lines) + "\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-i", str(wav),
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", "30", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
            "-movflags", "+faststart", "-shortest", str(out),
        ],
        check=True,
    )
    return out
