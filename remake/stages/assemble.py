"""Stage 5 — Join every clip with ffmpeg.

Clips are normalised to one resolution / frame rate / audio format first (Seedance clips can differ
slightly), then concatenated. A subtitle file in the target language is written alongside.
Output: final.mp4 (+ final.<lang>.srt).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from remake.engine.ffmpeg import get_ffmpeg_path, ffmpeg_missing_message
from remake.project import Project

SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960), "4:3": (960, 720), "3:4": (720, 960),
         "21:9": (1680, 720)}
RES_SCALE = {"480p": 480 / 720, "720p": 1.0, "1080p": 1.5}


def _probe_duration(ff: str, path: Path) -> float:
    out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _srt(clips: list, durations: list, loc: dict) -> str:
    shots = {s["id"]: s for s in loc["shots"]}
    chars = {c["id"]: c.get("name", c["id"]) for c in loc.get("characters") or []}
    entries, offset = [], 0.0
    for clip, dur in zip(clips, durations):
        lines = [(chars.get(d.get("character_id"), ""), d.get("line", ""))
                 for sid in clip["shot_ids"] for d in shots[sid].get("dialogue") or [] if d.get("line")]
        if lines:   # spread a clip's lines evenly over it — approximate, meant as a starting point to retime
            step = dur / len(lines)
            for i, (who, text) in enumerate(lines):
                entries.append((offset + i * step, offset + (i + 1) * step - 0.1, text))
        offset += dur
    return "\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(entries, 1))


def run(p: Project) -> dict:
    ff = get_ffmpeg_path()
    if not ff:
        raise RuntimeError(ffmpeg_missing_message())
    settings = p.meta["settings"]
    state = p.require("04_shots.json")
    clips = state["clips"]
    missing = [c["id"] for c in clips if not (c.get("video") and p.path(c["video"]).is_file())]
    if missing:
        raise RuntimeError("Clips not rendered yet: " + ", ".join(missing))

    w, h = SIZES.get(settings.get("ratio"), (1280, 720))
    k = RES_SCALE.get(settings.get("resolution"), 1.0)
    w, h = int(w * k) // 2 * 2, int(h * k) // 2 * 2
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24"

    durations = []
    with tempfile.TemporaryDirectory(prefix="remake-") as tmp:
        parts = []
        for i, c in enumerate(clips, 1):
            p.progress("assemble", f"Normalising {i}/{len(clips)}")
            out = Path(tmp) / f"{i:03d}.mp4"
            cmd = _normalise_cmd(ff, p.path(c["video"]), vf, out)
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg failed on {c['id']}: {r.stderr[-1500:]}")
            parts.append(out)
            durations.append(_probe_duration(ff, out))

        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{x}'\n" for x in parts), encoding="utf-8")
        final = p.path("final.mp4")
        p.progress("assemble", "Joining clips")
        r = subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                            "-movflags", "+faststart", str(final)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg concat failed: " + r.stderr[-1500:])

    loc = p.read("02_localized.json") or {"shots": [], "characters": []}
    lang = "".join(ch for ch in (loc.get("language") or "target").lower() if ch.isalnum())[:12] or "target"
    srt = p.path(f"final.{lang}.srt")
    srt.write_text(_srt(clips, durations, loc), encoding="utf-8")
    p.write("05_final.json", {"video": "final.mp4", "subtitles": srt.name, "seconds": round(sum(durations), 2),
                              "clips": [{"id": c["id"], "seconds": d} for c, d in zip(clips, durations)]})
    return {"final": str(final), "seconds": round(sum(durations), 1), "subtitles": str(srt)}


def _has_audio(ff: str, path: Path) -> bool:
    out = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    return "Audio:" in out


def _normalise_cmd(ff: str, src: Path, vf: str, out: Path) -> list:
    """Same codec / size / fps / audio layout for every clip so the concat can stream-copy.
    Clips without an audio track get silence, so the joined audio stays in sync."""
    common = ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-ar", "48000", "-ac", "2"]
    if _has_audio(ff, src):
        return [ff, "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0", *common, str(out)]
    return [ff, "-y", "-i", str(src), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest", *common, str(out)]

