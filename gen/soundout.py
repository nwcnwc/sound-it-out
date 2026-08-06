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

from gen.paths import AUDIO_CACHE, BUILD, MODELS, RESOURCES  # noqa: E402

ROOT = RESOURCES
SAMPLES = RESOURCES / "samples"
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
        self.cache = AUDIO_CACHE
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
        return samples

    def phoneme(self, ipa: str) -> np.ndarray:
        """A single sound, schwa-free and long enough to teach with."""
        # Get as much length as Kokoro will give natively before stretching:
        # a 6x time-stretch sounds processed, a 1.5x one does not. Repeating
        # the symbol makes the model hold the sound rather than release it.
        if ipa in STOPS:
            src = ipa  # a stop cannot be held; repeating just gives "t-t-t"
        elif ipa in VOWELS:
            src = ipa + "ː"  # IPA length mark
        else:
            src = ipa * 6
        return shape_phoneme(self.say(src, phonemes=True), ipa)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), dtype="float32")


def slower(a: np.ndarray, tempo: float) -> np.ndarray:
    """Slow speech down without raising the pitch. tempo 0.7 = 30% slower.

    Kokoro's own `speed` bottoms out at 0.5 and degrades before it gets there,
    so real slowing happens here instead.
    """
    return _stretch(a, int(len(a) / tempo))


# ------------------------------------------------------ phoneme shaping

# Two constraints pull against each other, and the balance matters more than
# either one alone:
#
#   1. Kokoro appends a schwa to isolated consonants ("sss-uh", "tuh"). Left
#      in, "cuh-a-tuh" never blends into "cat".
#   2. A sound that is merely *short* is useless for teaching. Phonics
#      instruction stretches sounds out - "ssssss", "mmmmm" - so the child can
#      hear each one and join them. A clipped 75ms /t/ is technically
#      schwa-free and pedagogically dead.
#
# The first pass over-corrected for (1) and broke (2). So: cut the schwa, then
# *sustain* what remains by looping its steady state, the way a sampler holds a
# note. Fricatives, nasals and vowels all have a genuine steady state, so they
# stretch cleanly to any length.
#
# Stop consonants (p t k b d g) are the exception, and no amount of engineering
# fixes them: a stop is defined by a closure and a release, with no sustainable
# phase in between. No human teacher can hold a /t/ either - the standard
# guidance is just "keep it crisp". They keep their fullest natural release.

VOWELS = set("æɑɒɔəɜɛɪiʊuʌeaoyɐɘɵʏøœɞʉɨ")
STOPS = set("ptkbdgʔ") | {"\u0261"}  # espeak emits U+0261 script g, not ASCII g
SONORANTS = set("mnŋlrɹjwɫ")  # voiced+low-frequency; centroid test won't work

SUSTAIN_VOWEL = 0.80   # seconds
SUSTAIN_CONS = 0.68
STOP_MAX = 0.30


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


def _xfade(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    """Join two clips with an equal-power crossfade, to avoid a seam click."""
    n = min(n, len(a), len(b))
    if n < 2:
        return np.concatenate([a, b])
    r = np.linspace(0.0, 1.0, n, dtype="float32")
    mid = a[-n:] * np.cos(r * np.pi / 2) + b[:n] * np.sin(r * np.pi / 2)
    return np.concatenate([a[:-n], mid, b[n:]])


def _stretch(a: np.ndarray, target: int) -> np.ndarray:
    """Time-stretch to `target` samples, preserving pitch and formants.

    Looping a short core with crossfades (the first attempt) repeats the same
    100ms of waveform over and over, and the ear hears that periodicity as a
    hard robotic stutter. Rubberband is a phase vocoder - it stretches the
    sound continuously instead of repeating it, so there is no period to hear.
    """
    if len(a) < int(SR * 0.03) or target <= 0:
        return a
    tempo = len(a) / target  # <1 slows down
    if abs(tempo - 1.0) < 0.03:
        return a
    tempo = max(tempo, 0.05)  # rubberband's floor
    src = BUILD / "_st_in.wav"
    dst = BUILD / "_st_out.wav"
    sf.write(src, a, SR)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-filter:a", f"rubberband=tempo={tempo:.5f}:formant=preserved:pitchq=quality",
         str(dst)],
        check=True,
    )
    out, _ = sf.read(dst, dtype="float32")
    return out


def tidy_word(a: np.ndarray, gap_ms=45, drop_gap_ms=130) -> np.ndarray:
    """Clean up a synthesised single word.

    Kokoro is trained on connected speech, and given a bare word it detaches
    the onset: measured, "Skye" comes out as /s/ + a silent gap + "kye", which
    is heard as "e-Skye". "Rubble" does the same with its /r/. Adding
    punctuation does not help - tested bare, with a period, and inside a
    carrier, and the gap survives all three.

    Two conservative repairs, in order of how safe they are:

      1. Compress internal silence. This removes no speech at all - it only
         shortens the gaps - so it cannot damage a correctly-spoken word.
      2. Drop a trailing fragment separated by a long gap and much quieter
         than the body. "pup" gains a detached vocalic release that is heard
         as "puppy"; a real word does not have a quiet island after a long
         silence.

    Only ever applied to GENERATED audio. Her recordings are used verbatim -
    see gen/voice.py - so none of this touches the voice Alex actually hears
    at levels 1-5.
    """
    if a.size < int(SR * 0.05):
        return a
    n = int(SR * 0.02)
    e = [float(np.sqrt(np.mean(a[i * n:(i + 1) * n] ** 2))) for i in range(len(a) // n)]
    if not e:
        return a
    mx = max(e) or 1.0
    on = [x / mx > 0.08 for x in e]
    if not any(on):
        return a

    first, last = on.index(True), len(on) - 1 - on[::-1].index(True)

    # (2) a quiet, detached tail is an artefact, not part of the word
    i = last
    while i > first:
        if on[i]:
            j = i
            while j > first and on[j]:
                j -= 1
            run_peak = max(e[j + 1:i + 1], default=0)
            silence_before = 0
            k = j
            while k > first and not on[k]:
                silence_before += 1
                k -= 1
            if (silence_before * 20 >= drop_gap_ms and run_peak < mx * 0.45
                    and k > first):
                last = k
                i = k
                continue
            break
        i -= 1

    # (1) compress internal silence. Indices are kept in the ORIGINAL bucket
    # space - slicing a `body` array first and then indexing it with the
    # unshifted map misaligns every segment by one bucket.
    lo = max(0, first - 1)
    hi = min(len(on) - 1, last + 1)
    out, run = [], 0
    limit = max(1, int(gap_ms / 20))
    for idx in range(lo, hi + 1):
        seg = a[idx * n:(idx + 1) * n]
        if on[idx]:
            run = 0
            out.append(seg)
        else:
            run += 1
            if run <= limit:
                out.append(seg)
    return np.concatenate(out) if out else a


def _longest_burst(a: np.ndarray, thresh=0.30) -> np.ndarray:
    """Return the longest continuously-voiced stretch of a clip.

    Asking Kokoro for `ssssss` does NOT give one held /s/ - measured, it gives
    two discrete re-articulated bursts with a dip between them. Stretching
    across that dip is exactly what produced the robotic stutter. So take the
    single longest continuous articulation and throw the rest away.
    """
    b = list(_buckets(a, ms=20))
    if not b:
        return a
    mx = max(x[2] for x in b) or 1.0
    on = [x[2] / mx > thresh for x in b]
    best = run = None
    for i, v in enumerate(on + [False]):
        if v and run is None:
            run = i
        elif not v and run is not None:
            if best is None or i - run > best[1] - best[0]:
                best = (run, i)
            run = None
    if best is None:
        return a
    n = int(SR * 0.020)
    return a[best[0] * n : min(len(a), best[1] * n)]


def shape_phoneme(a: np.ndarray, ipa: str) -> np.ndarray:
    """Strip the schwa, then stretch the sound out so it can be taught with."""
    if not a.size:
        return a
    if ipa not in STOPS:
        a = _longest_burst(a)

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
    bs = int(SR * 0.025)

    if ipa in STOPS:
        # Unsustainable by nature. Keep the natural release - crisp, but not
        # so clipped it stops sounding like the letter at all.
        return _fade(a[: min(len(a), int(SR * STOP_MAX))], 30)

    if ipa in VOWELS:
        region = a
    elif ipa in SONORANTS:
        # Voiced and low-frequency, so the centroid test can't separate them
        # from the schwa - but they lead with the murmur and the schwa only
        # appears on release, so keep everything but the tail.
        region = a[: max(len(a) - int(SR * 0.18), min(len(a), (live[0][0] + 8) * bs))]
    else:
        # Fricatives: keep the high-centroid frication and drop the tail where
        # the centroid falls back into vowel territory. That *is* the schwa.
        peak = max(live, key=lambda x: x[3])[0]
        end = len(b)
        for i, _, rms, cen in b:
            if i > peak and cen and cen < 2200 and rms > 0.02:
                end = i
                break
        region = a[: min(len(a), max(end, peak + 2) * bs)]

    target = int(SR * (SUSTAIN_VOWEL if ipa in VOWELS else SUSTAIN_CONS))
    return _fade(_stretch(region, target), 60)


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


# A word must NEVER break mid-word - "Chas / e" is worse than useless to a
# child learning to recognise word shapes. Estimating glyph widths got this
# wrong (Andika is wider than it looks), so the page measures itself instead:
# binary-search the largest font size that actually fits, in the browser that
# is actually rendering it. `white-space:nowrap` makes overflow measurable
# rather than silently wrapping.
HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:1920px; height:1080px; overflow:hidden; background:__BG__; }
/* 5% TV safe area - older sets overscan and would clip the edges */
#stage { position:absolute; left:96px; top:54px; width:1728px; height:972px;
         display:flex; align-items:center; justify-content:center; }
#word  { font-family:'Andika',sans-serif; font-weight:__WEIGHT__; color:__FG__;
         letter-spacing:0.04em; line-height:1.15; text-align:center;
         white-space:__WRAP__; overflow-wrap:normal; word-break:keep-all; }
.hl { color:__HL__; }
.dim { color:__DIM__; }
</style></head><body>
<div id="stage"><div id="word">__SPANS__</div></div>
<script>
// Exposed so it can be re-run once webfonts have loaded. Fonts arrive
// asynchronously; measuring before they land sizes against a fallback font
// and every frame comes out wrong.
window.__refit = function () {
  var s = document.getElementById('stage'), w = document.getElementById('word');
  var lo = 16, hi = __MAX__;
  while (hi - lo > 1) {
    var m = (lo + hi) >> 1;
    w.style.fontSize = m + 'px';
    if (w.scrollWidth <= s.clientWidth && w.scrollHeight <= s.clientHeight) lo = m;
    else hi = m;
  }
  w.style.fontSize = Math.floor(lo * __SCALE__) + 'px';
  document.title = 'fit' + lo;
  return lo;
};
window.__refit();
if (document.fonts && document.fonts.ready) document.fonts.ready.then(window.__refit);
</script></body></html>"""


def frame_html(seg: Segment, theme: Theme) -> str:
    """The complete HTML for one visual state.

    Kept separate from any browser invocation so the same markup can be
    rendered by external Chrome (CLI) or by Electron's own Chromium (app).
    Identical HTML in identical Chromium means identical pixels.
    """
    text = "".join(p for p, _ in seg.parts)
    spans = "".join(
        f'<span class="{"hl" if on else ("dim" if any(o for _, o in seg.parts) else "")}">'
        f"{html.escape(p)}</span>"
        for p, on in seg.parts
    )
    # Multi-word text may wrap between words; a single word never may.
    wrap = "normal" if " " in text.strip() else "nowrap"
    return (
        HTML.replace("__BG__", theme.bg)
        .replace("__FG__", seg.color or theme.word_colors.get(text.strip(), theme.fg))
        .replace("__HL__", theme.highlight)
        .replace("__DIM__", theme.dim)
        .replace("__WEIGHT__", str(theme.weight))
        .replace("__WRAP__", wrap)
        .replace("__MAX__", "560")
        .replace("__SCALE__", str(seg.scale))
        .replace("__SPANS__", spans)
    )


def render_frame(seg: Segment, theme: Theme, out: Path):
    """Render one visual state to PNG using external Chrome (CLI path only).

    The packaged app does not use this - Electron renders the same HTML with
    its own bundled Chromium, so there is no external Chrome dependency.
    """
    tmp = out.with_suffix(".html")
    tmp.write_text(frame_html(seg, theme))
    subprocess.run(
        [
            "google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
            "--hide-scrollbars", "--force-device-scale-factor=1",
            # let the fit script run to completion before the frame is captured
            "--virtual-time-budget=4000",
            f"--screenshot={out}", "--window-size=1920,1080",
            f"file://{tmp}",
        ],
        check=True, capture_output=True,
    )
    tmp.unlink()


# Video building is split into three phases so that the middle one - turning
# HTML into PNGs - can be done either by external Chrome (CLI/dev) or by
# Electron's own Chromium (packaged app), without the other two caring.
#
#   plan_job()   storyboard: unique frames, timing, audio.  No browser.
#   <render>     frames.json -> frames/<id>.png             Either renderer.
#   encode_job() frames + audio -> mp4                      No browser.


def plan_job(segments: list, theme: Theme, work: Path, loop_pad=1.0) -> dict:
    """Compute the storyboard and write audio. Renders nothing."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # One frame per unique visual state - dedupe so repeats cost nothing.
    # A 20 minute video is a few hundred PNGs, not 36,000.
    seen, timeline, audio = {}, [], []
    for seg in segments:
        sig = json.dumps([seg.parts, seg.scale, seg.color])
        if sig not in seen:
            seen[sig] = (f"f{len(seen):04d}", frame_html(seg, theme))
        timeline.append({"frame": seen[sig][0], "duration": round(seg.duration, 4)})
        audio.append(seg.audio)
        if seg.pad:
            audio.append(silence(seg.pad))

    audio.append(silence(loop_pad))
    timeline.append({"frame": timeline[-1]["frame"], "duration": loop_pad})

    frames = [{"id": fid, "html": h} for fid, h in seen.values()]
    (work / "frames.json").write_text(json.dumps(frames))
    sf.write(work / "audio.wav", np.concatenate(audio), SR)
    plan = {"timeline": timeline, "frame_count": len(frames),
            "duration": round(sum(t["duration"] for t in timeline), 3)}
    (work / "plan.json").write_text(json.dumps(plan))
    return plan


def render_job_chrome(work: Path, progress=None):
    """Render frames.json with external Chrome. Development path only."""
    frames = json.loads((work / "frames.json").read_text())
    out = work / "frames"
    out.mkdir(exist_ok=True)
    for i, f in enumerate(frames):
        page = out / f"{f['id']}.html"
        page.write_text(f["html"])
        subprocess.run(
            ["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", "--force-device-scale-factor=1",
             "--virtual-time-budget=4000",
             f"--screenshot={out / (f['id'] + '.png')}",
             "--window-size=1920,1080", f"file://{page}"],
            check=True, capture_output=True,
        )
        page.unlink()
        if progress:
            progress(i + 1, len(frames))


def encode_job(work: Path, out: Path, progress=None) -> Path:
    """Mux rendered frames and audio into a TV-playable mp4.

    Encoding is by far the longest phase, so it reports real progress: ffmpeg's
    own `-progress` stream is parsed against the known total duration. Without
    it the UI showed a bar that filled during frame rendering, reset to zero,
    and then sat there for minutes looking hung.

    Preset is `veryfast` with `-tune stillimage`, not the usual `medium`. The
    content is a handful of static images held for seconds at a time - there is
    essentially no motion to estimate, so a slower preset buys nothing but
    minutes of CPU. Measured on a 4-core i3, `medium` took several minutes for
    a 4 minute video.
    """
    # The concat demuxer resolves relative entries against the list file's own
    # directory, so a relative `work` silently produces doubled paths. Absolute
    # from here on.
    work = work.resolve()
    plan = json.loads((work / "plan.json").read_text())
    frames = work / "frames"
    missing = [t["frame"] for t in plan["timeline"]
               if not (frames / f"{t['frame']}.png").exists()]
    if missing:
        raise FileNotFoundError(
            f"{len(set(missing))} frames were never rendered, e.g. {missing[0]}"
        )

    lines = []
    for t in plan["timeline"]:
        lines.append(f"file '{frames / (t['frame'] + '.png')}'")
        lines.append(f"duration {t['duration']:.4f}")
    # The concat demuxer drops the final entry's duration unless it is repeated.
    lines.append(f"file '{frames / (plan['timeline'][-1]['frame'] + '.png')}'")
    lst = work / "list.txt"
    lst.write_text("\n".join(lines) + "\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    total = float(plan.get("duration") or 0)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(lst),
        "-i", str(work / "audio.wav"),
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        # 15fps, not 30. The picture is static text that changes a few times a
        # minute, so half the frames are pure duplication - and encoding cost
        # scales with frame count, which is the actual bottleneck here (a 4-core
        # i3 managed only 1.1x realtime at 30fps). 15fps is a long-standing
        # standard rate that TV built-in players handle without complaint.
        # Raise it if any player ever objects; nothing else depends on it.
        "-r", "15", "-preset", "veryfast", "-tune", "stillimage", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest",
        "-progress", "pipe:1", "-nostats", str(out),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    try:
        for line in proc.stdout:
            if progress and total > 0 and line.startswith("out_time_us="):
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue  # ffmpeg emits "N/A" before the first frame lands
                progress(min(done, total), total)
    finally:
        proc.stdout.close()
        err = proc.stderr.read()
        proc.stderr.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()[-400:]}")
    if progress and total > 0:
        progress(total, total)
    return out


def build_video(segments: list, theme: Theme, out: Path, loop_pad=1.0):
    """Plan, render (external Chrome) and encode in one go. CLI convenience."""
    work = BUILD / f"frames-{out.stem}"
    plan_job(segments, theme, work, loop_pad)
    render_job_chrome(work)
    return encode_job(work, out)
