"""Remake Studio web UI (stdlib HTTP server).

  GET  /                                  UI
  GET  /api/projects                      list
  GET  /api/models                        LLM / image / video / understanding model options
  POST /api/upload?name=clip.mp4          raw body -> uploads/<name>; returns {"path": ...}
  POST /api/projects                      {title, language, region, notes, video_path?, script_text?, settings?}
  GET  /api/projects/<id>                 meta + every stage JSON
  PUT  /api/projects/<id>/file/<name>     replace a stage JSON (hand edits)
  POST /api/projects/<id>/settings        {title?, settings?, target?} rename / merge into settings / target
  POST /api/projects/<id>/run             {start, until?, only?}  runs one stage (sheets/shots: only = card ids)
  GET  /p/<id>/<path>                     project media (sheets, clips, final.mp4)
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from remake import pipeline
from remake.engine import models
from remake.engine.config import ROOT as REMAKE_ROOT
from remake.project import PROJECTS_DIR, STAGE_KEYS, STAGES, Project

STATIC = Path(__file__).parent / "static"
UPLOADS = REMAKE_ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)
EDITABLE = {s[2] for s in STAGES if s[2]}
_ID = re.compile(r"^[\w-]+$")


def _project_payload(p: Project) -> dict:
    files = {name: p.read(name) for name in sorted(EDITABLE)}
    files["05_final.json"] = p.read("05_final.json")
    meta = p.meta
    meta["running"] = pipeline.is_running(p.id)
    return {"meta": meta, "files": files, "stages": [{"key": k, "label": l, "file": f} for k, l, f in STAGES]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # the UI polls project state; keep those out of the console
        if args and str(args[0]).startswith(("GET /api/projects/", "GET /p/")):
            return
        super().log_message(fmt, *args)

    # ---- helpers --------------------------------------------------------------------------------
    def _json(self, status: int, data) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _file(self, path: Path) -> None:
        if not path.is_file():
            return self._json(404, {"error": "not found"})
        size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0
            end = int(b) if b else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def _project(self, pid: str) -> Project:
        if not _ID.match(pid):
            raise FileNotFoundError(pid)
        return Project(pid)

    # ---- routes ---------------------------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        parts = [unquote(x) for x in url.path.strip("/").split("/") if x]
        try:
            if not parts:
                return self._file(STATIC / "index.html")
            if parts == ["api", "projects"]:
                return self._json(200, Project.list())
            if parts == ["api", "models"]:
                return self._json(200, models.catalog())
            if parts[:2] == ["api", "projects"] and len(parts) == 3:
                return self._json(200, _project_payload(self._project(parts[2])))
            if parts[0] == "p" and len(parts) >= 3:
                p = self._project(parts[1])
                target = (p.dir / "/".join(parts[2:])).resolve()
                if p.dir.resolve() not in target.parents:
                    return self._json(403, {"error": "forbidden"})
                return self._file(target)
        except FileNotFoundError:
            return self._json(404, {"error": "project not found"})
        self._json(404, {"error": "not found"})

    def do_PUT(self):
        parts = [unquote(x) for x in urlparse(self.path).path.strip("/").split("/") if x]
        try:
            if parts[:2] == ["api", "projects"] and len(parts) == 5 and parts[3] == "file" and parts[4] in EDITABLE:
                p = self._project(parts[2])
                if pipeline.is_running(p.id):
                    return self._json(409, {"error": "A stage is running — wait for it to finish."})
                data = json.loads(self._body() or b"null")
                p.write(parts[4], data)
                if parts[4] in ("03_sheets.json", "04_shots.json"):
                    from remake.stages import prompts
                    prompts.refresh(p)       # an edited prompt marks its sheet / clip "outdated"
                return self._json(200, {"ok": True})
        except json.JSONDecodeError as e:
            return self._json(400, {"error": f"Invalid JSON: {e}"})
        except FileNotFoundError:
            return self._json(404, {"error": "project not found"})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        parts = [unquote(x) for x in url.path.strip("/").split("/") if x]
        try:
            if parts == ["api", "upload"]:
                name = (parse_qs(url.query).get("name") or ["upload.mp4"])[0]
                safe = re.sub(r"[^\w.-]", "-", os.path.basename(name))[-80:] or "upload.mp4"
                dest = UPLOADS / f"{int(time.time())}-{uuid.uuid4().hex[:6]}-{safe}"
                n, left = 0, int(self.headers.get("Content-Length") or 0)
                with open(dest, "wb") as f:
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                        n += len(chunk)
                return self._json(200, {"path": str(dest), "bytes": n})

            body = json.loads(self._body() or b"{}")
            if parts == ["api", "projects"]:
                video_path = body.get("video_path") or ""
                if video_path and UPLOADS.resolve() not in Path(video_path).resolve().parents:
                    return self._json(400, {"error": "video_path must come from /api/upload"})
                p = Project.create(title=body.get("title", ""), language=body.get("language", "").strip(),
                                   region=body.get("region", ""), notes=body.get("notes", ""),
                                   video_path=video_path, script_text=body.get("script_text", ""),
                                   settings=body.get("settings") or {})
                if video_path:
                    os.remove(video_path)
                return self._json(200, {"id": p.id})
            if parts[:2] == ["api", "projects"] and len(parts) == 4:
                p = self._project(parts[2])
                if parts[3] == "run":
                    start, until = body.get("start"), body.get("until")
                    if start and start not in STAGE_KEYS or until and until not in STAGE_KEYS:
                        return self._json(400, {"error": "unknown stage"})
                    only = list(body.get("only") or []) or None
                    ok = pipeline.run_in_background(p, start, until or start, only=only)
                    return self._json(200 if ok else 409, {"ok": ok} if ok else {"error": "Already running."})
                if parts[3] == "settings":
                    title = (body.get("title") or "").strip() if "title" in body else None
                    if title is not None and not title:
                        raise ValueError("The project name can't be empty.")

                    def apply(m):
                        if title is not None:
                            m["title"] = title[:120]
                        m["settings"].update({k: v for k, v in (body.get("settings") or {}).items() if k in m["settings"]})
                        m["target"].update({k: v for k, v in (body.get("target") or {}).items()
                                            if k in ("language", "region", "notes")})
                    return self._json(200, self._project(parts[2]).update(apply))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except FileNotFoundError:
            return self._json(404, {"error": "project not found"})
        self._json(404, {"error": "not found"})


def serve(port: int = 8100) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Remake Studio on http://127.0.0.1:{port}/  (projects in {PROJECTS_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
