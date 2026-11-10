"""Stage 1 — Understand the source.

Video: Seed video understanding (Seed 2.0 Lite by default, which also hears the audio track, so
dialogue is transcribed). Script: Seed LLM breaks the text into the same structure, estimating timing.
Output: 01_understanding.json.
"""

from __future__ import annotations

from remake.engine import understanding
from remake.engine.sheet import llm_json, parse_json
from remake.project import Project

SCHEMA = """{
  "title": "<working title>",
  "logline": "<one sentence>",
  "genre": "<genre>",
  "tone": "<tone / mood>",
  "source_language": "<language spoken in the source>",
  "duration_seconds": <number>,
  "visual_style": "<medium, look, colour palette, lighting, lens feel, aspect>",
  "characters": [
    {"id": "C1", "name": "<name or descriptive label>", "role": "<who they are in the story>",
     "gender": "", "age": "", "appearance": "<face, build, skin, hair>",
     "wardrobe": "<exact clothing, colours, accessories>", "personality": "", "voice": "<pitch, pace, timbre>"}
  ],
  "locations": [
    {"id": "L1", "name": "", "int_ext": "INT|EXT", "description": "<architecture, materials, set pieces, props, era>"}
  ],
  "scenes": [
    {"id": "S1", "location_id": "L1", "time_of_day": "", "summary": "<what happens>"}
  ],
  "shots": [
    {"id": "SH1", "scene_id": "S1", "start": <seconds>, "end": <seconds>,
     "shot_size": "<ECU|CU|MCU|MS|MWS|WS|EWS>", "camera_angle": "", "camera_movement": "",
     "characters": ["C1"], "action": "<what visibly happens, concrete>", "emotion": "",
     "dialogue": [{"character_id": "C1", "line": "<verbatim>", "delivery": "<how it is said>"}],
     "sound": "<sfx / ambience / music>", "on_screen_text": ""}
  ]
}"""

VIDEO_PROMPT = f"""Break this video down for a shot-by-shot remake. Watch the whole video and listen to the audio.

Rules:
- One entry in "shots" per camera cut, in order, with start/end in seconds (decimals allowed). Shots must cover the whole video.
- Transcribe every spoken line verbatim in its original language and attribute it to a character id.
- Characters: everyone who appears on screen, with enough visual detail to recreate them (but describe, don't name real people).
- Locations: every distinct place; scenes group consecutive shots in one location and time.
- Be concrete and visual. No speculation beyond what is seen/heard.
- visual_style describes cinematography (light, lens, palette, mood). Only call it "period" when there are clear
  historical markers; traditional or cultural clothing is not a period marker.

Return ONLY this JSON (no prose, no code fences):
{SCHEMA}"""

SCRIPT_SYSTEM = f"""You are a script supervisor and first AD. Break the script into a shot list for production.
- Invent a sensible coverage: one entry per camera cut, with plausible shot sizes and movement.
- Timing: speech at ~2.5 words per second plus action beats; start/end in seconds, continuous from 0.
- Keep every dialogue line verbatim and attributed to a character id.
- Where the script is silent about appearance, wardrobe or place, make ONE specific choice that fits.
Return ONLY this JSON (no prose, no code fences):
{SCHEMA}"""


def _normalise(data: dict) -> dict:
    shots = data.get("shots") or []
    for i, s in enumerate(shots, 1):
        s.setdefault("id", f"SH{i}")
        try:
            s["start"], s["end"] = float(s.get("start") or 0), float(s.get("end") or 0)
        except (TypeError, ValueError):
            s["start"], s["end"] = 0.0, 0.0
        if s["end"] <= s["start"]:
            s["end"] = s["start"] + 3.0
        s.setdefault("characters", [])
        s.setdefault("dialogue", [])
    data["shots"] = shots
    for key in ("characters", "locations", "scenes"):
        data.setdefault(key, [])
    if shots and not data.get("duration_seconds"):
        data["duration_seconds"] = shots[-1]["end"]
    return data


def run(p: Project) -> dict:
    meta = p.meta
    settings = meta["settings"]
    video = p.source_video()
    script = p.script_text()

    if video:
        p.progress("understand", "Uploading video to Seed (Files API)…")
        prompt = VIDEO_PROMPT
        if script:
            prompt += "\n\nThe original script is provided for accurate dialogue:\n\"\"\"\n" + script[:20000] + "\n\"\"\""
        res = understanding.analyze(prompt, model=settings["understanding_model"], video=str(video),
                                           fps=float(settings.get("understanding_fps") or 1.0), thinking=True)
        p.progress("understand", f"Seed answered in {res['seconds']}s — parsing")
        data = parse_json(res["text"])
        if not isinstance(data, dict):
            # one repair turn on the same response
            fix = understanding.analyze("That was not valid JSON. Reply with ONLY the JSON object.",
                                               model=settings["understanding_model"],
                                               previous_response_id=res["id"], thinking=False)
            data = parse_json(fix["text"])
        if not isinstance(data, dict):
            raise RuntimeError("Video understanding did not return JSON: " + res["text"][:400])
        data["_model"] = res["model"]
        data["_heard_audio"] = res["audio"]
    else:
        p.progress("understand", "Breaking the script into shots…")
        data = llm_json(SCRIPT_SYSTEM, "SCRIPT:\n\"\"\"\n" + script[:40000] + "\n\"\"\"", temperature=0.3, max_tokens=16000)

    data = _normalise(data)
    p.write("01_understanding.json", data)
    return {"shots": len(data["shots"]), "characters": len(data["characters"]), "locations": len(data["locations"])}
