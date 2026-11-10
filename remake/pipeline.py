"""Runs one stage per click (or a range from the CLI), recording status/errors in project.json."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Optional

from remake.engine import models
from remake.project import STAGE_KEYS, Project
from remake.stages import assemble, localize, prompts, sheets, shots, understand

RUNNERS = {
    "understand": understand.run,
    "localize": localize.run,
    "prompts": prompts.run,
    "sheets": sheets.run,
    "shots": shots.run,
    "assemble": assemble.run,
}

_running: dict = {}


def run_stage(p: Project, key: str, **kwargs) -> dict:
    p.set_stage(key, status="running", error="", progress="", started=time.time())
    try:
        with models.use(p.meta["settings"]):      # this project's LLM / image model for every model call
            result = RUNNERS[key](p, **kwargs)
    except Exception as e:
        p.set_stage(key, status="error", error=str(e), trace=traceback.format_exc()[-4000:], ended=time.time())
        raise
    p.set_stage(key, status="done", error="", progress="", result=result, ended=time.time())
    for later in STAGE_KEYS[STAGE_KEYS.index(key) + 1:]:
        if p.meta["stages"][later]["status"] == "done":
            p.set_stage(later, status="stale")
    return result


def run(p: Project, start: Optional[str] = None, until: Optional[str] = None, only: Optional[list] = None) -> None:
    """Runs stages start..until (default: just `start`). The UI always runs one stage per click."""
    first = start or STAGE_KEYS[0]
    keys = STAGE_KEYS[STAGE_KEYS.index(first): STAGE_KEYS.index(until or first) + 1]
    for key in keys:
        if key == "assemble" and not _all_clips_rendered(p):
            msg = "Generate every clip (and update outdated ones) before assembling."
            p.set_stage("assemble", status="error", error=msg, progress="")
            raise RuntimeError(msg)
        run_stage(p, key, **({"only": only} if only and key in ("sheets", "shots") else {}))


def _all_clips_rendered(p: Project) -> bool:
    clips = (p.read("04_shots.json") or {}).get("clips") or []
    return bool(clips) and all(c.get("video") and p.path(c["video"]).is_file() and c.get("status") != "outdated"
                               for c in clips)


def run_in_background(p: Project, start: Optional[str] = None, until: Optional[str] = None, **kw) -> bool:
    """Starts a run unless one is already going for this project."""
    t = _running.get(p.id)
    if t and t.is_alive():
        return False

    def go():
        try:
            run(p, start, until, **kw)
        except Exception:
            pass        # recorded in project.json

    t = threading.Thread(target=go, daemon=True)
    _running[p.id] = t
    t.start()
    return True


def is_running(pid: str) -> bool:
    t = _running.get(pid)
    return bool(t and t.is_alive())
