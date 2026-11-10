"""Seedance video tasks and Seed LLM prompt optimisation (Seedance 2.5 prompt-optimizer skill)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from remake.engine.ark import client, output_text
from remake.engine.llm_images import fit_all_for_llm
from remake.engine.models import DEFAULTS, VIDEO_MODELS, prompt_model

SD25_PE_SKILL = (Path(__file__).parent / "skills" / "sd25_pe_skill.md").read_text(encoding="utf-8").strip()
DRAFT_RESOLUTION = "480p"
_EXTEND_INTENT = re.compile(r"\bextend(s|ed|ing)?\b|\bcontinue the (story|video)\b", re.IGNORECASE)


def _system_instruction(ref_count: int, role_lines: list) -> str:
    if ref_count:
        refs_line = (f"You are given {ref_count} reference image{'s' if ref_count != 1 else ''}.\n"
                     "Preserve identity and style consistently across the entire video based on the reference images.\n")
    else:
        refs_line = "No reference images are given; do not invent [Image N] references.\n"
    return (
        "You are writing a single prompt for an AI-native film video generation model.\n" + refs_line +
        "Your goal is to structure the prompt as clearly and strongly as possible so the model can generate the best possible video result.\n"
        "Use the user's content to define the action, setting, camera, blocking, sound cues, dialogue, pacing, and visual continuity.\n"
        "If any dialogue is present, the character must clearly lip-sync with the dialogue.\n"
        "Use the SD25 prompt optimizer skill below for prompt structure and task shaping.\n"
        "Prefer a prompt that is concrete, chronological, visually legible, and easy for the generation model to execute.\n"
        "Return one production-ready prompt only. No markdown, no quotes around the full answer, no explanations.\n\n"
        "Reference image role mapping:\n" + ("\n".join(role_lines) or "No explicit per-image role mapping was provided.") +
        "\n\nSD25 PROMPT OPTIMIZER SKILL:\n" + SD25_PE_SKILL
    )


def refine_video_prompt(*, ui_content: str, images: list, roles: Optional[list] = None) -> str:
    refs = [str(x).strip() for x in images or [] if str(x).strip()]
    role_lines = [f"Image {i + 1}: {str(r).strip()}." for i, r in enumerate((roles or [])[:len(refs)]) if str(r).strip()]
    content = [{"type": "input_text", "text": f"User content: {ui_content.strip()}"}]
    for url in fit_all_for_llm(refs):
        content.append({"type": "input_image", "detail": "high", "image_url": url})
    resp = client(600).responses.create(
        model=prompt_model(),
        input=[{"role": "system", "content": _system_instruction(len(refs), role_lines)},
               {"role": "user", "content": content}],
        temperature=0.2)
    return output_text(resp) or ui_content.strip()


def create_video_task(*, prompt: str, reference_images: list, ratio: Optional[str] = None,
                      resolution: Optional[str] = None, duration: Optional[int] = None,
                      model: Optional[str] = None, draft: bool = False, seed: Optional[int] = None) -> str:
    model_id = (model or "").strip() or DEFAULTS["video_model"]
    content = [{"type": "text", "text": prompt}]
    for url in reference_images:
        content.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
    kwargs = {"model": model_id, "content": content, "generate_audio": True, "return_last_frame": True,
              "resolution": resolution, "duration": duration, "seed": seed, "watermark": False,
              "ratio": ratio or "16:9"}
    if VIDEO_MODELS.get(model_id, {}).get("label") == "Seedance 2.5" and reference_images:
        kwargs["omni_reference_task_type"] = "auto"     # multi-reference generation
    if draft:
        kwargs.update(draft=True, resolution=DRAFT_RESOLUTION)
    task = client().content_generation.tasks.create(**kwargs)
    return getattr(task, "id", "")


def get_video_task(*, task_id: str) -> dict:
    task = client().content_generation.tasks.get(task_id=task_id)
    content, error = getattr(task, "content", None), getattr(task, "error", None)
    return {
        "id": getattr(task, "id", ""),
        "status": getattr(task, "status", ""),
        "video_url": getattr(content, "video_url", "") if content else "",
        "error": {"code": getattr(error, "code", "") if error else "",
                  "message": getattr(error, "message", "") if error else ""},
    }
