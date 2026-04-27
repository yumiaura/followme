#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt rendering and grade response parsing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined


JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
PROFILE_SYSTEM_PROMPT = (
    "You are a principal engineer performing concise but deep repository review. "
    "Produce structured markdown only."
)
GRADE_SYSTEM_PROMPT = (
    "You are a strict software engineering reviewer. "
    "Return only the requested one-line JSON object."
)


def render_prompt_template(template_path: Path, context: dict[str, Any]) -> str:
    """Render one Jinja prompt template."""
    template_dir = template_path.parent
    template_name = template_path.name
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    template = environment.get_template(template_name)
    return template.render(**context).strip()


def build_profile_prompt(
    settings: dict[str, Any],
    target: dict[str, Any],
    digest: str,
) -> tuple[str, str]:
    """Render profile prompt pair."""
    prompt = render_prompt_template(
        Path(settings["md_prompt_template_path"]),
        {"settings": settings, "target": target, "digest": digest},
    )
    return PROFILE_SYSTEM_PROMPT, prompt


def build_grade_prompt(
    settings: dict[str, Any],
    target: dict[str, Any],
    profile_markdown: str,
) -> tuple[str, str]:
    """Render grade prompt pair."""
    prompt = render_prompt_template(
        Path(settings["csv_prompt_template_path"]),
        {
            "settings": settings,
            "target": target,
            "profile_markdown": profile_markdown,
        },
    )
    return GRADE_SYSTEM_PROMPT, prompt


def normalize_comment_text(raw_comment: str) -> str:
    """Normalize model comment to compact one-line text."""
    text = raw_comment.strip()
    if not text:
        return "no comment"
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    if "###" in text:
        text = text.split("###", 1)[0].strip()
    if "## " in text:
        text = text.split("## ", 1)[0].strip()
    text = text.strip(" -*#")
    if not text:
        return "no comment"
    return text[:240]


def parse_grade_response(text: str) -> dict[str, Any]:
    """Extract grade payload from model JSON response."""
    match = JSON_OBJECT_PATTERN.search(text)
    if not match:
        return {
            "grade": 0.0,
            "comment": "failed to parse model response",
            "verdict": "weak",
            "risk_level": "high",
            "evidence": [],
            "raw_response": text,
        }
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {
            "grade": 0.0,
            "comment": "invalid json in model response",
            "verdict": "weak",
            "risk_level": "high",
            "evidence": [],
            "raw_response": text,
        }

    try:
        grade = float(payload.get("grade", 0.0))
    except (TypeError, ValueError):
        grade = 0.0
    grade = max(1.0, min(10.0, grade))
    verdict = str(payload.get("verdict", "fair")).strip().lower() or "fair"
    risk_level = str(payload.get("risk_level", "medium")).strip().lower() or "medium"
    evidence_raw = payload.get("evidence", [])
    if isinstance(evidence_raw, list):
        evidence = [str(item).strip()[:120] for item in evidence_raw if str(item).strip()]
    else:
        evidence = []

    return {
        "grade": grade,
        "comment": normalize_comment_text(str(payload.get("comment", ""))),
        "verdict": verdict,
        "risk_level": risk_level,
        "evidence": evidence[:5],
        "raw_response": text,
    }


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
