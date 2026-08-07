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

    minutes = float(opts.get("minutes") or 0)

    # Level 6 is a journey, not a playlist: it travels from single letters to a
    # sentence, so filling 30 minutes by playing a 7 minute arc four times is
    # the wrong shape. Stretch the arc instead, by repeating each item more.
    # ~3.3 min per repetition, measured across all four chapters; approximate,
    # because real recordings will not be the same length as the built-in voice.
    if level == 6 and minutes > 0:
        opts = dict(opts, reps=max(2, min(14, round(minutes / 3.3))))

    _progress(job_id, "audio", 0, 1, "Working out the sounds...")
    voice = VoiceSource(clone_profile=params.get("cloneProfile"))
    segments = levels.build(level, voice, opts)

    # Every other level is a playlist of independent items, so repeat the whole
    # thing to fill the running time. The video loops anyway, but a longer file
    # means fewer restarts on a TV's own player.
    if minutes > 0 and segments and level != 6:
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


def m_recordings_import(params):
    """Split one long recording into clips, check them, and save.

    The pipeline existed from early on but had no way in from the app, so the
    only way to use it was a terminal - which defeats the point, since the
    person doing the recording is not a developer.
    """
    from gen import recordings as R

    src = Path(params["path"]).expanduser()
    part = params.get("part", "words")
    if not src.exists():
        raise ValueError(f"Can't find that file: {src}")

    _progress("import", "reading", 0, 1, "Listening to the recording...")

    if part == "passage":
        issues, notes, out = R.check_passage(src, None, params.get("dryRun", False))
        return {
            "part": part,
            "saved": 0,
            "outdir": str(out) if out else None,
            "issues": [{"label": i.label, "severity": i.severity,
                        "message": i.message} for i in issues],
            "notes": list(notes),
            "report": R.format_report(part, None, issues, src, out, extra=notes),
        }

    labels = (R.phoneme_labels(params.get("order", "rows")) if part == "phonemes"
              else R.word_labels())
    _progress("import", "splitting", 0, 1, "Finding each item...")
    al = R.split_recording(src, labels, min_silence=float(
        params.get("minSilence", R.MIN_SILENCE)))

    _progress("import", "checking", 0, 1, "Checking the sounds...")
    issues = list(al.health) + R.quality_report(al.clips, part=part)

    written = []
    if not params.get("dryRun"):
        outdir = R.default_outdir(part)
        written = R.save_clips(al.clips, outdir, source=src, issues=issues,
                               review=al.review, part=part)
    else:
        outdir = None

    return {
        "part": part,
        "found": len(al.clips),
        "expected": len(labels),
        "saved": len(written),
        "outdir": str(outdir) if outdir else None,
        "issues": [{"label": i.label, "severity": i.severity,
                    "message": i.message} for i in issues],
        "report": R.format_report(part, al, issues, src, outdir),
    }


def m_studio_plan(params):
    from gen import studio

    items = studio.plan(params.get("part", "phonemes"), params.get("order", "rows"))
    dicts = [i.as_dict() for i in items]
    done = sum(1 for d in dicts if d["done"])
    # Where to pick up: the first thing not yet recorded. A busy parent does
    # this over several sittings, so resuming has to be the default rather
    # than something to go looking for.
    resume = next((n for n, d in enumerate(dicts) if not d["done"]), len(dicts))
    return {"part": params.get("part", "phonemes"),
            "takes": studio.TAKES_DEFAULT,
            "items": dicts, "done": done, "total": len(dicts), "resumeAt": resume}


def m_studio_submit(params):
    """Score the takes for one item, keep the best, and say why."""
    from gen import studio

    it = params["item"]
    item = studio.Item(key=it["key"], kind=it["kind"], display=it["display"],
                       say=it.get("say", ""), length=it.get("length", "free"),
                       ipa=it.get("ipa", ""))
    sr = int(params.get("sampleRate", 48000))
    takes = [studio.decode(t, sr) for t in params.get("takes", [])]
    if not takes:
        raise ValueError("No audio was received.")

    result = studio.choose(takes, item)
    saved = None
    if result["audio"] is not None and not params.get("dryRun"):
        saved = studio.save(item, result["audio"])
    return {"key": item.key, "best": result["best"], "takes": result["takes"],
            "reason": result["reason"], "allFailed": result["allFailed"],
            "saved": saved}


def m_passage_text(_params):
    """The passage itself, so it can be read from the screen."""
    from gen.paths import RESOURCES

    raw = (RESOURCES / "PASSAGE.md").read_text(encoding="utf-8")
    body = raw.split("## One", 1)[-1]
    return {"markdown": "## One" + body}


def m_studio_passage(params):
    """Save a passage recorded in the app, then check it as an import would."""
    import soundfile as sf
    from gen import recordings as R
    from gen import studio
    from gen.paths import VOICE_DIR

    audio = studio.decode(params["audio"], int(params.get("sampleRate", 48000)))
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    dest = VOICE_DIR / "passage.wav"
    sf.write(dest, audio.astype("float32"), studio.SR)

    issues, notes, _ = R.check_passage(dest, None, dry_run=True)
    return {
        "path": str(dest),
        "seconds": round(len(audio) / studio.SR, 1),
        "issues": [{"label": i.label, "severity": i.severity, "message": i.message}
                   for i in issues],
        "notes": list(notes),
    }


def m_studio_clip(params):
    from gen import studio

    return {"path": studio.clip_path(params.get("part", "phonemes"),
                                     params["key"],
                                     params.get("order", "rows"))}


def m_studio_remove(params):
    from gen import studio

    keys = params.get("keys")
    n = studio.remove(params.get("part", "phonemes"), keys,
                      params.get("order", "rows"))
    return {"removed": n}


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
    "recordings.import": m_recordings_import,
    "studio.plan": m_studio_plan,
    "studio.submit": m_studio_submit,
    "studio.clip": m_studio_clip,
    "studio.passage": m_studio_passage,
    "passage.text": m_passage_text,
    "studio.remove": m_studio_remove,
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
