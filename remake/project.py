"""A remake project lives in projects/<id>/ as plain JSON + media, so every stage's output can be
reviewed and hand-edited before the next stage runs.

  project.json            settings, source, target locale, per-stage status
  01_understanding.json   what the source contains (scenes, shots, characters, locations, dialogue)
  02_localized.json       the same story adapted to the target language / region
  03_sheets.json          character sheets + location plates (images in sheets/)
  04_shots.json           per-clip Seedance prompts, reference mapping, task ids (videos in clips/)
  final.mp4               all clips joined
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from remake.engine.config import ROOT as REMAKE_ROOT

PROJECTS_DIR = Path(os.getenv("REMAKE_PROJECTS_DIR") or (REMAKE_ROOT / "projects"))
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

STAGES = [
    ("understand", "1 · Understand source", "01_understanding.json"),
    ("localize", "2 · Localize story", "02_localized.json"),
    ("prompts", "3 · Write prompts (sheets + video)", None),
    ("sheets", "4 · Character & location sheets", "03_sheets.json"),
    ("shots", "5 · Video generation", "04_shots.json"),
    ("assemble", "6 · Assemble with ffmpeg", None),
]
STAGE_KEYS = [s[0] for s in STAGES]

DEFAULT_SETTINGS = {
    "understanding_model": "seed-2-0-lite-260428",   # hears the audio track
    "understanding_fps": 1.0,
    "llm_model": "dola-seed-2-1-turbo-260628",
    "image_model": "dola-seedream-5-0-pro-260628",
    "video_model": "dreamina-seedance-2-5-260628",
    "resolution": "720p",
    "ratio": "16:9",
    # "pack": fill each generation up to the video model's max length, cutting across scenes.
    # "scene": never put two scenes in one generation.
    "clip_mode": "pack",
    "min_clip_seconds": 4,
    "max_clip_seconds": 0,                            # 0 = the video model's max (30 s for Seedance 2.5)
    "parallel_videos": 3,
    "draft": False,
}

_locks: dict = {}
_locks_guard = threading.Lock()


def _lock(pid: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(pid, threading.RLock())


class Project:
    def __init__(self, pid: str):
        self.id = pid
        self.dir = PROJECTS_DIR / pid
        if not (self.dir / "project.json").is_file():
            raise FileNotFoundError(f"No project {pid}")

    # ---- creation / listing ---------------------------------------------------------

    @classmethod
    def create(cls, *, title: str, language: str, region: str = "", notes: str = "",
               video_path: str = "", script_text: str = "", settings: Optional[dict] = None) -> "Project":
        if not video_path and not script_text.strip():
            raise ValueError("Give a source video or a script.")
        pid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        d = PROJECTS_DIR / pid
        (d / "source").mkdir(parents=True)
        source: dict = {"type": "video" if video_path else "script"}
        if video_path:
            ext = os.path.splitext(video_path)[1] or ".mp4"
            dest = d / "source" / ("source" + ext)
            shutil.copyfile(video_path, dest)
            source["path"] = str(dest.relative_to(d))
        if script_text.strip():
            (d / "source" / "script.txt").write_text(script_text, encoding="utf-8")
            source["script"] = "source/script.txt"
        meta = {
            "id": pid, "title": title or pid, "created": time.time(),
            "source": source,
            "target": {"language": language, "region": region, "notes": notes},
            "settings": {**DEFAULT_SETTINGS, **(settings or {})},
            "stages": {k: {"status": "pending", "error": "", "progress": ""} for k in STAGE_KEYS},
        }
        (d / "project.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return cls(pid)

    @staticmethod
    def list() -> list:
        out = []
        for p in sorted(PROJECTS_DIR.iterdir(), reverse=True):
            if (p / "project.json").is_file():
                try:
                    out.append(Project(p.name).meta)
                except Exception:
                    continue
        return out

    # ---- state ----------------------------------------------------------------------

    @property
    def meta(self) -> dict:
        with _lock(self.id):
            meta = json.loads((self.dir / "project.json").read_text(encoding="utf-8"))
        meta["settings"] = {**DEFAULT_SETTINGS, **(meta.get("settings") or {})}   # older projects get new keys
        stages = meta.setdefault("stages", {})
        meta["stages"] = {k: stages.get(k) or {"status": "pending", "error": "", "progress": ""} for k in STAGE_KEYS}
        return meta

    def update(self, fn) -> dict:
        with _lock(self.id):
            meta = self.meta
            fn(meta)
            tmp = self.dir / "project.json.tmp"
            tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dir / "project.json")
            return meta

    def set_stage(self, key: str, **fields) -> None:
        self.update(lambda m: m["stages"][key].update(fields))

    def progress(self, key: str, text: str) -> None:
        self.set_stage(key, progress=text)

    # ---- stage artifacts ------------------------------------------------------------

    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    def read(self, name: str) -> Optional[dict]:
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def write(self, name: str, data) -> None:
        with _lock(self.id):
            tmp = self.dir / (name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dir / name)

    def require(self, name: str) -> dict:
        data = self.read(name)
        if data is None:
            raise RuntimeError(f"{name} is missing — run the earlier stage first.")
        return data

    def source_video(self) -> Optional[Path]:
        s = self.meta["source"]
        return self.dir / s["path"] if s.get("path") else None

    def script_text(self) -> str:
        s = self.meta["source"]
        return (self.dir / s["script"]).read_text(encoding="utf-8") if s.get("script") else ""
