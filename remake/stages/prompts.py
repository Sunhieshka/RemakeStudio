"""Stage 3 — Write every prompt in ONE Seed LLM call.

From the localized story the LLM writes, together:
- a Seedream prompt for each character sheet,
- a Seedream prompt for each location plate,
- a Seedance prompt for each video clip (shots packed into clips first), with @Image1..N mapped to the
  sheets that clip will use.
Prompts are saved on their cards (03_sheets.json, 04_shots.json) so each one can be read and edited
before anything is generated. Nothing is generated here.
"""

from __future__ import annotations

import hashlib
import json

from remake.engine import sheet as csq
from remake.engine import sheet_prompts as SP
from remake.engine.models import video_spec
from remake.engine.video import SD25_PE_SKILL
from remake.project import Project
from remake.stages.shots import brief_for_clip, clip_limits, group_clips, refs_for_clip

# Appended by code to every video prompt (and re-checked right before rendering), so it can't be lost.
NO_TEXT = ("Strictly no text overlay: no subtitles, no captions, no title cards, no on-screen text, labels, "
           "logos or watermarks anywhere in the video. Dialogue is only heard, never written on screen.")
LOCATION_TAIL = "One location, with nothing alive anywhere in the frame. No text, no lettering, no watermark."

SYSTEM = """You are the prompt writer for a film remake. In ONE answer you write every generation prompt:
character sheets and location plates for the Seedream image model, and one prompt per clip for the Seedance 2.5
video model. Everything must agree: the same faces, hair, wardrobe and places in the sheets and in the clips.

1. CHARACTER "sheet_prompt" (120–220 words): the character section of a Seedream turnaround-sheet prompt. The app
   adds the four-panel layout, camera, background and lighting, so write ONLY the person: age, build, skin, face,
   eyes, eyebrows; hair as ONE fixed style (length, colour, parting, how it is tied) and how it reads from the
   front, the side and the back; then every garment head to toe (top, lower-body garment, footwear) with
   construction, colour, material and how it is worn; accessories with an explicit side from the character's own
   left/right. Flat neutral expression, mouth closed. Never leave the legs or feet undescribed. Keep every fact in
   the character's description; choose concrete values where it is vague.
2. LOCATION "plate_prompt" (80–150 words): one empty, wide 16:9 establishing photograph of the place — interior or
   exterior, architecture, materials, set pieces the scenes use, light and time of day, visual style. No people, no
   animals, no readable text or lettering.
3. CLIP "video_prompt": a production-ready Seedance 2.5 prompt following the SD25 prompt optimizer skill below.
   - Use exactly the @Image tags given for that clip: say which character or location each one is, and use only
     the face/hair/build/wardrobe from a character sheet (not its layout or grey background) and only the space
     from a location plate.
   - Keep the shots in order with their timings, hard cuts between them, camera size/angle/movement, action and
     emotion, and sound/ambience.
   - Every dialogue line VERBATIM in quotes, in the target language, attributed to its speaker, with clear lip-sync.
   - STRICTLY NO TEXT OVERLAY: no subtitles, captions, title cards, location labels or any on-screen text.
   - Frame for video_aspect_ratio; ignore any other aspect ratio mentioned in visual_style.
   - Plain prose, no markdown, under 700 words.

Return ONLY this JSON (no prose, no code fences):
{"characters": [{"id": "C1", "sheet_prompt": ""}],
 "locations": [{"id": "L1", "plate_prompt": ""}],
 "clips": [{"id": "CLIP01", "video_prompt": ""}]}

SD25 PROMPT OPTIMIZER SKILL:
"""


def compose_character(spec: str) -> str:
    return "CHARACTER\n" + spec.strip() + "\n\n" + SP.TEXT_SHEET_BASE_PROMPT


def compose_location(plate: str) -> str:
    return plate.strip() + "\n\n" + LOCATION_TAIL


def with_no_text(prompt: str) -> str:
    prompt = (prompt or "").strip()
    return prompt if NO_TEXT in prompt else prompt + "\n\n" + NO_TEXT


def clip_basis(p: Project, clip: dict) -> str:
    """Fingerprint of what a clip is rendered from: its prompt and the current reference images."""
    h = hashlib.sha1(with_no_text(clip.get("prompt") or "").encode("utf-8"))
    for r in clip.get("references") or []:
        f = p.path(r["image"])
        h.update(f.read_bytes() if f.is_file() else b"missing")
    return h.hexdigest()[:16]


def refresh(p: Project) -> None:
    """Marks sheets and clips 'outdated' when their prompt (or a clip's reference sheets) changed after they were
    generated, and back to 'done' when they match again. Never touches items that are generating."""
    S = p.read("03_sheets.json")
    if S:
        for kind in ("characters", "locations"):
            for e in (S.get(kind) or {}).values():
                if not (e.get("image") and p.path(e["image"]).is_file()) or e.get("status") in ("generating", "error"):
                    continue
                if "image_prompt" not in e:                             # projects from before this field existed
                    e["image_prompt"] = e.get("prompt") if e.get("status") != "outdated" else None
                e["status"] = "done" if e.get("image_prompt") == e.get("prompt") else "outdated"
        p.write("03_sheets.json", S)
    C = p.read("04_shots.json")
    if C:
        for c in C.get("clips") or []:
            if not (c.get("video") and p.path(c["video"]).is_file()) or c.get("status") in ("queued", "rendering", "error"):
                continue
            if "rendered_basis" not in c:          # clips rendered before this field existed: keep their status
                if c.get("status") == "outdated":
                    continue
                c["rendered_basis"] = clip_basis(p, c)
            c["status"] = "done" if c["rendered_basis"] == clip_basis(p, c) else "outdated"
        p.write("04_shots.json", C)


def run(p: Project) -> dict:
    settings = p.meta["settings"]
    loc = p.require("02_localized.json")
    chars, locs = loc.get("characters") or [], loc.get("locations") or []

    # Clips: regroup on the first run, or when the model / clip settings changed before anything was rendered.
    lo, hi = clip_limits(settings)
    grouping = {"mode": settings.get("clip_mode") or "pack", "min": lo, "max": hi}
    state = p.read("04_shots.json") or {}
    started = any(c.get("task_id") or c.get("video") for c in state.get("clips") or [])
    if not state.get("clips") or (state.get("grouping") != grouping and not started):
        state = {"grouping": grouping, "clips": group_clips(loc["shots"], lo, hi, grouping["mode"])}
    clips = state["clips"]
    max_refs = int(video_spec(settings["video_model"]).get("max_ref_images") or 9)
    for c in clips:
        refs = refs_for_clip(c, loc, max_refs)
        c["references"] = [{"tag": f"@Image{i}", "kind": k, "id": rid, "name": n, "image": f"sheets/{rid}.png"}
                           for i, (k, rid, n) in enumerate(refs, 1)]
        c["brief"] = brief_for_clip(c, loc, refs)

    request = {
        "language": loc.get("language"), "region": loc.get("region"),
        "video_aspect_ratio": settings.get("ratio", "16:9"),
        "visual_style": loc.get("visual_style", ""),
        "characters": [{"id": c["id"], "name": c.get("name"), "gender": c.get("gender"), "age": c.get("age"),
                        "description": c.get("sheet_description", "")} for c in chars],
        "locations": [{"id": l["id"], "name": l.get("name"), "description": l.get("plate_description", "")}
                      for l in locs],
        "clips": [{"id": c["id"], "duration_seconds": c["duration"], "brief": c["brief"]} for c in clips],
    }
    p.progress("prompts", f"Writing {len(chars)} character, {len(locs)} location and {len(clips)} clip prompts "
                          f"in one call…")
    out = csq.llm_json(SYSTEM + SD25_PE_SKILL, json.dumps(request, ensure_ascii=False, indent=1),
                       temperature=0.3, max_tokens=32000, timeout=900)

    def by_id(key, field):
        return {x.get("id"): str(x.get(field) or "").strip() for x in out.get(key) or [] if isinstance(x, dict)}
    cp, lp, vp = by_id("characters", "sheet_prompt"), by_id("locations", "plate_prompt"), by_id("clips", "video_prompt")

    S = p.read("03_sheets.json") or {}
    S = {"characters": dict(S.get("characters") or {}), "locations": dict(S.get("locations") or {})}
    missing = []
    for kind, items, written, compose, fallback in (
            ("characters", chars, cp, compose_character, "sheet_description"),
            ("locations", locs, lp, compose_location, "plate_description")):
        for it in items:
            if not written.get(it["id"]):
                missing.append(it["id"])
            e = S[kind].get(it["id"]) or {}
            if e.get("image") and "image_prompt" not in e:
                e["image_prompt"] = e.get("prompt")                  # keep what the existing image was made from
            e.update(id=it["id"], name=it.get("name", it["id"]), error="",
                     prompt=compose(written.get(it["id"]) or it.get(fallback) or it.get("name", "")))
            e["status"] = "prompted" if not e.get("image") else e.get("status", "done")
            S[kind][it["id"]] = e
    for c in clips:
        if c.get("video") and "rendered_basis" not in c and c.get("status") != "outdated":
            c["rendered_basis"] = clip_basis(p, c)        # remember what the existing video was made from
        if not vp.get(c["id"]):
            missing.append(c["id"])
        c["prompt"] = with_no_text(vp.get(c["id"]) or c["brief"])
        if not c.get("video"):
            c["status"] = "prompted"
        c["error"] = "" if c.get("status") != "error" else c.get("error", "")
    p.write("03_sheets.json", S)
    p.write("04_shots.json", state)
    refresh(p)
    return {"characters": len(chars), "locations": len(locs), "clips": len(clips),
            "fallbacks": missing}
