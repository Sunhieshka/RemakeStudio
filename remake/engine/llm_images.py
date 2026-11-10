"""Make images safe to send to Seed LLM (the prompt-writing model).

Seed LLM's vision input rejects any image over 10 MiB
(InvalidParameter.OversizeImage). Reference images often exceed that — e.g. an
asset group image whose public TOS URL points at an 18 MiB original — while
Seedance and Seedream accept them fine. The LLM only needs to *see* the image to
write a prompt, so an oversized one is downscaled to a JPEG (max 2048 px side,
typically a few hundred KB) for the LLM call only; the generation models keep
receiving the original.
"""

import base64
import hashlib
import os
import subprocess
import tempfile
import threading
import urllib.request
from collections import OrderedDict

LLM_IMAGE_LIMIT = 9 * 1024 * 1024       # bytes; Seed LLM's hard limit is 10 MiB
DOWNLOAD_TIMEOUT_S = 90
_cache: "OrderedDict[str, str]" = OrderedDict()
_lock = threading.Lock()


def _remember(key: str, value: str) -> str:
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > 64:
            _cache.popitem(last=False)
    return value


def _cached(key: str):
    with _lock:
        return _cache.get(key)


def _shrink(raw: bytes) -> str:
    from remake.engine.ffmpeg import ffmpeg_missing_message, get_ffmpeg_path

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("A reference image is over Seed LLM's 10 MiB limit and can't be downscaled: " + ffmpeg_missing_message())
    with tempfile.TemporaryDirectory(prefix="llm-img-") as tmp:
        src = os.path.join(tmp, "in")
        with open(src, "wb") as f:
            f.write(raw)
        for side, quality in ((2048, 3), (1536, 4), (1024, 6)):
            out = os.path.join(tmp, f"out-{side}.jpg")
            scale = f"scale='if(gt(iw,ih),min({side},iw),-2)':'if(gt(iw,ih),-2,min({side},ih))'"
            p = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", src, "-frames:v", "1", "-vf", scale,
                                "-q:v", str(quality), out], capture_output=True, text=True)
            if p.returncode != 0 or not os.path.isfile(out):
                raise RuntimeError(f"A reference image is over Seed LLM's 10 MiB limit and could not be downscaled: {(p.stderr or '').strip()[-300:]}")
            data = open(out, "rb").read()
            if len(data) <= LLM_IMAGE_LIMIT:
                return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
    raise RuntimeError("A reference image is too large for Seed LLM even after downscaling.")


def fit_for_llm(image: str) -> str:
    """Returns `image` unchanged when it is within Seed LLM's limit, otherwise a
    downscaled JPEG data URL. Accepts data URLs and http(s) URLs; anything else
    (e.g. asset:// handles) is passed through."""
    image = (image or "").strip()
    if not image:
        return image
    if image.startswith("data:"):
        _head, _, b64 = image.partition(",")
        if len(b64) * 3 // 4 <= LLM_IMAGE_LIMIT:
            return image
        key = "data:" + hashlib.sha1(b64[:4096].encode() + str(len(b64)).encode()).hexdigest()
        hit = _cached(key)
        return hit or _remember(key, _shrink(base64.b64decode(b64)))
    if not image.startswith(("http://", "https://")):
        return image
    hit = _cached(image)
    if hit:
        return hit
    # Cheap check first: most references are small, and their URL can be sent as-is.
    try:
        req = urllib.request.Request(image, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            length = int(resp.headers.get("Content-Length") or 0)
        if 0 < length <= LLM_IMAGE_LIMIT:
            return _remember(image, image)
    except Exception:
        pass
    req = urllib.request.Request(image, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
        raw = resp.read()
    if len(raw) <= LLM_IMAGE_LIMIT:
        return _remember(image, image)
    return _remember(image, _shrink(raw))


def fit_all_for_llm(images: list) -> list:
    from concurrent.futures import ThreadPoolExecutor

    images = list(images or [])
    if len(images) <= 1:
        return [fit_for_llm(x) for x in images]
    with ThreadPoolExecutor(max_workers=min(6, len(images))) as pool:
        return list(pool.map(fit_for_llm, images))
