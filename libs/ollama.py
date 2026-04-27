#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ollama HTTP client helpers."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_OLLAMA_PORT = 11434

logger = logging.getLogger(__name__)


def normalize_ollama_url(raw_url: str) -> str:
    """Normalize Ollama URL, adding scheme and default port when needed."""
    value = raw_url.strip() or f"http://localhost:{DEFAULT_OLLAMA_PORT}"
    if "://" not in value:
        value = f"http://{value}"
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid OLLAMA_URL: {raw_url}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"Invalid OLLAMA_URL: {raw_url}")
    port = parsed.port or DEFAULT_OLLAMA_PORT
    return urllib.parse.urlunparse((parsed.scheme, f"{host}:{port}", "", "", "", "")).rstrip("/")


def ensure_ollama_available(settings: dict[str, Any]) -> None:
    """Ensure Ollama is reachable and configured model exists."""
    url = f"{settings['ollama_url']}/api/tags"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=settings["request_timeout_seconds"]) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {settings['ollama_url']}: {type(exc).__name__}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama /api/tags returned invalid JSON: {exc}") from exc

    available_models = {
        str(item.get("name", "")).strip()
        for item in payload.get("models", [])
        if isinstance(item, dict)
    }
    if settings["ollama_model"] not in available_models:
        installed = sorted(model for model in available_models if model)
        raise RuntimeError(
            f"Model '{settings['ollama_model']}' is not installed in Ollama. "
            f"Installed: {installed}"
        )


def ollama_generate(
    settings: dict[str, Any],
    prompt: str,
    system: str,
    temperature: float = 0.2,
    call_tag: str = "generate",
) -> str:
    """Call Ollama /api/generate and return response text."""
    payload = {
        "model": settings["ollama_model"],
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": temperature},
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{settings['ollama_url']}/api/generate",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    timeout_seconds = max(180, settings["request_timeout_seconds"])
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTPError {exc.code}: {body_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot call Ollama: {type(exc).__name__}: {exc}") from exc

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {exc}: {raw_text[:500]}") from exc

    prompt_tokens = parsed.get("prompt_eval_count")
    output_tokens = parsed.get("eval_count")
    if isinstance(prompt_tokens, int) and isinstance(output_tokens, int):
        logger.info(
            "ollama token usage "
            f"[{call_tag}]: prompt_tokens={prompt_tokens} output_tokens={output_tokens} "
            f"total={prompt_tokens + output_tokens}"
        )
    response_text = str(parsed.get("response", "")).strip()
    if not response_text:
        raise RuntimeError("Ollama returned an empty response")
    return response_text


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
