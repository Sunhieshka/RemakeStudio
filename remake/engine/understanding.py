"""Video understanding with a Seed 2.x vision-language model.

The video goes through the ModelArk Files API; the upload names the model in
preprocess_configs.video.model, and that model decides how it is preprocessed — Seed 2.0 Mini and
Lite also extract the audio track (speech, music, sound effects); Seed 2.0 Pro and 2.1 Turbo see the
frames only. Up to 512 MB. An uploaded file is reused for 6 days for the same (file, model, fps).
Follow-up questions pass previous_response_id, so the video is not sent again.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

from remake.engine.ark import client
from remake.engine.config import api_key, base_url
from remake.engine.models import UNDERSTANDING_MODELS

MAX_VIDEO_BYTES = 512 * 1024 * 1024
MIN_FPS, MAX_FPS, DEFAULT_FPS = 0.2, 5.0, 1.0
FILE_TTL_S = 6 * 24 * 3600
UPLOAD_WAIT_S = 15 * 60
RESPONSE_TIMEOUT_S = 15 * 60

SYSTEM = (
    "You are an expert in visual understanding. Answer from what is actually in the provided video: be "
    "specific and concrete, cite timestamps for events, and say so plainly when something cannot be "
    "determined from the media. Follow the user's requested output format exactly."
)
AUDIO_NOTE = " The video's audio track is included: use speech, music and sound effects as evidence too."
NO_AUDIO_NOTE = (" You receive the video's frames only; its audio track is not given to you, although the video may "
                 "well have sound. Never claim what is said or heard, and never say the video is silent.")

_uploads: dict = {}
_uploads_lock = threading.Lock()


def _model(model_id: str) -> dict:
    m = next((x for x in UNDERSTANDING_MODELS if x["id"] == model_id), None)
    if not m:
        raise ValueError(f"Unknown understanding model: {model_id}")
    return m


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{base_url()}{path}", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=RESPONSE_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(raw).get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
        except ValueError:
            msg = raw[:600]
        raise RuntimeError(msg or f"HTTP {e.code}") from None


def _sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def upload_video(path: str, model: str, fps: float) -> str:
    """Uploads a local video to the Files API, preprocessed for `model`; returns its file_id."""
    if os.path.getsize(path) > MAX_VIDEO_BYTES:
        raise ValueError("The video is over the 512 MB limit for video understanding.")
    key = (_sha1(path), model, fps)
    with _uploads_lock:
        hit = _uploads.get(key)
    if hit and time.time() - hit[1] < FILE_TTL_S:
        return hit[0]
    ark = client(UPLOAD_WAIT_S)
    with open(path, "rb") as f:
        created = ark.files.create(file=f, purpose="user_data",
                                   preprocess_configs={"video": {"model": model, "fps": fps}})
    done = ark.files.wait_for_processing(created.id, poll_interval=2.0, max_wait_seconds=UPLOAD_WAIT_S)
    if done.status != "active":
        detail = getattr(done, "error", None) or getattr(done, "status_details", None) or ""
        raise RuntimeError(f"The video could not be processed{': ' + str(detail) if detail else ''}.")
    with _uploads_lock:
        _uploads[key] = (done.id, time.time())
    return done.id


def _output_text(data: dict) -> str:
    text = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            text += [c.get("text") or "" for c in item.get("content") or [] if c.get("type") == "output_text"]
    return "".join(text).strip()


def analyze(prompt: str, model: str, video: str = "", fps: float = DEFAULT_FPS, thinking: bool = True,
            previous_response_id: str = "") -> dict:
    """One question about a local video. A follow-up passes previous_response_id and no video."""
    m = _model(model)
    if not previous_response_id and not video:
        raise ValueError("A video is required.")
    fps = max(MIN_FPS, min(MAX_FPS, float(fps or DEFAULT_FPS)))
    started = time.time()
    content: list = []
    if video:
        content.append({"type": "input_video", "file_id": upload_video(video, m["id"], fps)})
    content.append({"type": "input_text", "text": prompt})
    body = {"model": m["id"], "input": [{"role": "user", "content": content}]}
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    else:
        body["instructions"] = SYSTEM + (AUDIO_NOTE if m["audio"] else NO_AUDIO_NOTE)
    if not thinking:
        body["thinking"] = {"type": "disabled"}
    data = _post("/responses", body)
    text = _output_text(data)
    if not text:
        raise RuntimeError("The model returned no answer.")
    return {"id": data.get("id") or "", "text": text, "model": m["id"], "audio": bool(video) and m["audio"],
            "seconds": round(time.time() - started, 1)}
