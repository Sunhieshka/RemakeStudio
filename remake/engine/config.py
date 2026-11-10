"""Paths and environment for the engine. Credentials come from remake_studio/.env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# Scratch space for downloaded model outputs before they are copied into a project.
CACHE_DIR = str(ROOT / "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or default


def api_key() -> str:
    return get_env("ARK_API_KEY") or ""


def base_url() -> str:
    return (get_env("ARK_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
