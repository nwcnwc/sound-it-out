"""JSON-lines sidecar. Electron's only way into the Python pipeline.

Protocol: one JSON object per line, both directions.

    -> {"id": 1, "method": "capabilities", "params": {}}
    <- {"id": 1, "ok": true, "result": {...}}
    <- {"event": "progress", "jobId": "...", "stage": "audio", "done": 3, "total": 40}

Frame rendering is deliberately NOT done here. `plan` returns a job directory
containing frames.json; Electron rasterises those with its own Chromium and
then calls `encode`. That keeps the one browser-dependent step on the side
that already ships a browser, so the packaged app needs no external Chrome.

Run standalone for debugging:  .venv/bin/python -m gen.service
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from gen.paths import JOBS, ensure_user_files  # noqa: E402


def _emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _progress(job_id, stage, done, total, message=""):
    _emit({"event": "progress", "jobId": job_id, "stage": stage,
           "done": done, "total": total, "message": message})


# ---------------------------------------------------------------- methods


def m_capabilities(_params):
    from gen.voice import VoiceSource
    from gen.levels import level_status

    caps = VoiceSource.capabilities()
    return {"capabilities": caps, "levels": level_status(caps)}


def m_wordlist_load(_params):
    from gen import wordlists

    path = wordlists.WORDLISTS / "sight-words.txt"
    groups = wordlists.load(path)
    return {
        "text": path.read_text(encoding="utf-8"),
        "groups": [
            {"name": g.name, "words": [{"word": w, "color": c} for w, c in g.words]}
            for g in groups
        ],
    }


def m_wordlist_save(params):
    from gen import wordlists

    path = wordlists.WORDLISTS / "sight-words.txt"
    text = params["text"]
    # Parse before writing: a file that cannot be parsed would silently empty
    # every level that depends on it.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        groups = wordlists.load(tmp)
        if not groups:
            raise ValueError("No words found - every line was blank or a comment.")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"Could not read that word list: {e}") from e
    tmp.replace(path)
    return {
        "groups": [
            {"name": g.name, "words": [{"word": w, "color": c} for w, c in g.words]}
            for g in groups
        ]
    }


def m_plan(params):
    """Build audio and the storyboard. Returns a job dir for Electron to render."""
    from gen import levels
    from gen.soundout import THEMES, Theme, plan_job
    from gen.voice import VoiceSource

    job_id = str(params["jobId"])
    work = JOBS / job_id
    level = int(params.get("level", 1))
    opts = dict(params.get("options") or {})

    _progress(job_id, "audio", 0, 1, "Working out the sounds...")
    voice = VoiceSource(clone_profile=params.get("cloneProfile"))
    segments = levels.build(level, voice, opts)

    # Repeat the material to fill the requested running time. The video loops
    # anyway, but a longer file means fewer restarts on a TV's own player.
    minutes = float(opts.get("minutes") or 0)
    if minutes > 0 and segments:
        one = sum(s.duration for s in segments)
        if one > 0:
            segments = segments * max(1, int((minutes * 60) // one))

    base = THEMES.get(params.get("theme", "night"), THEMES["night"])
    colors = {w: c for g in _groups() for w, c in g.words if c}
    theme = Theme(base.name, base.bg, base.fg, base.highlight, base.dim,
                  base.weight, colors)

    _progress(job_id, "planning", 0, 1, "Preparing the frames...")
    plan = plan_job(segments, theme, work)
    plan.update({"jobDir": str(work), "voice": voice.summary()})
    return plan


def _groups():
    from gen import wordlists

    try:
        return wordlists.load()
    except Exception:
        return []


def m_encode(params):
    """Mux the frames Electron rendered into an mp4."""
    from gen.soundout import encode_job

    job_id = str(params["jobId"])
    work = JOBS / job_id
    out = Path(params["output"]).expanduser()
    _progress(job_id, "encoding", 0, 1, "Making the video file...")
    encode_job(
        work, out,
        progress=lambda d, t: _progress(
            job_id, "encoding", round(d, 1), round(t, 1), "Making the video file..."
        ),
    )
    return {"output": str(out)}


def m_render_chrome(params):
    """Fallback renderer for development, when Electron is not driving."""
    from gen.soundout import render_job_chrome

    job_id = str(params["jobId"])
    work = JOBS / job_id
    render_job_chrome(
        work, progress=lambda d, t: _progress(job_id, "frames", d, t, "Drawing...")
    )
    return {"ok": True}


def m_install_cloning(params):
    from gen import clone

    return clone.install(
        progress_cb=lambda d, t, msg="": _emit(
            {"event": "installProgress", "done": d, "total": t, "message": msg}
        )
    )


def m_ping(_params):
    return {"pong": True}


METHODS = {
    "ping": m_ping,
    "capabilities": m_capabilities,
    "wordlist.load": m_wordlist_load,
    "wordlist.save": m_wordlist_save,
    "plan": m_plan,
    "encode": m_encode,
    "render.chrome": m_render_chrome,
    "cloning.install": m_install_cloning,
}


def handle(msg):
    mid = msg.get("id")
    method = msg.get("method")
    fn = METHODS.get(method)
    if fn is None:
        return {"id": mid, "ok": False, "error": f"Unknown method: {method}"}
    try:
        return {"id": mid, "ok": True, "result": fn(msg.get("params") or {})}
    except Exception as e:
        # The UI shows `error` to a non-technical user, so keep it a sentence;
        # `detail` carries the traceback for the log.
        return {"id": mid, "ok": False, "error": str(e) or e.__class__.__name__,
                "detail": traceback.format_exc()}


def main():
    ensure_user_files()
    _emit({"event": "ready", "pid": None})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _emit({"event": "error", "message": "malformed request"})
            continue
        if msg.get("method") == "shutdown":
            _emit({"id": msg.get("id"), "ok": True, "result": {}})
            break
        _emit(handle(msg))


if __name__ == "__main__":
    main()
