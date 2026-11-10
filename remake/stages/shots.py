"""Stage 5 — Video generation with Seedance. Runs only when you click Generate (all clips, or one).

Clips, their @Image references and their prompts come from stage 3 (Write prompts) and can be edited first.
Reference images (sheets from stage 4) go straight into the request as JPEG data URLs: no TOS, no asset
library. Every prompt ends with the no-text-overlay rule, re-checked here before it is sent.
Seedance tasks run in parallel; finished clips are downloaded to clips/. Output: 04_shots.json.
"""

from __future__ import annotations

import base64
import math
import re
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from remake.engine import video
from remake.engine.ffmpeg import get_ffmpeg_path
from remake.engine.models import MIN_VIDEO_DURATION, VIDEO_MODELS, pmap
from remake.project import Project

WORDS_PER_SECOND = 2.6     # comfortable spoken pace across most languages
POLL_S = 10
TASK_TIMEOUT_S = 30 * 60
OVERRUN = 1.10


# ---- 4a grouping --------------------------------------------------------------------------------

def _speech_seconds(shots: list) -> float:
    words = sum(len(str(d.get("line") or "").split()) for s in shots for d in s.get("dialogue") or [])
    return words / WORDS_PER_SECOND + (0.6 * sum(len(s.get("dialogue") or []) for s in shots))


def clip_limits(settings: dict) -> tuple:
    """(min, max) seconds per generation: max is the video model's own limit unless set lower."""
    model_max = int(VIDEO_MODELS.get(settings.get("video_model"), {}).get("max_duration") or 15)
    want = int(settings.get("max_clip_seconds") or 0)
    hi = min(model_max, want) if want > 0 else model_max
    lo = max(MIN_VIDEO_DURATION, min(int(settings.get("min_clip_seconds") or 4), hi))
    return lo, hi


def group_clips(shots: list, min_s: float, max_s: float, mode: str = "pack") -> list:
    """Consecutive shots packed into as few generations as fit in max_s (source time and the time the
    target-language dialogue needs). mode "scene" also cuts at every scene change."""
    clips, cur = [], []

    def span(group):
        return group[-1]["end"] - group[0]["start"] if group else 0.0

    for s in shots:
        new_scene = cur and s.get("scene_id") != cur[-1].get("scene_id")
        # Source timing may run up to OVERRUN past the limit: the clip is then rendered at max_s with
        # its beats compressed slightly, instead of spending a whole extra generation on a sliver.
        if cur and ((mode == "scene" and new_scene) or span(cur + [s]) > max_s * OVERRUN
                    or _speech_seconds(cur + [s]) > max_s - 1):
            clips.append(cur)
            cur = []
        cur.append(s)
    if cur:
        clips.append(cur)

    out = []
    for i, group in enumerate(clips, 1):
        need = max(span(group), _speech_seconds(group) + 0.5)
        scene_ids = list(dict.fromkeys(s.get("scene_id") for s in group))
        out.append({
            "id": f"CLIP{i:02d}",
            "shot_ids": [s["id"] for s in group],
            "scene_ids": scene_ids,
            "source_start": group[0]["start"],
            "source_end": group[-1]["end"],
            "duration": int(min(max_s, max(min_s, math.ceil(need)))),
            "status": "pending",
        })
    return out


# ---- 4b prompt ----------------------------------------------------------------------------------

def _scene_ids(clip: dict) -> list:
    return clip.get("scene_ids") or [clip.get("scene_id")]


def refs_for_clip(clip: dict, loc: dict, max_refs: int = 9) -> list:
    """[(kind, id, name)] — the clip's characters first, then each location it visits. Mapped to @Image1..N."""
    shots = {s["id"]: s for s in loc["shots"]}
    chars = {c["id"]: c for c in loc.get("characters") or []}
    scenes = {s["id"]: s for s in loc.get("scenes") or []}
    locs = {l["id"]: l for l in loc.get("locations") or []}
    refs, seen = [], set()
    for sid in clip["shot_ids"]:
        for cid in shots[sid].get("characters") or []:
            if cid in chars and cid not in seen:
                seen.add(cid)
                refs.append(("character", cid, chars[cid].get("name", cid)))
    for scene_id in _scene_ids(clip):
        lid = (scenes.get(scene_id) or {}).get("location_id")
        if lid in locs and lid not in seen:
            seen.add(lid)
            refs.append(("location", lid, locs[lid].get("name", lid)))
    return refs[:max_refs]


def brief_for_clip(clip: dict, loc: dict, refs: list) -> str:
    shots = {s["id"]: s for s in loc["shots"]}
    chars = {c["id"]: c for c in loc.get("characters") or []}
    scenes = {s["id"]: s for s in loc.get("scenes") or []}
    tag = {r[1]: f"@Image{i}" for i, r in enumerate(refs, 1)}
    language, region = loc.get("language", ""), loc.get("region", "")

    locs = {l["id"]: l for l in loc.get("locations") or []}
    lines = []
    for i, (kind, rid, name) in enumerate(refs, 1):
        if kind == "character":
            lines.append(f"{name} maps to @Image{i} (character turnaround sheet); use only face, hair, build and "
                         f"wardrobe, not the sheet layout or grey background.")
        else:
            lines.append(f"Location \"{name}\" references @Image{i}; use only the space, architecture, materials "
                         f"and lighting, and only in the shots set there.")
    style = re.sub(r",?\s*(vertical|horizontal)?\s*\d+:\d+( aspect( ratio)?)?", "", loc.get("visual_style", ""), flags=re.I)
    lines += ["", f"Visual style: {style.strip(' ,')}"]
    for scene_id in _scene_ids(clip):
        sc = scenes.get(scene_id) or {}
        where = (locs.get(sc.get("location_id")) or {}).get("name", "")
        lines.append(f"Scene {scene_id} at {where} ({sc.get('time_of_day', '')}): {sc.get('summary', '')}")
    lines += [f"Total length: {clip['duration']} seconds, {len(clip['shot_ids'])} shot(s) with hard cuts between them.",
              f"All speech is in {language} with a natural {region} accent; characters lip-sync every line exactly "
              f"as written. Strictly no text overlay: no subtitles, captions, title cards or on-screen text.", ""]

    t0 = clip["source_start"]
    src_len = max(0.1, clip["source_end"] - clip["source_start"])
    scale = clip["duration"] / src_len        # stretch or compress the source beats to the clip length
    for sid in clip["shot_ids"]:
        s = shots[sid]
        a, b = (s["start"] - t0) * scale, (s["end"] - t0) * scale
        who = ", ".join(f"{(chars.get(c) or {}).get('name', c)} ({tag.get(c, 'no ref')})" for c in s.get("characters") or [])
        lid = (scenes.get(s.get("scene_id")) or {}).get("location_id")
        if len(_scene_ids(clip)) > 1:
            who += f". Location: {(locs.get(lid) or {}).get('name', lid)} ({tag.get(lid, 'no ref')})"
        framing = " ".join(x for x in (s.get("shot_size"), s.get("camera_angle")) if x) or "shot"
        lines.append(f"[{a:.1f}s–{b:.1f}s] {framing}, camera {s.get('camera_movement') or 'static'}. "
                     f"On screen: {who or 'no characters'}.")
        if s.get("action"):
            lines.append(f"  Action: {s['action']}" + (f"  Emotion: {s['emotion']}" if s.get("emotion") else ""))
        for d in s.get("dialogue") or []:
            speaker = (chars.get(d.get("character_id")) or {}).get("name", d.get("character_id"))
            how = f" ({d['delivery']})" if d.get("delivery") else ""
            lines.append(f"  {speaker} says{how}: \"{d.get('line', '')}\"")
        if s.get("sound"):
            lines.append(f"  Sound: {s['sound']}")
    return "\n".join(lines)


# ---- 4d generation ------------------------------------------------------------------------------

def _inline_ref(path, max_edge: int = 2560) -> str:
    """Reference image sent straight to Seedance as a base64 JPEG data URL — no TOS upload, no asset library.
    The PNG sheets (~6 MB) are re-encoded with ffmpeg so a request with several references stays small."""
    scale = f"scale='if(gt(iw,ih),min(iw,{max_edge}),-2)':'if(gt(iw,ih),-2,min(ih,{max_edge}))'"
    out = subprocess.run([get_ffmpeg_path(), "-loglevel", "error", "-i", str(path), "-vf", scale, "-q:v", "3",
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                         capture_output=True, timeout=60)
    if out.returncode or not out.stdout:
        raise RuntimeError(f"Could not encode reference {path.name}: {out.stderr.decode()[:200]}")
    return "data:image/jpeg;base64," + base64.b64encode(out.stdout).decode("ascii")


def _render(p: Project, clip: dict, settings: dict, upd) -> None:
    """upd(**fields) updates the clip and saves 04_shots.json under the stage's lock."""
    from remake.stages import prompts      # lazy: prompts imports this module
    if clip.get("video") and p.path(clip["video"]).is_file():
        return
    if not clip.get("task_id"):
        missing = [r["id"] for r in clip.get("references") or [] if not p.path(r["image"]).is_file()]
        if missing:
            raise RuntimeError(f"Generate these sheets first: {', '.join(missing)}")
        ref_urls = [_inline_ref(p.path(r["image"])) for r in clip.get("references") or []]
        basis = prompts.clip_basis(p, clip)
        task_id = video.create_video_task(
            prompt=prompts.with_no_text(clip["prompt"]), reference_images=ref_urls, ratio=settings["ratio"],
            resolution=settings["resolution"], duration=int(clip["duration"]),
            model=settings["video_model"], draft=bool(settings.get("draft")))
        upd(task_id=task_id, status="rendering", error="", rendered_basis=basis)

    started = time.time()
    while True:
        t = video.get_video_task(task_id=clip["task_id"])
        if t["status"] == "succeeded":
            break
        if t["status"] in ("failed", "cancelled", "expired"):
            upd(task_id="")                 # so a re-run submits a fresh task
            raise RuntimeError(f"Seedance {t['status']}: {t['error'].get('message') or t['error'].get('code')}")
        if time.time() - started > TASK_TIMEOUT_S:
            raise RuntimeError("Timed out waiting for Seedance (the task keeps running; re-run to resume).")
        time.sleep(POLL_S)

    dest = p.path("clips", f"{clip['id']}.mp4")
    req = urllib.request.Request(t["video_url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as f:
        f.write(resp.read())
    upd(video=str(dest.relative_to(p.dir)), status="done", error="")


# ---- stage entry --------------------------------------------------------------------------------

def needs_render(p: Project, c: dict) -> bool:
    return c.get("status") == "outdated" or not (c.get("video") and p.path(c["video"]).is_file())


def run(p: Project, only: Optional[list] = None) -> dict:
    """Renders the clips in `only`, or every clip that has no video yet or is outdated."""
    settings = p.meta["settings"]
    state = p.read("04_shots.json") or {}
    clips = state.get("clips") or []
    if not clips or not all(c.get("prompt") for c in clips):
        raise RuntimeError("Write the prompts first (stage 3).")
    p.path("clips").mkdir(exist_ok=True)
    pending = [c for c in clips if c["id"] in only] if only else [c for c in clips if needs_render(p, c)]
    lock = threading.RLock()

    def upd(clip, **fields):
        with lock:
            clip.update(fields)
            p.write("04_shots.json", state)

    done = [0]

    def work(c):
        try:
            _render(p, c, settings, lambda **f: upd(c, **f))
        except Exception as e:
            upd(c, status="error", error=str(e))
        done[0] += 1
        p.progress("shots", f"Rendered {done[0]}/{len(pending)} clips")

    for c in pending:
        if c.get("video") or c.get("status") == "outdated":
            upd(c, video="", task_id="")      # generate again with the current prompt and sheets
        if not c.get("task_id"):
            upd(c, status="queued", error="")
    p.progress("shots", f"Rendering {len(pending)} clip(s) with {settings['video_model']}…")
    with ThreadPoolExecutor(max(1, int(settings.get("parallel_videos") or 3))) as pool:
        pmap(pool, work, pending)

    failed = [f"{c['id']}: {c['error']}" for c in pending if c.get("status") == "error"]
    if failed:
        raise RuntimeError("Some clips failed (click Generate on those clips to retry):\n" + "\n".join(failed))
    return {"clips": len(clips), "rendered": sum(1 for c in clips if c.get("video"))}
