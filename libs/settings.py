#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load runtime settings for followme."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_EXTENSIONS = (
    ".py",
    ".pyi",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".swift",
    ".scala",
    ".lua",
    ".sh",
    ".bash",
    ".zsh",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ini",
    ".cfg",
    ".md",
    ".txt",
)
DEFAULT_ANALYSIS_DIR = "data/analysis"
DEFAULT_CLONE_DEPTH = 1
DEFAULT_MAX_CHARS_PER_FILE = 6000
DEFAULT_MAX_FILE_BYTES = 512 * 1024
DEFAULT_MAX_FILES = 25
DEFAULT_MAX_LINES_PER_FILE = 120
DEFAULT_MAX_TOTAL_CHARS = 70000
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_RESULTS_CSV = "data/results.csv"


def parse_bool(raw_value: str, default: bool) -> bool:
    """Parse bool-like strings from env values."""
    text = raw_value.strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse KEY=VALUE pairs from .env file without external dependencies."""
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip().strip("'\"")
    return values


def read_setting(
    key: str,
    env_values: dict[str, str],
    default: str | None = None,
    required: bool = False,
) -> str:
    """Read setting from process env, then .env map, then default."""
    process_value = os.getenv(key)
    if process_value is not None and process_value.strip():
        return process_value.strip()
    file_value = env_values.get(key)
    if file_value is not None and file_value.strip():
        return file_value.strip()
    if default is not None:
        return default
    if required:
        raise RuntimeError(f"Missing required setting: {key}")
    return ""


def split_csv_like(raw_value: str) -> list[str]:
    """Split comma-separated env setting into non-empty items."""
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def normalize_extension(raw_value: str) -> str:
    """Normalize extension value to lowercase dot-prefixed form."""
    value = raw_value.strip().lower()
    if not value:
        return value
    if not value.startswith("."):
        value = f".{value}"
    return value


def read_int_setting(
    key: str,
    env_values: dict[str, str],
    default: int,
    minimum: int,
) -> int:
    """Read bounded integer setting."""
    raw_value = read_setting(key, env_values, default=str(default))
    try:
        value = int(raw_value)
    except ValueError:
        value = default
    return max(minimum, value)


def read_float_setting(
    key: str,
    env_values: dict[str, str],
    default: float,
    minimum: float,
) -> float:
    """Read bounded float setting."""
    raw_value = read_setting(key, env_values, default=str(default))
    try:
        value = float(raw_value)
    except ValueError:
        value = default
    return max(minimum, value)


def parse_float_default(raw_value: str, fallback: float) -> float:
    """Parse optional float fallback value."""
    if not raw_value.strip():
        return fallback
    try:
        return float(raw_value)
    except ValueError:
        return fallback


def load_extensions(env_values: dict[str, str]) -> list[str]:
    """Load file extensions used for digest selection."""
    raw_extensions = read_setting("FOLLOW_EXTENSIONS", env_values, default=",".join(DEFAULT_EXTENSIONS))
    extensions = [
        normalize_extension(item)
        for item in split_csv_like(raw_extensions)
        if item.strip()
    ]
    if extensions:
        return extensions
    return list(DEFAULT_EXTENSIONS)


def load_settings(project_root: Path) -> dict[str, Any]:
    """Load and normalize runtime settings."""
    from libs.ollama import normalize_ollama_url

    env_values = parse_env_file(project_root / ".env")
    github_token = read_setting("GITHUB_TOKEN", env_values, required=True)
    # Backward compatibility for existing .env files that still use FOLLOW_Y.
    legacy_threshold = read_setting("FOLLOW_Y", env_values, default="")
    threshold_default = parse_float_default(legacy_threshold, fallback=7.5)
    follow_grade = min(
        10.0,
        read_float_setting("FOLLOW_GRADE", env_values, default=threshold_default, minimum=0.0),
    )
    star_grade = min(
        10.0,
        read_float_setting("FOLLOW_STAR_GRADE", env_values, default=threshold_default, minimum=0.0),
    )
    scan_limit = read_int_setting("FOLLOW_SCAN_LIMIT", env_values, default=100, minimum=1)
    language = read_setting(
        "FOLLOW_LANGUAGE",
        env_values,
        default=read_setting("FOLLOWME_LANGUAGE", env_values, default="Python"),
    )
    output_language = read_setting("FOLLOW_OUTPUT_LANGUAGE", env_values, default="English")
    max_stars = read_int_setting("MAX_STARS", env_values, default=100, minimum=0)
    infinite_sleep_seconds = read_float_setting(
        "FOLLOW_INFINITE_SLEEP_SECONDS",
        env_values,
        default=600.0,
        minimum=0.0,
    )
    results_csv = project_root / read_setting(
        "FOLLOW_RESULTS_CSV",
        env_values,
        default=DEFAULT_RESULTS_CSV,
    )
    analysis_dir = project_root / read_setting(
        "FOLLOW_ANALYSIS_DIR",
        env_values,
        default=DEFAULT_ANALYSIS_DIR,
    )
    data_dir = project_root / "data"
    repo_dir = data_dir / "repo"
    code_style_dir = data_dir / "code_style"
    plugins_dir = project_root / "plugins"
    md_prompt_template_path = project_root / "templates" / "PROMT_MD.j2"
    csv_prompt_template_path = project_root / "templates" / "PROMT_CSV.j2"
    request_timeout_seconds = read_int_setting(
        "FOLLOW_HTTP_TIMEOUT",
        env_values,
        default=30,
        minimum=5,
    )
    dry_run = parse_bool(read_setting("FOLLOW_DRY_RUN", env_values, default="false"), default=False)
    ollama_url = normalize_ollama_url(read_setting("OLLAMA_URL", env_values, default=DEFAULT_OLLAMA_URL))
    ollama_model = read_setting("OLLAMA_MODEL", env_values, default=DEFAULT_OLLAMA_MODEL)
    max_files = read_int_setting("FOLLOW_MAX_FILES", env_values, default=DEFAULT_MAX_FILES, minimum=1)
    max_lines_per_file = read_int_setting(
        "FOLLOW_MAX_LINES_PER_FILE",
        env_values,
        default=DEFAULT_MAX_LINES_PER_FILE,
        minimum=1,
    )
    max_chars_per_file = read_int_setting(
        "FOLLOW_MAX_CHARS_PER_FILE",
        env_values,
        default=DEFAULT_MAX_CHARS_PER_FILE,
        minimum=100,
    )
    max_total_chars = read_int_setting(
        "FOLLOW_MAX_TOTAL_CHARS",
        env_values,
        default=DEFAULT_MAX_TOTAL_CHARS,
        minimum=1000,
    )
    max_file_bytes = read_int_setting(
        "FOLLOW_MAX_FILE_BYTES",
        env_values,
        default=DEFAULT_MAX_FILE_BYTES,
        minimum=1024,
    )
    clone_depth = read_int_setting("FOLLOW_GIT_CLONE_DEPTH", env_values, default=DEFAULT_CLONE_DEPTH, minimum=1)
    include_hidden_files = parse_bool(
        read_setting("FOLLOW_INCLUDE_HIDDEN_FILES", env_values, default="false"),
        default=False,
    )
    save_digest = parse_bool(read_setting("FOLLOW_SAVE_DIGEST", env_values, default="false"), default=False)
    extensions = load_extensions(env_values)

    return {
        "project_root": str(project_root),
        "github_token": github_token,
        "follow_grade": follow_grade,
        "star_grade": star_grade,
        "scan_limit": scan_limit,
        "language": language,
        "output_language": output_language,
        "max_stars": max_stars,
        "infinite_sleep_seconds": infinite_sleep_seconds,
        "results_csv": str(results_csv),
        "analysis_dir": str(analysis_dir),
        "data_dir": str(data_dir),
        "repo_dir": str(repo_dir),
        "code_style_dir": str(code_style_dir),
        "plugins_dir": str(plugins_dir),
        "md_prompt_template_path": str(md_prompt_template_path),
        "csv_prompt_template_path": str(csv_prompt_template_path),
        "request_timeout_seconds": request_timeout_seconds,
        "dry_run": dry_run,
        "ollama_url": ollama_url,
        "ollama_model": ollama_model,
        "max_files": max_files,
        "max_lines_per_file": max_lines_per_file,
        "max_chars_per_file": max_chars_per_file,
        "max_total_chars": max_total_chars,
        "max_file_bytes": max_file_bytes,
        "clone_depth": clone_depth,
        "include_hidden_files": include_hidden_files,
        "save_digest": save_digest,
        "extensions": extensions,
    }


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
