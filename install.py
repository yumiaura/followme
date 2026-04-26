#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bootstrap followme: ensure pip, install dependencies, and generate .env."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_OUTPUT_LANGUAGE = "English"


def run_command(command_parts: list[str]) -> None:
    """Run command and raise on non-zero exit code."""
    result = subprocess.run(command_parts)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with code {result.returncode}: {' '.join(command_parts)}")


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse KEY=VALUE pairs from .env file."""
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


def ensure_virtualenv(project_root: Path) -> Path:
    """Create project .venv if missing and return its Python executable."""
    venv_dir = project_root / ".venv"
    venv_python = venv_dir / "bin" / "python3"
    if venv_python.exists():
        return venv_python
    print(f"Creating virtual environment at {venv_dir} ...")
    run_command([sys.executable, "-m", "venv", str(venv_dir)])
    if not venv_python.exists():
        raise RuntimeError(f"Virtual environment was created but {venv_python} is missing")
    return venv_python


def ensure_pip_available(python_executable: Path) -> None:
    """Ensure pip is available for selected Python interpreter."""
    try:
        run_command([str(python_executable), "-m", "pip", "--version"])
    except Exception:
        run_command([str(python_executable), "-m", "ensurepip", "--upgrade"])


def install_requirements(project_root: Path, python_executable: Path) -> None:
    """Install dependencies from requirements.txt."""
    requirements_path = project_root / "requirements.txt"
    run_command([str(python_executable), "-m", "pip", "install", "--upgrade", "pip"])
    run_command([str(python_executable), "-m", "pip", "install", "-r", str(requirements_path)])


def ask_input(label: str, default: str = "") -> str:
    """Prompt user for text value with optional default."""
    if default:
        prompt = f"{label} [{default}]: "
    else:
        prompt = f"{label}: "
    answer = input(prompt).strip()
    if answer:
        return answer
    return default


def normalize_ollama_url(raw_ollama_url: str) -> str:
    """Normalize Ollama URL, add scheme and default Ollama port."""
    value = raw_ollama_url.strip()
    if not value:
        value = DEFAULT_OLLAMA_URL
    if "://" not in value:
        value = f"http://{value}"
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid OLLAMA_URL: {raw_ollama_url}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"Invalid OLLAMA_URL: {raw_ollama_url}")
    port = parsed.port or 11434
    normalized = urllib.parse.urlunparse((parsed.scheme, f"{host}:{port}", "", "", "", ""))
    return normalized.rstrip("/")


def fetch_ollama_models(ollama_url: str) -> list[str]:
    """Fetch installed model names from Ollama tags endpoint."""
    tags_url = f"{ollama_url.rstrip('/')}/api/tags"
    request = urllib.request.Request(tags_url, method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        raw_body = response.read().decode("utf-8", errors="replace")
    payload = json.loads(raw_body)
    models = payload.get("models", [])
    names: list[str] = []
    for model_item in models:
        name = str(model_item.get("name", "")).strip()
        if name:
            names.append(name)
    return names


def choose_model(available_models: list[str]) -> str:
    """Ask user to choose one model from list."""
    if not available_models:
        return ask_input("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    print("\nInstalled Ollama models:")
    for index, model_name in enumerate(available_models, start=1):
        print(f"  {index}. {model_name}")
    while True:
        raw_choice = ask_input("Choose model number", "1")
        try:
            selected_index = int(raw_choice)
        except ValueError:
            print("Please enter a number.")
            continue
        if 1 <= selected_index <= len(available_models):
            return available_models[selected_index - 1]
        print("Number is out of range.")


def render_env_text(project_root: Path, overrides: dict[str, str]) -> str:
    """Render .env text from env.example template with overrides."""
    template_path = project_root / "env.example"
    if not template_path.exists():
        lines = [f"{key}={value}" for key, value in overrides.items()]
        lines.append("")
        return "\n".join(lines)

    rendered_lines: list[str] = []
    replaced_keys: set[str] = set()
    for line in template_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rendered_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        clean_key = key.strip()
        if clean_key in overrides:
            rendered_lines.append(f"{clean_key}={overrides[clean_key]}")
            replaced_keys.add(clean_key)
        else:
            rendered_lines.append(line)
    missing_keys = [key for key in overrides if key not in replaced_keys]
    if missing_keys:
        if rendered_lines and rendered_lines[-1].strip():
            rendered_lines.append("")
        rendered_lines.append("# Added by install.py")
        for key in missing_keys:
            rendered_lines.append(f"{key}={overrides[key]}")
    rendered_lines.append("")
    return "\n".join(rendered_lines)


def write_env_file(project_root: Path, env_text: str) -> None:
    """Write .env file, creating backup when file exists."""
    env_path = project_root / ".env"
    if env_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = project_root / f".env.backup_{timestamp}"
        env_path.rename(backup_path)
        print(f"Existing .env backed up to {backup_path.name}")
    env_path.write_text(env_text, encoding="utf-8")
    print(f"Generated {env_path}")


def main() -> None:
    """Program entrypoint."""
    project_root = Path(__file__).resolve().parent
    env_path = project_root / ".env"
    env_example_path = project_root / "env.example"
    existing_env_values = parse_env_file(env_path)
    template_env_values = parse_env_file(env_example_path)
    base_env_values = template_env_values.copy()
    base_env_values.update(existing_env_values)

    print("Step 1/3: Ensuring project virtual environment is available...")
    venv_python = ensure_virtualenv(project_root)
    print(f"Using Python: {venv_python}")
    ensure_pip_available(venv_python)

    print("Step 2/3: Installing dependencies from requirements.txt...")
    install_requirements(project_root, venv_python)

    print("Step 3/3: Generating .env file...")
    github_token = base_env_values.get("GITHUB_TOKEN", "")
    if env_path.exists():
        print("Existing .env detected, reusing GITHUB_TOKEN from it.")
    else:
        github_token = ask_input("GITHUB_TOKEN")
    if not github_token:
        print("GITHUB_TOKEN is required.")
        sys.exit(1)

    default_ollama_url = base_env_values.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    try:
        default_ollama_url = normalize_ollama_url(default_ollama_url)
    except ValueError:
        default_ollama_url = DEFAULT_OLLAMA_URL
    while True:
        raw_ollama_url = ask_input("OLLAMA_URL", default_ollama_url)
        try:
            ollama_url = normalize_ollama_url(raw_ollama_url)
            break
        except ValueError as exc:
            print(exc)
    try:
        models = fetch_ollama_models(ollama_url)
    except urllib.error.URLError as exc:
        print(f"Could not fetch models from {ollama_url}: {type(exc).__name__}: {exc}")
        models = []
    except Exception as exc:
        print(f"Could not parse Ollama model list: {type(exc).__name__}: {exc}")
        models = []
    ollama_model = choose_model(models)
    default_output_language = base_env_values.get("FOLLOW_OUTPUT_LANGUAGE", DEFAULT_OUTPUT_LANGUAGE)
    output_language = ask_input("FOLLOW_OUTPUT_LANGUAGE", default_output_language)

    env_text = render_env_text(
        project_root,
        {
            "GITHUB_TOKEN": github_token,
            "OLLAMA_URL": ollama_url,
            "OLLAMA_MODEL": ollama_model,
            "FOLLOW_OUTPUT_LANGUAGE": output_language,
        },
    )
    write_env_file(project_root, env_text)
    print("Initialization completed.")


if __name__ == "__main__":
    main()
