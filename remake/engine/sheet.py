"""Seed LLM JSON calls, Seedream image generation, and character-sheet prompt building."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request
import uuid
from typing import Optional

from remake.engine import sheet_prompts as P
from remake.engine.ark import client, output_text
from remake.engine.config import CACHE_DIR
from remake.engine.llm_images import fit_all_for_llm
from remake.engine.models import image_model, prompt_model

SHEET_SIZE = "2560x1440"         # 16:9 at 2K
MAX_SEEDREAM_REFS = 9
LLM_TIMEOUT_S = 180
IMAGE_TIMEOUT_S = 300
TOKENS = {"bible": 7000, "review": 7000}
LOCATION_ANCHOR = "{brief}\n\nOne location, with nothing alive anywhere in the frame. No text, no lettering, no watermark."

_RETRYABLE = ("rate", "timeout", "timed out", "429", "500", "502", "503", "504", "server", "connection")


def _with_retries(fn, attempts: int = 2):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1 or not any(k in str(e).lower() for k in _RETRYABLE):
                raise
            time.sleep(2 ** (i + 1))


def parse_json(text: str):
    """JSON object or array from a model reply (tolerates code fences and surrounding prose)."""
    t = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    for a_c, b_c in (("{", "}"), ("[", "]")):
        a, b = t.find(a_c), t.rfind(b_c)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except ValueError:
                continue
    return None


def llm_json(system: str, user: str, images: Optional[list] = None, temperature: float = 0.2,
             max_tokens: int = 6000, retries: int = 2, timeout: int = LLM_TIMEOUT_S) -> dict:
    """Seed LLM (text or vision) -> parsed JSON object, with one repair turn for invalid JSON."""
    content = [{"type": "input_text", "text": user}]
    for url in fit_all_for_llm([u for u in (images or []) if u]):
        content.append({"type": "input_image", "detail": "high", "image_url": url})
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    reply = ""
    for _ in range(2):
        resp = _with_retries(lambda: client(timeout).responses.create(
            model=prompt_model(), input=messages, temperature=temperature, thinking={"type": "disabled"},
            max_output_tokens=max_tokens), attempts=retries)
        reply = output_text(resp)
        data = parse_json(reply)
        if isinstance(data, dict):
            return data
        messages = messages + [{"role": "assistant", "content": reply or "(empty)"},
                               {"role": "user", "content": "That was not valid JSON. Reply again with ONLY the JSON object."}]
    raise RuntimeError("Seed LLM returned invalid JSON: " + (reply or "")[:300])


def seedream(prompt: str, images: Optional[list] = None, size: str = SHEET_SIZE, prefix: str = "image") -> dict:
    """Seedream text-to-image (or reference generation when images are given); saved to the cache."""
    extra = {"image": images[:MAX_SEEDREAM_REFS]} if images else {}
    resp = _with_retries(lambda: client(IMAGE_TIMEOUT_S).images.generate(
        model=image_model(), prompt=prompt, size=size, response_format="url",
        output_format="png", watermark=False, **extra))
    data = getattr(resp, "data", None) or []
    if not data or getattr(data[0], "error", None) or not getattr(data[0], "url", None):
        raise RuntimeError(f"Seedream returned no image: {getattr(data[0], 'error', '') if data else 'empty response'}")
    path = os.path.join(CACHE_DIR, f"{prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.png")
    req = urllib.request.Request(data[0].url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    return {"url": data[0].url, "path": path}


def data_url_of(path: str) -> str:
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def build_sheet_prompt(description: str) -> dict:
    """Written description -> character bible + Seedream prompt for a four-view sheet."""
    data = llm_json(P.TEXT_SHEET_ENGINEER_SYSTEM,
                    P.TEXT_SHEET_ENGINEER_USER.format(description=description.strip(), base_prompt=P.TEXT_SHEET_BASE_PROMPT),
                    temperature=0.7, max_tokens=TOKENS["bible"])
    prompt = str(data.get("image_prompt") or "").strip()
    if not prompt:
        raise RuntimeError("Seed LLM returned no sheet prompt.")
    bible = data.get("character_bible") if isinstance(data.get("character_bible"), dict) else {}
    return {"bible": bible, "prompt": prompt}


def review_sheet_prompt(bible: dict, prompt: str) -> dict:
    """Fixes contradictions (a chest print on a waist apron…) before anything is generated; never blocks."""
    try:
        data = llm_json(P.PROMPT_REVIEW_SYSTEM, P.PROMPT_REVIEW_USER.format(bible=_dump(bible), prompt=prompt),
                        max_tokens=TOKENS["review"], retries=1)
    except Exception:
        return {"bible": bible, "prompt": prompt, "fixes": []}
    new_bible = data.get("character_bible") if isinstance(data.get("character_bible"), dict) else None
    new_prompt = str(data.get("image_prompt") or "").strip()
    if not new_bible or not new_prompt:
        return {"bible": bible, "prompt": prompt, "fixes": []}
    fixes = [str(i) for i in data.get("issues_fixed") or [] if str(i).strip()]
    fixes = [i for i in fixes if not any(k in i.lower() for k in P.EXPRESSION_KEYWORDS)]
    if "neutral" not in new_prompt.lower():
        new_prompt += " Flat neutral expression with the mouth closed and no smile in every panel."
    return {"bible": new_bible, "prompt": new_prompt, "fixes": fixes}
