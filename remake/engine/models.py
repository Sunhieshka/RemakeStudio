"""Model catalog and the per-project model choice.

A stage runs inside `use(settings)`; engine calls read the project's LLM / image model through
prompt_model() and image_model(). Worker threads get the choice through pmap().
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager

LLM_MODELS = [
    {"id": "dola-seed-2-1-turbo-260628", "label": "Seed 2.1 Turbo", "note": "fast, default"},
    {"id": "seed-2-0-pro-260328", "label": "Seed 2.0 Pro", "note": "strongest reasoning, slower"},
    {"id": "seed-2-0-lite-260428", "label": "Seed 2.0 Lite", "note": "balanced"},
    {"id": "seed-2-0-mini-260428", "label": "Seed 2.0 Mini", "note": "fastest, lightest"},
]
IMAGE_MODELS = [
    {"id": "dola-seedream-5-0-pro-260628", "label": "Seedream 5.0 Pro", "note": "best quality, default"},
    {"id": "dola-seedream-5-0-flash-260915", "label": "Seedream 5.0 Flash", "note": "faster, cheaper"},
]
# Reference limits are what each model enforces: images, videos (total s), audios (total s).
VIDEO_MODELS = {
    "dreamina-seedance-2-5-260628": {"label": "Seedance 2.5", "max_duration": 30, "resolutions": ["480p", "720p", "1080p"],
                                     "max_ref_images": 30, "draft": True},
    "dreamina-seedance-2-0-260128": {"label": "Seedance 2.0", "max_duration": 15,
                                     "resolutions": ["480p", "720p", "1080p", "4k"], "max_ref_images": 9},
    "dreamina-seedance-2-0-fast-260128": {"label": "Seedance 2.0 fast", "max_duration": 15,
                                          "resolutions": ["480p", "720p"], "max_ref_images": 9},
    "dreamina-seedance-2-0-mini-260615": {"label": "Seedance 2.0 mini", "max_duration": 15,
                                          "resolutions": ["480p", "720p"], "max_ref_images": 9},
}
UNDERSTANDING_MODELS = [
    {"id": "seed-2-0-mini-260428", "label": "Seed 2.0 Mini", "audio": True, "note": "fastest · hears audio"},
    {"id": "seed-2-0-lite-260428", "label": "Seed 2.0 Lite", "audio": True, "note": "balanced · hears audio"},
    {"id": "seed-2-0-pro-260328", "label": "Seed 2.0 Pro", "audio": False, "note": "strongest reasoning · frames only"},
    {"id": "dola-seed-2-1-turbo-260628", "label": "Seed 2.1 Turbo", "audio": False, "note": "fast · frames only"},
]
DEFAULTS = {"llm_model": LLM_MODELS[0]["id"], "image_model": IMAGE_MODELS[0]["id"],
            "video_model": "dreamina-seedance-2-5-260628", "understanding_model": "seed-2-0-lite-260428"}
MIN_VIDEO_DURATION = 4

_current: contextvars.ContextVar = contextvars.ContextVar("remake_models", default=None)


def _pick(key: str, options: list) -> str:
    m = (_current.get() or {}).get(key)
    return m if any(o["id"] == m for o in options) else DEFAULTS[key]


def prompt_model() -> str:
    return _pick("llm_model", LLM_MODELS)


def image_model() -> str:
    return _pick("image_model", IMAGE_MODELS)


def video_spec(model_id: str) -> dict:
    return VIDEO_MODELS.get(model_id) or VIDEO_MODELS[DEFAULTS["video_model"]]


@contextmanager
def use(settings: dict):
    token = _current.set(dict(settings or {}))
    try:
        yield
    finally:
        _current.reset(token)


def pmap(pool, fn, items) -> list:
    """pool.map that carries the current model choice into the worker threads."""
    futures = [pool.submit(contextvars.copy_context().run, fn, it) for it in items]
    return [f.result() for f in futures]


def catalog() -> dict:
    return {
        "llm": LLM_MODELS, "image": IMAGE_MODELS, "understanding": UNDERSTANDING_MODELS,
        "video": [{"id": k, "label": v["label"], "max_duration": v["max_duration"], "resolutions": v["resolutions"]}
                  for k, v in VIDEO_MODELS.items()],
        "defaults": DEFAULTS,
    }
