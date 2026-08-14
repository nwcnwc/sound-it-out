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


def m_sightwords_load(_params):
    from gen import sightwords

    text = sightwords.load_text()
    return {"text": text, "words": sightwords.parse(text)}


def m_sightwords_save(params):
    from gen import sightwords

    words = sightwords.save(params.get("text", ""))
    return {"text": sightwords.load_text(), "words": words}


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
    # sentence, so filling 30 minutes by playing the arc four times over is
    # the wrong shape. Stretch the arc instead, by repeating each item more.
    # Measured at ~11 min for the whole journey at reps=2 and ~10.5 min per
    # extra rep (approximate - real recordings are not the same length as the
    # built-in voice). Requests shorter than the journey rely on the trim
    # below, which ends the video after a whole chapter.
    if level == 6 and minutes > 0:
        opts = dict(opts, reps=max(2, min(14, round(minutes / 10.5) + 1)))

    _progress(job_id, "audio", 0, 1, "Working out the sounds...")
    # Per-video choices. Defaults keep the old behaviour, so a request that
    # says nothing gets what it always got.
    voice = VoiceSource(
        clone_profile=params.get("cloneProfile"),
        use_magic_e=opts.get("useMagicE", True),
        use_joins=opts.get("useJoins", True),
    )
    segments = levels.build(level, voice, opts)

    # Fit the running time that was actually asked for, in both directions.
    #
    # Repeating fills a short pass: the video loops anyway, but a longer file
    # means fewer restarts on a TV's own player. Trimming handles the opposite
    # case, which used to be silently ignored - `//` rounds down to a floor of
    # one whole pass, so a 5 minute request on a level whose single pass runs
    # 9 minutes came out 9 minutes long. Level 6 is never repeated (it is a
    # journey, not a playlist - reps above stretch it instead) but it is
    # trimmed: its items are whole chapters, so a short video ends after a
    # chapter's sentence rather than mid-story.
    if minutes > 0 and segments:
        target = minutes * 60
        one = sum(s.duration for s in segments)
        if one > target:
            segments = _whole_items_upto(segments, target)
        elif one > 0 and level != 6:
            # Whole passes, then whole items from the start of another pass
            # to cover the remainder - repeating passes alone left a 5 minute
            # request at 3.6 when the pass ran 1.8. The video loops anyway,
            # so a partial final pass is just the loop arriving early.
            n = int(target // one)
            extra = _whole_items_upto(segments, target - n * one, allow_empty=True)
            segments = segments * n + extra

    # Per-word colors are a fossil of the Words-tab era (Chase in his kit
    # blue), and they break the one color rule that matters now: the
    # highlight means "being said" and everything else is neutral. A word
    # whose BASE color resembles the highlight - Chase's blue against the
    # blue highlight of the contrast theme - makes the sweep invisible.
    base = THEMES.get(params.get("theme", "night"), THEMES["night"])
    theme = Theme(base.name, base.bg, base.fg, base.highlight, base.dim,
                  base.weight)

    _progress(job_id, "planning", 0, 1, "Preparing the frames...")
    plan = plan_job(segments, theme, work)
    plan.update({"jobDir": str(work), "voice": voice.summary()})
    return plan


def _whole_items_upto(segments, target, allow_empty=False):
    """Trim a segment list to `target` seconds, cutting only at item ends.

    Items stay in curriculum order and nothing is skipped - the list just
    stops at the item boundary nearest the target, which may be slightly over
    it. Cutting mid-item would end the video with a word half sounded out,
    which teaches the wrong thing. Unless `allow_empty`, the first item is
    always kept whole, so a request shorter than a single item still produces
    a video.
    """
    out, item, total = [], [], 0.0
    for seg in segments:
        item.append(seg)
        if seg.item_end:
            dur = sum(s.duration for s in item)
            if (out or allow_empty) and total + dur > target:
                # Overrunning by less than we would fall short lands closer
                # to what was asked for, so the boundary item stays in.
                if (total + dur - target) < (target - total):
                    out += item
                break
            out += item
            total += dur
            item = []
    return out if (out or allow_empty) else segments


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


def m_cloning_info(_params):
    """What the download needs, and whether this computer can take it.

    Asked before the button is pressed. Finding out you are 2 GB short after
    committing to a 3 GB download is a bad way to learn it, and the check
    itself is instant.
    """
    from gen import clone

    try:
        return clone.capabilities()
    except Exception as e:
        return {"available": False, "reason": str(e), "enough_space": None}


def m_install_cloning(params):
    from gen import clone

    # clone.install calls back with (fraction, message) - a float 0..1 and a
    # line of text. The adapter here used to declare (done, total, msg), so the
    # message was bound to `total` and the renderer computed done/total as
    # 0.02 / "Creating the voice-model environment" = NaN. The progress bar got
    # `width: NaN%` and the status line never moved off "Downloading...", which
    # made a working 3 GB download look like a hung one for its entire run.
    return clone.install(
        progress_cb=lambda frac, msg="": _emit({
            "event": "installProgress",
            "done": round(max(0.0, min(1.0, float(frac))) * 100),
            "total": 100,
            "message": str(msg),
        })
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


def m_sentences_list(_params):
    from gen import sentences

    return {"sentences": sentences.status()}


def m_sentences_add(params):
    from gen import sentences

    sentences.add(params.get("text", ""))
    return {"sentences": sentences.status()}


def m_sentences_remove(params):
    from gen import sentences

    sentences.remove(params["key"])
    return {"sentences": sentences.status()}


def m_sentences_estimate(params):
    from gen import sentences

    s = sentences.estimate_seconds(
        keys=params.get("sentences"),
        reps=int(params.get("reps", 3)),
        pause=float(params.get("pauseSeconds", 1.5)),
    )
    return {"seconds": round(s, 1)}


def m_sentences_clips(params):
    from gen import sentences

    return {"clips": sentences.clips(params["key"])}


def m_packs_list(_params):
    from gen import sentences

    return {"packs": sentences.packs()}


def m_packs_add(params):
    from gen import sentences

    sentences.add_pack(params["id"])
    return {"sentences": sentences.status(), "packs": sentences.packs()}


def m_studio_plan(params):
    from gen import studio

    # The sentence walk-through: the words of ONE sentence, then its whole
    # line. Words already in the shared bank show as done and are resumed
    # past, so each sentence she adds is cheaper to record than the last.
    if params.get("part") == "sentence":
        from gen import sentences

        items = sentences.walkthrough_items(params["key"])
        # `only` narrows the walk-through to one item - the redo path from
        # the listen-back panel. Recorded-or-not, it starts at the top.
        only = params.get("only")
        if only is not None:
            items = [i for i in items if i.key == only]
            dicts = [i.as_dict() for i in items]
            return {"part": "sentence", "takes": 1, "items": dicts,
                    "done": 0, "total": len(dicts), "resumeAt": 0,
                    "redo": True}
        dicts = [i.as_dict() for i in items]
        done = sum(1 for d in dicts if d["done"])
        resume = next((n for n, d in enumerate(dicts) if not d["done"]), len(dicts))
        return {"part": "sentence", "takes": 1, "items": dicts,
                "done": done, "total": len(dicts), "resumeAt": resume}

    # Everything the packs still need, as ONE session: each missing word,
    # then each unread line, auto-advancing and resumable. Recording them
    # sentence by sentence works too, but is thirty-nine open-and-close
    # cycles; this is one sitting.
    if params.get("part") == "starter":
        from gen import sentences, starter

        words, lines = starter.needed()
        items = [sentences._word_item(w) for w in words]
        items += [sentences._line_item(t) for t in lines]
        # Gaps only: recorded items are interleaved through the pack order,
        # and a gap-filling session that asks for them again is not faster
        # than anything.
        dicts = [i.as_dict() for i in items if not i.done()]
        return {"part": "starter", "takes": 1, "items": dicts,
                "done": 0, "total": len(dicts), "resumeAt": 0}

    # The word bank: what is actually on disk, for listening back and
    # re-recording. `keys` narrows to a chosen few - the redo path - and a
    # redo never trips the "all recorded, start again?" question.
    if params.get("part") == "bank":
        items = studio.bank_plan()
        keys = params.get("keys")
        if keys is not None:
            want = set(keys)
            items = [i for i in items if i.key in want]
        dicts = [i.as_dict() for i in items]
        return {"part": "bank", "takes": 1, "items": dicts,
                "done": sum(1 for d in dicts if d["done"]),
                "total": len(dicts), "resumeAt": 0,
                "redo": keys is not None}

    part = params.get("part", "phonemes")
    items = studio.plan(part, params.get("order", "rows"))

    # `keys` narrows any part to the chosen items - the redo path. Nothing
    # is deleted first: the old flow removed the clips and reopened the
    # WHOLE part at its first gap, which could land somewhere other than
    # the selection, auto-advance into items never chosen, and leave a
    # deleted clip deleted if she quit half way. A redo records over the
    # top, and the previous take is kept as a backup.
    keys = params.get("keys")
    if keys is not None:
        want = set(keys)
        dicts = [i.as_dict() for i in items if i.key in want]
        return {"part": part, "takes": studio.takes_for(part),
                "items": dicts, "done": 0, "total": len(dicts),
                "resumeAt": 0, "redo": True}

    dicts = [i.as_dict() for i in items]
    done = sum(1 for d in dicts if d["done"])
    # Where to pick up: the first thing not yet recorded. A busy parent does
    # this over several sittings, so resuming has to be the default rather
    # than something to go looking for.
    resume = next((n for n, d in enumerate(dicts) if not d["done"]), len(dicts))
    return {"part": params.get("part", "phonemes"),
            "takes": studio.takes_for(params.get("part", "phonemes")),
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
            "weak": result["weak"], "advice": result["advice"],
            "saved": saved}


def m_passage_text(_params):
    """The passage itself, so it can be read from the screen."""
    from gen.paths import RESOURCES

    raw = (RESOURCES / "PASSAGE.md").read_text(encoding="utf-8")
    body = raw.split("## One", 1)[-1]
    return {"markdown": "## One" + body}


def m_studio_passage(params):
    """Save a passage recording, then check it as an import would.

    With `index`, one section is saved and the whole passage reassembled from
    every section recorded so far - this is how the app records it, because
    five undisturbed minutes is not something a parent reliably has. Without
    `index`, the audio is the entire passage in one take, which is how a file
    imported from a phone arrives.
    """
    import soundfile as sf
    from gen import passage as P
    from gen import recordings as R
    from gen import studio
    from gen.paths import VOICE_DIR

    audio = studio.decode(params["audio"], int(params.get("sampleRate", 48000)))
    index = params.get("index")

    if index is None:
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        dest = VOICE_DIR / "passage.wav"
        sf.write(dest, audio.astype("float32"), studio.SR)
        built = {"complete": True, "seconds": round(len(audio) / studio.SR, 1)}
    else:
        built = P.save_section(int(index), audio)
        dest = Path(built["path"])

    # Only judge the whole passage once it is whole. Running the import checks
    # against a third of the script would report it as too short every time,
    # which is true and useless while she is still working through it.
    issues, notes = [], []
    if built.get("complete"):
        issues, notes, _ = R.check_passage(dest, None, dry_run=True)

    out = {
        "path": str(dest),
        "seconds": built.get("seconds", 0.0),
        "issues": [{"label": i.label, "severity": i.severity, "message": i.message}
                   for i in issues],
        "notes": list(notes),
    }
    if index is not None:
        out["section"] = int(index)
        out["plan"] = P.plan()
    return out


def m_passage_plan(_params):
    """The sections, which are recorded, and where to pick up."""
    from gen import passage as P

    return P.plan()


def m_passage_remove(params):
    """Drop one section so it can be read again."""
    from gen import passage as P

    removed = P.remove_section(int(params["index"]))
    return {"removed": removed, "plan": P.plan()}


def m_voice_info(_params):
    """Where the recordings live, and how much there is. Shown in Settings."""
    from gen.paths import VOICE_DIR

    files = sorted(VOICE_DIR.rglob("*.wav")) if VOICE_DIR.exists() else []
    return {
        "dir": str(VOICE_DIR),
        "count": len(files),
        "bytes": sum(f.stat().st_size for f in files),
        "hasPassage": (VOICE_DIR / "passage.wav").exists(),
    }


def m_voice_export(params):
    """Copy every recording into one zip the user can put somewhere safe.

    Recording takes about forty minutes and cannot be redone identically, so
    it is the one thing in here worth protecting. The app's data folder is
    inside Library on macOS, where nobody would think to look, let alone back
    up - so this has to be one button rather than a path to go hunting for.
    """
    import zipfile
    from gen.paths import VOICE_DIR

    dest = Path(params["path"]).expanduser()
    if dest.suffix.lower() != ".zip":
        dest = dest.with_suffix(".zip")
    files = sorted(VOICE_DIR.rglob("*.wav")) if VOICE_DIR.exists() else []
    if not files:
        raise ValueError("There are no recordings to back up yet.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(VOICE_DIR).as_posix())
    return {"path": str(dest), "count": len(files),
            "bytes": dest.stat().st_size}


def m_voice_restore(params):
    """Put a backup back. Existing clips of the same name are replaced."""
    import zipfile
    from gen.paths import VOICE_DIR

    src = Path(params["path"]).expanduser()
    if not src.exists():
        raise ValueError(f"Can't find that file: {src}")
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(src) as z:
        for name in z.namelist():
            # Never write outside the voice directory, whatever the zip claims.
            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts or not name.endswith(".wav"):
                continue
            out = VOICE_DIR / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(name))
            n += 1
    if not n:
        raise ValueError("That file did not contain any recordings.")
    return {"restored": n}


def m_studio_clip(params):
    """Where a clip is, AND whether it actually contains anything.

    Without the level, a silent playback is indistinguishable from broken
    headphones - and the person cannot fix either without knowing which.
    """
    import numpy as np
    import soundfile as sf
    from gen import studio

    # The passage has no key - it is a single file, not one of a list.
    part = params.get("part", "phonemes")
    path = studio.clip_path(part, params.get("key", ""),
                            params.get("order", "rows"))
    preview = False
    if path is None and part == "pairs":
        # Nothing recorded, but never nothing to hear: every pair plays
        # as an automatic blend of the recorded sounds, and the preview IS
        # that blend - what a video would use today, rendered to a temp
        # file so the ordinary player can play it.
        import soundfile as sf
        from gen.paths import BUILD
        from gen.voice import VoiceSource, _safe

        try:
            a = VoiceSource().phoneme(params.get("key", ""))
            p = BUILD / "preview" / f"{_safe(params.get('key', ''))}.wav"
            p.parent.mkdir(parents=True, exist_ok=True)
            sf.write(p, a, 24000)
            path, preview = str(p), True
        except Exception:
            path = None
    out = {"path": path, "peak": 0.0, "seconds": 0.0, "silent": True,
           "preview": preview}
    if path:
        a, sr = sf.read(path, dtype="float32")
        out["peak"] = round(float(np.abs(a).max()) if a.size else 0.0, 4)
        out["seconds"] = round(len(a) / sr, 2)
        # Below this nothing is audible on a laptop speaker.
        out["silent"] = out["peak"] < 0.01

        # The passage is the voice-cloning reference, and the only recording
        # whose *length* can be wrong without anything looking wrong. Stopping
        # early saves a valid, audible wav that happens to be a fraction of the
        # script - which surfaces much later as a poor cloned voice, with
        # nothing pointing back at the cause.
        if params.get("part") == "passage":
            want = expected_passage_seconds()
            out["expectedSeconds"] = round(want)
            out["short"] = out["seconds"] < want * 0.5
    return out


def expected_passage_seconds() -> float:
    """Roughly how long the passage takes to read aloud.

    150 words a minute is unhurried reading. Only used to tell "she read the
    whole thing" apart from "she stopped after a paragraph", so it does not
    need to be better than roughly right.
    """
    from gen.paths import RESOURCES

    try:
        raw = (RESOURCES / "PASSAGE.md").read_text(encoding="utf-8")
    except OSError:
        return 240.0
    body = raw.split("## One", 1)[-1]
    words = sum(1 for w in body.split() if any(c.isalpha() for c in w))
    return max(60.0, words / 150.0 * 60.0)


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
    "sightwords.load": m_sightwords_load,
    "sightwords.save": m_sightwords_save,
    "sentences.list": m_sentences_list,
    "sentences.add": m_sentences_add,
    "sentences.remove": m_sentences_remove,
    "sentences.clips": m_sentences_clips,
    "sentences.estimate": m_sentences_estimate,
    "packs.list": m_packs_list,
    "packs.add": m_packs_add,
    "plan": m_plan,
    "encode": m_encode,
    "render.chrome": m_render_chrome,
    "cloning.install": m_install_cloning,
    "cloning.info": m_cloning_info,
    "recordings.import": m_recordings_import,
    "studio.plan": m_studio_plan,
    "studio.submit": m_studio_submit,
    "studio.clip": m_studio_clip,
    "voice.info": m_voice_info,
    "voice.export": m_voice_export,
    "voice.restore": m_voice_restore,
    "studio.passage": m_studio_passage,
    "passage.text": m_passage_text,
    "passage.plan": m_passage_plan,
    "passage.remove": m_passage_remove,
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
