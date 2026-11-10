"""ModelArk client helpers."""

from __future__ import annotations

from byteplussdkarkruntime import Ark

from remake.engine.config import api_key, base_url


def client(timeout: float = 600) -> Ark:
    key = api_key()
    if not key:
        raise RuntimeError("No ARK_API_KEY. Set it in remake_studio/.env and restart.")
    return Ark(base_url=base_url(), api_key=key, timeout=timeout)


def output_text(resp) -> str:
    chunks = []
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for c in getattr(item, "content", None) or []:
            if getattr(c, "type", None) == "output_text":
                chunks.append(getattr(c, "text", "") or "")
    return "".join(chunks).strip()
