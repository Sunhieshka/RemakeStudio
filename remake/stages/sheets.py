"""Stage 4 — Character sheets and location plates, generated from the prompts written in stage 3.

Runs only when you click Generate: one card, or every card that has no image yet or whose prompt changed.
Images are copied into projects/<id>/sheets/. Output: 03_sheets.json.
"""

from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from remake.engine import sheet as csq
from remake.engine.models import pmap
from remake.project import Project

MAX_WORKERS = 4


def run(p: Project, only: Optional[list] = None) -> dict:
    from remake.stages import prompts
    S = p.read("03_sheets.json") or {}
    entries = [(kind, e) for kind in ("characters", "locations") for e in (S.get(kind) or {}).values()]
    if not entries or not all(e.get("prompt") for _, e in entries):
        raise RuntimeError("Write the prompts first (stage 3).")
    p.path("sheets").mkdir(exist_ok=True)
    if only:
        jobs = [(k, e) for k, e in entries if e["id"] in only]
    else:
        jobs = [(k, e) for k, e in entries
                if not (e.get("image") and p.path(e["image"]).is_file()) or e.get("status") in ("outdated", "error")]
    lock = threading.Lock()

    def save():
        with lock:
            p.write("03_sheets.json", S)

    for _, e in jobs:      # queued cards show "generating" and keep their old image until it is replaced
        e.update(status="generating", error="")
    save()
    done = [0]

    def work(job):
        kind, e = job
        prompt = e["prompt"]
        try:
            img = csq.seedream(prompt, None, csq.SHEET_SIZE, "sheet" if kind == "characters" else "location")
            dest = p.path("sheets", f"{e['id']}.png")
            shutil.copyfile(img["path"], dest)
            e.update(image=str(dest.relative_to(p.dir)), image_prompt=prompt, status="done", error="")
        except Exception as ex:     # keep going; the failure shows on that card
            e.update(status="error", error=str(ex))
        save()
        done[0] += 1
        p.progress("sheets", f"{done[0]}/{len(jobs)} sheets")

    with ThreadPoolExecutor(MAX_WORKERS) as pool:
        pmap(pool, work, jobs)
    prompts.refresh(p)      # clips whose reference sheets changed become "outdated"

    errors = [f"{e['id']} — {e.get('error')}" for _, e in jobs if e.get("status") == "error"]
    if errors:
        raise RuntimeError("Some sheets failed (click Generate on those cards to retry):\n" + "\n".join(errors))
    return {"generated": len(jobs), "characters": len(S.get("characters") or {}),
            "locations": len(S.get("locations") or {})}
