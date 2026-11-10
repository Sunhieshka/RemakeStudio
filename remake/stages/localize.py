"""Stage 2 — Localize the story for the target language and region.

Seed LLM transcreates (not just translates): character looks, names, wardrobe, locations, props,
signage and dialogue are re-imagined as if the piece had been shot in the target region, while ids,
story beats and shot order stay identical so later stages can map everything 1:1.
Output: 02_localized.json.
"""

from __future__ import annotations

import json
import re

from remake.engine.sheet import llm_json
from remake.project import Project

SYSTEM = """You are a transcreation lead for film remakes. You re-imagine a production for a target language and
region so it feels locally shot — not dubbed — while the story, beats, emotions and shot order stay the same.

ERA: the remake is set in the PRESENT DAY unless the source unmistakably shows a historical period (vintage vehicles
or technology, a named historical event, explicit dates). Traditional or cultural dress of the source (saree, kurta,
hanbok, kimono…) is culture, NOT a period marker — replace it with what people in the target region wear today.
Any "period" wording in the source visual_style that only comes from traditional dress must be dropped.

Adapt:
- CHARACTERS: cast them so that a local audience recognises them at a glance as people from {region_or_default}
  today: names, ethnicity and appearance plausible for that region and setting, plus the everyday wardrobe,
  grooming, hairstyle, footwear and accessories that real people of that age, role and class wear there now.
  Keep age, gender, role, personality and story function. RECAST, don't re-dress: write the appearance as a casting
  director in {region_or_default} would cast the role for a local audience. Never copy the source actors' skin tone,
  ethnicity, face or hair descriptors, and never carry over the source's wardrobe colours, silhouettes or habits
  (draped garments, bindi, going barefoot at home…) — only role, age, emotion and story carry over.
- LOCATIONS: move each place to a believable equivalent in the region (architecture, materials, street furniture,
  climate, vegetation, interior dressing, brands become generic/local, signage in the target language).
- DIALOGUE: natural, idiomatic, spoken {language} as used in {region_or_default} — register, slang and forms of address
  that fit each character. Keep meaning and subtext. Each line must be speakable in roughly the same time as the
  original (±20%); trim filler rather than exceeding it. Use proper accents/punctuation of the language.
- ACTION / PROPS / ON-SCREEN TEXT: swap culturally specific items for local equivalents (food, gestures, money,
  vehicles, documents). On-screen text is written in {language}.
- ANY VISIBLE LETTERING (logos or names on clothing, signage, labels, vehicles): either in {language} with a locally
  plausible invented name, or none at all. Never leave source-language words in a description.
Keep every id (C1, L1, S1, SH1…) exactly as given. Never add or remove shots. Never name real people or brands.

Character "sheet_description": 90–160 words of plain visual facts for a character turnaround sheet — face, skin,
hair, build, age, and a COMPLETE head-to-toe outfit: top, lower-body garment (trousers, skirt…), footwear (or
"barefoot") and accessories, each with colours and materials. The sheet shows the full standing body, so name every
garment even if the source never shows it (a seated or close-up character): choose one that fits role, era, region. No pose, expression, lighting or
background. Photorealistic unless the source visual_style says otherwise.
Location "plate_description": 70–140 words — one empty establishing view of the place (no people or animals):
interior/exterior, region and era, architecture, materials, key set pieces the scenes use, signage, light/time of day.

Return ONLY JSON (no prose, no code fences):
{{
  "language": "{language}",
  "region": "{region_or_default}",
  "title": "<localized title>",
  "logline": "<localized logline in English>",
  "visual_style": "<the source cinematography (light, lens, palette, mood) in neutral terms — no source-culture or period words unless the era rule keeps a period>",
  "localization_notes": ["<each notable cultural decision, one line>"],
  "characters": [{{"id": "C1", "source_name": "", "name": "", "role": "", "gender": "", "age": "",
                   "personality": "", "wardrobe": "<the complete head-to-toe outfit only: garments, footwear, accessories>",
                   "sheet_description": "", "voice": "<voice and accent in {language}>", "changes": "<what changed and why>"}}],
  "locations": [{{"id": "L1", "source_name": "", "name": "", "plate_description": "", "changes": ""}}],
  "scenes": [{{"id": "S1", "location_id": "L1", "time_of_day": "", "summary": ""}}],
  "shots": [{{"id": "SH1", "scene_id": "S1", "start": 0, "end": 0, "shot_size": "", "camera_angle": "",
              "camera_movement": "", "characters": ["C1"], "action": "<localized, concrete, English>", "emotion": "",
              "dialogue": [{{"character_id": "C1", "line": "<in {language}>", "source_line": "<original>",
                             "delivery": ""}}],
              "sound": "", "on_screen_text": "<in {language} or empty>"}}]
}}"""


CASTING_SYSTEM = """You are the casting director of a film made in {region} for a mainstream {region} audience.
For each role, cast an actor whom that audience reads at a glance as a local person from {region} today, and write
the look as plain visual facts. You are NOT told what the actors of any earlier version looked like — cast fresh.
For each character return:
- "name": a first and last name common for people of that age in {region}.
- "appearance": 40–70 words — skin tone, face, eyes, hair colour, length and one fixed hairstyle, build, age.
  No clothing, pose, expression, lighting or background.
Keep gender and age as given. Make the cast look like different people from each other.
Return ONLY JSON: {{"characters": [{{"id": "C1", "name": "", "appearance": ""}}]}}"""


def _recast(data: dict, region: str) -> list:
    """Re-cast faces and names from role/age/gender alone, so the source actors' looks can't leak through.
    The wardrobe from the transcreation pass is kept. Returns notes on what changed."""
    chars = data.get("characters") or []
    if not chars:
        return []
    brief = [{k: c.get(k, "") for k in ("id", "role", "gender", "age", "personality")} for c in chars]
    cast = llm_json(CASTING_SYSTEM.format(region=region), "ROLES:\n" + json.dumps(brief, ensure_ascii=False, indent=1),
                    temperature=0.7, max_tokens=4000)
    by_id = {c.get("id"): c for c in (cast.get("characters") or []) if isinstance(c, dict)}
    renames, notes = {}, []
    for c in chars:
        new = by_id.get(c["id"]) or {}
        if not new.get("appearance"):
            continue
        old_name = (c.get("name") or "").strip()
        if new.get("name") and new["name"].strip() != old_name:
            c["name"] = new["name"].strip()
            if old_name:
                renames[old_name.split()[0]] = c["name"].split()[0]
        wardrobe = (c.get("wardrobe") or "").strip()
        c["appearance"] = new["appearance"].strip()
        c["sheet_description"] = c["appearance"] + (" Wears " + wardrobe[0].lower() + wardrobe[1:] if wardrobe and
                                                     not wardrobe.lower().startswith("wear") else " " + wardrobe)
        notes.append(f"Cast {c['id']} ({c.get('role') or 'role'}) as {c['name']}, a local face for {region}.")
    if renames:   # follow the new first names through dialogue and action
        pat = re.compile(r"\b(" + "|".join(map(re.escape, renames)) + r")\b")
        for sh in data.get("shots") or []:
            for key in ("action", "on_screen_text"):
                if isinstance(sh.get(key), str):
                    sh[key] = pat.sub(lambda m: renames[m.group(1)], sh[key])
            for d in sh.get("dialogue") or []:
                if isinstance(d.get("line"), str):
                    d["line"] = pat.sub(lambda m: renames[m.group(1)], d["line"])
        for sc in data.get("scenes") or []:
            if isinstance(sc.get("summary"), str):
                sc["summary"] = pat.sub(lambda m: renames[m.group(1)], sc["summary"])
    return notes


def run(p: Project) -> dict:
    meta = p.meta
    target = meta["target"]
    language = target["language"].strip()
    region = target.get("region", "").strip() or f"the main {language}-speaking market"
    src = p.require("01_understanding.json")
    src = {k: v for k, v in src.items() if not k.startswith("_")}

    user = "SOURCE BREAKDOWN:\n" + json.dumps(src, ensure_ascii=False, indent=1)
    if target.get("notes"):
        user += "\n\nDIRECTOR NOTES FOR THE REMAKE:\n" + target["notes"].strip()
    user += f"\n\nTarget: {language} — {region}. Return the JSON."

    p.progress("localize", f"Transcreating for {language} / {region}…")
    data = llm_json(SYSTEM.format(language=language, region_or_default=region), user, temperature=0.5,
                    max_tokens=24000)

    p.progress("localize", f"Casting local faces for {region}…")
    data.setdefault("localization_notes", []).extend(_recast(data, region))

    # Guard the 1:1 mapping: fall back to source timing/ids for anything the model dropped.
    by_id = {s.get("id"): s for s in data.get("shots") or []}
    merged = []
    for s in src["shots"]:
        loc = by_id.get(s["id"]) or {}
        out = {**s, **{k: v for k, v in loc.items() if v not in (None, "")}}
        out["start"], out["end"] = s["start"], s["end"]
        if not loc:
            out["_untranslated"] = True
        merged.append(out)
    data["shots"] = merged
    data.setdefault("language", language)
    data.setdefault("region", region)
    p.write("02_localized.json", data)
    missing = sum(1 for s in merged if s.get("_untranslated"))
    return {"characters": len(data.get("characters") or []), "locations": len(data.get("locations") or []),
            "shots": len(merged), "untranslated_shots": missing}
