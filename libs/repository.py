#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repository clone and digest helpers."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import urllib.parse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from libs.github import build_git_basic_auth_header


DEFAULT_IGNORE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "env",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "coverage",
    ".coverage",
    "target",
    "bin",
    "obj",
    ".terraform",
}

logger = logging.getLogger(__name__)


def reset_repo_dir(repo_dir: Path) -> None:
    """Delete repository work directory when present."""
    if repo_dir.exists():
        shutil.rmtree(repo_dir)


def clone_repository(
    repo_url: str,
    destination: Path,
    clone_depth: int,
    github_token: str,
) -> tuple[bool, str]:
    """Clone repository with depth into destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command: list[str] = ["git"]
    auth_header = build_git_basic_auth_header(github_token)
    if auth_header and repo_url.startswith("https://"):
        command.extend(["-c", f"http.extraHeader={auth_header}"])
    command.extend(["clone", "--depth", str(max(1, clone_depth)), repo_url, str(destination)])

    git_env = os.environ.copy()
    git_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    git_env.setdefault("GIT_ASKPASS", "")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=git_env,
    )
    if result.returncode == 0:
        return True, ""

    stderr_text = (result.stderr or "").strip()
    stdout_text = (result.stdout or "").strip()
    combined = f"{stderr_text}\n{stdout_text}".strip()
    auth_hint = ""
    normalized_error = combined.lower()
    if any(
        marker in normalized_error
        for marker in [
            "could not read username",
            "authentication failed",
            "terminal prompts disabled",
            "fatal: could not read",
        ]
    ):
        auth_hint = (
            " Authentication failed in non-interactive mode. "
            "Set GITHUB_TOKEN in environment or .env for private GitHub repositories."
        )
    message = combined or "git clone failed"
    return False, f"git clone ({result.returncode}): {message}{auth_hint}"


def parse_github_full_name(raw_value: str) -> str:
    """Parse owner/repo from supported repository argument forms."""
    value = raw_value.strip()
    if "__" in value and not value.startswith(("http://", "https://")):
        owner, repo = value.split("__", 1)
        owner = owner.strip()
        repo = repo.strip()
        if owner and repo:
            return f"{owner}/{repo}"
    if value.count("/") == 1 and " " not in value and not value.endswith(".git"):
        owner, repo = value.split("/", 1)
        owner = owner.strip()
        repo = repo.strip()
        if owner and repo:
            return f"{owner}/{repo}"
    if value.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(value)
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    raise ValueError("Unsupported --repo format. Use URL, owner/repo, or owner__repo.")


def build_repo_url(raw_repo: str) -> str:
    """Build clone URL from supported repository argument forms."""
    value = raw_repo.strip()
    if value.startswith(("http://", "https://")) or value.endswith(".git"):
        return value
    full_name = parse_github_full_name(value)
    return f"https://github.com/{full_name}.git"


def make_repository_from_arg(raw_repo: str) -> dict[str, Any]:
    """Convert CLI repository argument into repository descriptor."""
    full_name = parse_github_full_name(raw_repo)
    owner_login, repo_name = full_name.split("/", 1)
    return {
        "full_name": full_name,
        "owner_login": owner_login,
        "clone_url": build_repo_url(raw_repo),
        "html_url": f"https://github.com/{full_name}",
        "stargazers_count": 0,
        "pushed_at": "",
        "name": repo_name,
    }


def sanitize_label(raw_value: str) -> str:
    """Sanitize text for filesystem labels."""
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_value.strip())
    return value.strip("._") or "analysis"


def is_hidden_path(path: Path) -> bool:
    """Return whether any relative path part is hidden."""
    return any(part.startswith(".") for part in path.parts if part not in {".", ".."})


def should_skip_dir(path: Path, include_hidden_files: bool) -> bool:
    """Return whether directory should be skipped during digest walk."""
    name = path.name
    if name in DEFAULT_IGNORE_DIR_NAMES:
        return True
    if not include_hidden_files and name.startswith("."):
        return True
    return False


def file_language_hint(file_path: Path) -> str:
    """Infer a compact language hint from file suffix."""
    suffix = file_path.suffix.lower()
    mapping = {
        ".py": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".c": "c",
        ".h": "c/header",
        ".cpp": "cpp",
        ".hpp": "cpp/header",
        ".cs": "csharp",
        ".php": "php",
        ".rb": "ruby",
        ".swift": "swift",
        ".scala": "scala",
        ".lua": "lua",
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
        ".sql": "sql",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".json": "json",
        ".ini": "ini",
        ".cfg": "config",
        ".md": "markdown",
        ".txt": "text",
    }
    return mapping.get(suffix, suffix.lstrip(".") or "text")


def priority_for_file(file_path: Path) -> tuple[int, int, str]:
    """Return digest selection priority for a file."""
    name = file_path.name.lower()
    normalized_path = str(file_path).replace("\\", "/").lower()
    priority = 50
    if name in {"readme.md", "readme.txt"}:
        priority = 0
    elif name in {"pyproject.toml", "requirements.txt", "package.json", "cargo.toml", "go.mod"}:
        priority = 1
    elif name in {"dockerfile", "compose.yaml", "docker-compose.yml"}:
        priority = 2
    elif name.startswith("test_") or "/tests/" in normalized_path:
        priority = 10
    elif file_path.suffix.lower() == ".py":
        priority = 5
    return priority, len(file_path.parts), str(file_path).lower()


def iter_candidate_files(target_path: Path, settings: dict[str, Any]) -> Iterable[Path]:
    """Yield files eligible for repository digest."""
    if target_path.is_file():
        if target_path.suffix.lower() in settings["extensions"]:
            if target_path.stat().st_size <= settings["max_file_bytes"]:
                yield target_path
        return

    for root, dirs, files in os.walk(target_path):
        root_path = Path(root)
        dirs[:] = [
            directory_name
            for directory_name in dirs
            if not should_skip_dir(root_path / directory_name, settings["include_hidden_files"])
        ]
        for file_name in sorted(files):
            file_path = root_path / file_name
            if not settings["include_hidden_files"] and is_hidden_path(file_path.relative_to(target_path)):
                continue
            if file_path.suffix.lower() not in settings["extensions"]:
                continue
            try:
                if file_path.stat().st_size > settings["max_file_bytes"]:
                    continue
            except OSError:
                continue
            yield file_path


def select_relevant_files(target_path: Path, settings: dict[str, Any]) -> list[Path]:
    """Select highest-priority files for digest."""
    files = sorted(
        iter_candidate_files(target_path, settings),
        key=lambda path: (priority_for_file(path), str(path).lower()),
    )
    return files[: settings["max_files"]]


def read_file_snippet(
    target_root: Path,
    file_path: Path,
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    """Read bounded file snippet for digest."""
    try:
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        file_size = file_path.stat().st_size
    except OSError as exc:
        logger.warning(f"Cannot read {file_path}: {exc}")
        return None

    lines = raw_text.splitlines()
    snippet = "\n".join(lines[: settings["max_lines_per_file"]])
    if len(snippet) > settings["max_chars_per_file"]:
        snippet = snippet[: settings["max_chars_per_file"]]
    root = target_root if target_root.is_dir() else file_path.parent
    relative_path = str(file_path.relative_to(root))
    return {
        "relative_path": relative_path,
        "file_size": file_size,
        "language_hint": file_language_hint(file_path),
        "content": snippet,
    }


def collect_file_snippets(repo_dir: Path, settings: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Collect bounded snippets and return selected candidate count."""
    selected_paths = select_relevant_files(repo_dir, settings)
    snippets: list[dict[str, Any]] = []
    total_chars = 0
    for file_path in selected_paths:
        snippet = read_file_snippet(repo_dir, file_path, settings)
        if not snippet:
            continue
        next_size = total_chars + len(snippet["content"])
        if snippets and next_size > settings["max_total_chars"]:
            break
        snippets.append(snippet)
        total_chars = next_size
    return snippets, len(selected_paths)


def build_digest(
    repository: dict[str, Any],
    repo_dir: Path,
    snippets: list[dict[str, Any]],
    selected_paths_count: int,
) -> str:
    """Build compact digest from selected repository snippets."""
    lines: list[str] = [
        "source_kind: github_repository",
        f"source_value: {repository.get('html_url', repository['full_name'])}",
        f"repository: {repository['full_name']}",
        f"local_path: {repo_dir}",
        f"selected_files: {len(snippets)}",
        f"initial_candidates_after_filtering: {selected_paths_count}",
        "",
    ]
    for index, snippet in enumerate(snippets, start=1):
        lines.extend(
            [
                f"## FILE {index}: {snippet['relative_path']}",
                f"language_hint: {snippet['language_hint']}",
                f"file_size_bytes: {snippet['file_size']}",
                "```",
                snippet["content"].rstrip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def build_prompt_target(repository: dict[str, Any], repo_dir: Path) -> dict[str, Any]:
    """Build prompt target payload for repository analysis."""
    return {
        "label": repository["full_name"],
        "source_kind": "github_repository",
        "source_value": repository.get("html_url", repository["full_name"]),
        "local_path": str(repo_dir),
    }


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
