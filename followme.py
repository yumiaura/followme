#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan recent Python repositories, grade authors, and follow top candidates."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGING = {
    "handlers": [logging.StreamHandler()],
    "format": "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s",
    "level": logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def build_grade_prompt(
    settings: dict[str, Any],
    target: dict[str, Any],
    digest: str,
    profile_analysis: str,
) -> tuple[str, str]:
    system = (
        "You are a strict software engineering reviewer. "
        "You analyze repository and file summaries. "
        "Be concrete, compact, and evidence-based. "
        "Do not inflate scores without clear signals."
    )
    prompt = (
        "Analyze the provided project digest and profile analysis.\n"
        "Return ONLY one-line JSON with keys: grade, comment, verdict, risk_level, evidence.\n"
        "Rules:\n"
        "- grade: float from 1.0 to 10.0\n"
        "- comment: max 18 words, describe what repository is about, not why score was assigned\n"
        "- verdict: one of weak, fair, good, strong, excellent\n"
        "- risk_level: one of low, medium, high\n"
        "- evidence: array of 3 short strings\n"
        f"- Write comment and evidence in language: {settings['output_language']}\n\n"
        "Use this anchor scale:\n"
        "1.0 broken or extremely weak code\n"
        "3.0 weak junior-level quality\n"
        "5.0 workable middle-level quality\n"
        "7.0 solid middle+/senior- signals\n"
        "8.0 strong production-quality signals\n"
        "9.0 clear senior-level quality\n"
        "10.0 exceptional, rare, truly impressive engineering quality; use only if the code genuinely surprises you\n\n"
        "Important scoring rules:\n"
        "- Do not give 9.0+ without strong engineering evidence\n"
        "- If hardcoded keys, tokens, passwords, or other secrets are found in code, this is a major negative signal and should seriously reduce the score\n"
        "- Evaluate only from the provided digest and profile analysis\n"
        "- Do not hallucinate missing files, tests, CI, or architecture\n\n"
        f"target_label={target['label']}\n"
        f"source_kind={target['source_kind']}\n"
        f"source_value={target['source_value']}\n\n"
        f"profile_analysis:\n{profile_analysis}\n\n"
        f"digest:\n{digest}"
    )
    return system, prompt


def build_profile_prompt(settings: dict[str, Any], target: dict[str, Any], digest: str) -> tuple[str, str]:
    system = (
        "You are a principal engineer performing concise but deep repository review. "
        "Your task is to infer repository behavior and developer style from repository and file summaries. "
        "Produce structured markdown only. "
        "Be concrete, evidence-based, and do not hallucinate missing files."
    )
    prompt = (
        "Analyze the project digest below. Respond in concise markdown with sections:\n"
        "1) What this repository does\n"
        "2) Architecture and structure\n"
        "3) Developer style\n"
        "4) Self-documenting code\n"
        "5) Comments and docstrings\n"
        "6) Python usage style\n"
        "7) Functional style vs OOP\n"
        "8) Reliability and error handling\n"
        "9) Security\n"
        "10) Logging and observability\n"
        "11) PEP 8 and readability\n"
        "12) Best files or patterns noticed\n"
        "13) Risks and concrete improvements\n"
        "14) Developer portrait\n"
        "15) Profile summary\n\n"
        "Section requirements:\n"
        "- In 'What this repository does', briefly explain in 1-3 sentences what the repository appears to do based only on the provided digest\n"
        "- In 'Developer style', describe whether the author looks pragmatic, systematic, script-like, engineering-oriented, minimalistic, verbose, overly clever, or simplicity-driven\n"
        "- In 'Self-documenting code', evaluate whether variable, function, class, and module names explain the logic clearly without relying on comments\n"
        "- In 'Comments and docstrings', evaluate whether comments are useful or noisy, whether functions/classes/modules use docstrings, and whether docstrings describe intent or contracts\n"
        "- Also mention whether there are emoji, icons, or decorative symbols in code/comments/log messages, and how they are used\n"
        "- In 'Python usage style', describe whether the author uses Python idiomatically or writes in a style imported from other languages\n"
        "- Mention signals such as type hints, dataclass usage, comprehensions, generators, pathlib, context managers, typing usage, enum, stdlib fluency, and code organization\n"
        "- Include observations that help characterize the developer's Python style even if they do not directly affect the score\n"
        "- In 'Functional style vs OOP', explain whether the code is mostly procedural, functional, or object-oriented, and whether that choice fits the task well\n"
        "- In 'Reliability and error handling', evaluate input validation, try/except usage, failure handling, and whether exceptions are handled too broadly or too weakly\n"
        "- In 'Security', explicitly check for signs of hardcoded keys, passwords, tokens, secrets, credential-like values, unsafe subprocess usage, shell=True, eval, exec, insecure SQL composition, unsafe file handling, or risky user input handling\n"
        "- If any hardcoded secrets are present, call this out explicitly as a major negative issue\n"
        "- If no secret-like material is visible, explicitly say so\n"
        "- In 'Logging and observability', explain whether the code uses logging or print, how mature the logging looks, and whether logs contain context and levels\n"
        "- If print is used instead of logging where structured logging would be expected, mention it as a weaker engineering signal\n"
        "- In 'PEP 8 and readability', comment on naming consistency, line length, formatting consistency, readability of blocks, and visible style discipline\n"
        "- If precise PEP 8 validation is impossible from the digest alone, say that clearly and then describe visible signals only\n"
        "- In 'Developer portrait', summarize what kind of Python developer this appears to be, what they understand well, and what their main weaknesses are\n"
        "- In 'Profile summary', provide a short neutral summary without any numeric scoring\n\n"
        "Response rules:\n"
        f"- Write the whole response in language: {settings['output_language']}\n"
        "- Do not assign any numeric grade or level labels in this profile response\n"
        "- Focus on evidence from provided files only\n"
        "- Do not hallucinate missing files\n"
        "- Avoid vague statements like 'the code looks good overall'; always explain which visible signals support the conclusion\n"
        "- Clearly separate traits that affect engineering quality from traits that mainly describe style\n"
        "- If evidence is limited, say so explicitly\n\n"
        f"target_label={target['label']}\n"
        f"source_kind={target['source_kind']}\n"
        f"source_value={target['source_value']}\n\n"
        f"digest:\n{digest}"
    )
    return system, prompt


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from .env file."""

    github_token: str
    follow_y: float
    scan_limit: int
    language: str
    output_language: str
    max_stars: int
    infinite_sleep_seconds: float
    results_csv: Path
    data_dir: Path
    repo_dir: Path
    code_style_dir: Path
    codecat_dir: Path | None
    request_timeout_seconds: int
    dry_run: bool


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
        key = key.strip()
        value = raw_value.strip().strip("'\"")
        values[key] = value
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


def load_settings(project_root: Path) -> Settings:
    """Load and normalize runtime settings."""
    env_values = parse_env_file(project_root / ".env")
    github_token = read_setting("GITHUB_TOKEN", env_values, required=True)
    follow_y = float(read_setting("FOLLOW_Y", env_values, default="7.5"))
    scan_limit = max(1, int(read_setting("FOLLOW_SCAN_LIMIT", env_values, default="100")))
    language = read_setting(
        "FOLLOW_LANGUAGE",
        env_values,
        default=read_setting("FOLLOWME_LANGUAGE", env_values, default="Python"),
    )
    output_language = read_setting("FOLLOW_OUTPUT_LANGUAGE", env_values, default="English")
    max_stars = max(0, int(read_setting("MAX_STARS", env_values, default="100")))
    infinite_sleep_seconds = max(
        0.0,
        float(read_setting("FOLLOW_INFINITE_SLEEP_SECONDS", env_values, default="600")),
    )
    results_csv = project_root / read_setting("FOLLOW_RESULTS_CSV", env_values, default="data/results.csv")
    data_dir = project_root / "data"
    repo_dir = data_dir / "repo"
    code_style_dir = data_dir / "code_style"
    codecat_dir = None
    codecat_dir_raw = read_setting("CODECAT_DIR", env_values, default="")
    if codecat_dir_raw:
        codecat_dir = Path(codecat_dir_raw).resolve()
    request_timeout_seconds = max(5, int(read_setting("FOLLOW_HTTP_TIMEOUT", env_values, default="30")))
    dry_run = parse_bool(read_setting("FOLLOW_DRY_RUN", env_values, default="false"), default=False)
    return Settings(
        github_token=github_token,
        follow_y=follow_y,
        scan_limit=scan_limit,
        language=language,
        output_language=output_language,
        max_stars=max_stars,
        infinite_sleep_seconds=infinite_sleep_seconds,
        results_csv=results_csv,
        data_dir=data_dir,
        repo_dir=repo_dir,
        code_style_dir=code_style_dir,
        codecat_dir=codecat_dir,
        request_timeout_seconds=request_timeout_seconds,
        dry_run=dry_run,
    )


def auth_headers(token: str) -> dict[str, str]:
    """Build standard GitHub API headers."""
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "followme-grader",
    }


def github_request(
    method: str,
    path: str,
    token: str,
    timeout_seconds: int,
    params: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """Execute GitHub request and return status + parsed JSON body if possible."""
    url = f"{GITHUB_API}{path}"
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"
    request = urllib.request.Request(url=url, method=method, headers=auth_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.getcode()
            raw_body = response.read().decode("utf-8", errors="replace")
            if not raw_body:
                return status_code, None
            return status_code, json.loads(raw_body)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = {"raw": raw}
        return exc.code, body


def fetch_recent_python_repositories(settings: Settings) -> list[dict[str, Any]]:
    """Fetch the latest Python repositories using GitHub Search API."""
    repositories: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_page = 100
    page = 1
    query = f"language:{settings.language} stars:<{settings.max_stars}"
    while len(repositories) < settings.scan_limit:
        status_code, body = github_request(
            method="GET",
            path="/search/repositories",
            token=settings.github_token,
            timeout_seconds=settings.request_timeout_seconds,
            params={
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": per_page,
                "page": page,
            },
        )
        if status_code != 200:
            logger.error(f"Search API failed ({status_code}): {body}")
            break
        items = body.get("items", []) if isinstance(body, dict) else []
        if not items:
            break
        for item in items:
            full_name = str(item.get("full_name", "")).strip()
            owner_login = str(item.get("owner", {}).get("login", "")).strip()
            clone_url = str(item.get("clone_url", "")).strip()
            if not full_name or not owner_login or not clone_url or full_name in seen:
                continue
            seen.add(full_name)
            repositories.append(
                {
                    "full_name": full_name,
                    "owner_login": owner_login,
                    "clone_url": clone_url,
                    "html_url": str(item.get("html_url", "")),
                    "stargazers_count": int(item.get("stargazers_count", 0)),
                    "pushed_at": str(item.get("pushed_at", "")),
                }
            )
            if len(repositories) >= settings.scan_limit:
                break
        page += 1
    logger.info(f"Fetched {len(repositories)} repositories for scan")
    return repositories


def reset_repo_dir(repo_dir: Path) -> None:
    """Delete and recreate repository work directory."""
    if repo_dir.exists():
        shutil.rmtree(repo_dir)


def clone_shallow_repository(clone_url: str, target_dir: Path) -> tuple[bool, str]:
    """Clone repository with depth=1 into target directory."""
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone", "--depth", "1", clone_url, str(target_dir)]
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
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git clone failed"
        return False, message
    return True, ""


def list_python_files(repo_dir: Path) -> list[Path]:
    """Return all .py files in repository."""
    files = [path for path in repo_dir.rglob("*.py") if path.is_file()]
    files.sort()
    return files


def build_repository_digest(repo_root: Path, python_files: list[Path], max_files: int = 25) -> str:
    """Build compact digest from python file list and short snippets."""
    selected = python_files[:max_files]
    lines: list[str] = []
    lines.append(f"python_file_count={len(python_files)}")
    for file_path in selected:
        relative = file_path.relative_to(repo_root)
        lines.append(f"file={relative}")
        try:
            file_lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for snippet_line in file_lines[:30]:
            lines.append(f"  {snippet_line[:200]}")
    if len(python_files) > max_files:
        lines.append(f"... truncated additional files: {len(python_files) - max_files}")
    return "\n".join(lines)


def ensure_codecat_importable(codecat_dir: Path | None) -> None:
    """Insert codecat module path into sys.path when needed."""
    if importlib.util.find_spec("engine_runtime") is not None:
        return
    if codecat_dir and codecat_dir.is_dir():
        codecat_str = str(codecat_dir)
        if codecat_str not in sys.path:
            sys.path.insert(0, codecat_str)
        if importlib.util.find_spec("engine_runtime") is not None:
            return
    raise RuntimeError(
        "codecat runtime is not importable. Install with: "
        "pip install git+https://github.com/yumiaura/codecat.git"
    )


def parse_grade_response(text: str) -> tuple[float, str]:
    """Extract grade/comment from model output."""
    match = JSON_OBJECT_PATTERN.search(text)
    if not match:
        return 0.0, "failed to parse model response"
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return 0.0, "invalid json in model response"
    grade_raw = payload.get("grade", 0)
    comment_raw = str(payload.get("comment", "")).strip()
    try:
        grade = float(grade_raw)
    except (TypeError, ValueError):
        grade = 0.0
    grade = max(1.0, min(10.0, grade))
    comment = comment_raw[:240] if comment_raw else "no comment"
    return grade, comment


def parse_repo_slug(full_name: str) -> tuple[str, str]:
    """Split owner/repository from full_name."""
    if "/" not in full_name:
        return "unknown", full_name
    owner, repo = full_name.split("/", 1)
    return owner.strip(), repo.strip()


def style_profile_path(settings: Settings, repository_full_name: str) -> Path:
    """Build markdown profile path data/code_style/username__reponame.md."""
    owner, repo = parse_repo_slug(repository_full_name)
    safe_owner = re.sub(r"[^A-Za-z0-9_.-]", "_", owner)
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]", "_", repo)
    return settings.code_style_dir / f"{safe_owner}__{safe_repo}.md"


def evaluate_developer_grade(
    settings: Settings,
    repository: dict[str, Any],
    digest: str,
    profile_analysis: str,
) -> tuple[float, str]:
    """Call codecat runtime and return grade + short comment."""
    ensure_codecat_importable(settings.codecat_dir)
    import engine_runtime  # type: ignore

    prompt_settings: dict[str, Any] = {"output_language": settings.output_language}
    target: dict[str, Any] = {
        "label": repository["full_name"],
        "source_kind": "github_repository",
        "source_value": repository.get("html_url", repository["full_name"]),
    }
    system_prompt, user_prompt = build_grade_prompt(prompt_settings, target, digest, profile_analysis)
    messages = [{"role": "user", "content": user_prompt}]
    response_text = engine_runtime.run_model_turn_with_tools(messages, system_prompt)
    return parse_grade_response(response_text)


def evaluate_style_profile(settings: Settings, repository: dict[str, Any], digest: str) -> str:
    """Generate detailed style and pattern profile in markdown."""
    ensure_codecat_importable(settings.codecat_dir)
    import engine_runtime  # type: ignore

    prompt_settings: dict[str, Any] = {"output_language": settings.output_language}
    target: dict[str, Any] = {
        "label": repository["full_name"],
        "source_kind": "github_repository",
        "source_value": repository.get("html_url", repository["full_name"]),
    }
    system_prompt, user_prompt = build_profile_prompt(prompt_settings, target, digest)
    messages = [{"role": "user", "content": user_prompt}]
    response_text = engine_runtime.run_model_turn_with_tools(messages, system_prompt).strip()
    if not response_text:
        return "No style profile generated."
    return response_text


def append_style_profile(
    settings: Settings,
    repository: dict[str, Any],
    python_file_count: int,
    analyzed_file_count: int,
    style_profile_markdown: str,
    grade: float,
    comment: str,
) -> None:
    """Append one analysis block to style profile markdown file."""
    settings.code_style_dir.mkdir(parents=True, exist_ok=True)
    profile_path = style_profile_path(settings, repository["full_name"])
    timestamp = datetime.now(timezone.utc).isoformat()
    block_lines = [
        "",
        f"## Analysis {timestamp}",
        "",
        f"- Repository: `{repository['full_name']}`",
        f"- Author: `{repository['owner_login']}`",
        f"- Python files found: `{python_file_count}`",
        f"- Files included in digest: `{analyzed_file_count}`",
        f"- Grade: `{grade:.2f}`",
        f"- Short comment: {comment}",
        "",
        "### Repository description and detailed profile",
        "",
        style_profile_markdown.strip(),
        "",
    ]
    if not profile_path.exists():
        header = [
            f"# Style profile: {repository['full_name']}",
            "",
            "Accumulated coding style and pattern analysis.",
            "",
        ]
        profile_path.write_text("\n".join(header + block_lines), encoding="utf-8")
        return
    with profile_path.open("a", encoding="utf-8") as file_handle:
        file_handle.write("\n".join(block_lines))


def ensure_csv_header(csv_path: Path) -> None:
    """Create CSV file with header if missing."""
    expected_header = [
        "timestamp_utc",
        "repository",
        "author",
        "grade",
        "comment",
        "starred",
        "followed",
        "status",
        "error",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.writer(file_handle)
            writer.writerow(expected_header)
        return

    with csv_path.open("r", encoding="utf-8", newline="") as file_handle:
        rows = list(csv.reader(file_handle))
    if not rows:
        with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.writer(file_handle)
            writer.writerow(expected_header)
        return
    header = rows[0]
    if header == expected_header:
        return
    if "repository_description" in header:
        drop_index = header.index("repository_description")
        migrated_rows = [expected_header]
        for row in rows[1:]:
            adjusted = list(row)
            if len(adjusted) <= drop_index:
                adjusted.extend([""] * (drop_index + 1 - len(adjusted)))
            adjusted.pop(drop_index)
            while len(adjusted) < len(expected_header):
                adjusted.append("")
            migrated_rows.append(adjusted[: len(expected_header)])
        with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.writer(file_handle)
            writer.writerows(migrated_rows)
        return


def append_csv_row(csv_path: Path, row: list[Any]) -> None:
    """Append one result row to CSV."""
    with csv_path.open("a", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle)
        writer.writerow(row)


def is_repo_starred(settings: Settings, repository_full_name: str) -> bool:
    """Check if repository is already starred."""
    status_code, _ = github_request(
        method="GET",
        path=f"/user/starred/{repository_full_name}",
        token=settings.github_token,
        timeout_seconds=settings.request_timeout_seconds,
    )
    return status_code == 204


def star_repository(settings: Settings, repository_full_name: str) -> bool:
    """Star repository if not already starred."""
    if is_repo_starred(settings, repository_full_name):
        return False
    status_code, body = github_request(
        method="PUT",
        path=f"/user/starred/{repository_full_name}",
        token=settings.github_token,
        timeout_seconds=settings.request_timeout_seconds,
    )
    if status_code == 204:
        return True
    logger.warning(f"Failed to star {repository_full_name}: {status_code} {body}")
    return False


def is_user_followed(settings: Settings, username: str) -> bool:
    """Check if current token follows username."""
    status_code, _ = github_request(
        method="GET",
        path=f"/user/following/{username}",
        token=settings.github_token,
        timeout_seconds=settings.request_timeout_seconds,
    )
    return status_code == 204


def follow_user(settings: Settings, username: str) -> bool:
    """Follow user if not followed yet."""
    if is_user_followed(settings, username):
        return False
    status_code, body = github_request(
        method="PUT",
        path=f"/user/following/{username}",
        token=settings.github_token,
        timeout_seconds=settings.request_timeout_seconds,
    )
    if status_code == 204:
        return True
    logger.warning(f"Failed to follow {username}: {status_code} {body}")
    return False


def process_repository(settings: Settings, repository: dict[str, Any]) -> None:
    """Clone, inspect, grade, write CSV, then cleanup."""
    timestamp = datetime.now(timezone.utc).isoformat()
    repo_full_name = repository["full_name"]
    author_login = repository["owner_login"]
    starred = False
    followed = False
    status = "ok"
    error_message = ""
    grade = 0.0
    comment = ""
    style_profile_markdown = ""
    python_file_count = 0
    analyzed_file_count = 0

    reset_repo_dir(settings.repo_dir)
    clone_ok, clone_error = clone_shallow_repository(repository["clone_url"], settings.repo_dir)
    if not clone_ok:
        status = "clone_error"
        error_message = clone_error
    else:
        python_files = list_python_files(settings.repo_dir)
        python_file_count = len(python_files)
        if not python_files:
            status = "no_python"
            comment = "no python files found"
        else:
            digest = build_repository_digest(settings.repo_dir, python_files)
            analyzed_file_count = min(len(python_files), 25)
            try:
                style_profile_markdown = evaluate_style_profile(settings, repository, digest)
                grade, comment = evaluate_developer_grade(
                    settings,
                    repository,
                    digest,
                    style_profile_markdown,
                )
            except Exception as exc:
                status = "analysis_error"
                error_message = f"{type(exc).__name__}: {str(exc)}"
                logger.warning(
                    f"Profile/grade analysis failed for {repo_full_name}: {error_message}"
                )
            else:
                logger.info(
                    f"Grade result for {repo_full_name}: grade={grade:.2f}, comment={comment}"
                )
                if grade > settings.follow_y and not settings.dry_run:
                    starred = star_repository(settings, repo_full_name)
                    followed = follow_user(settings, author_login)
                if grade > settings.follow_y and settings.dry_run:
                    status = "dry_run_high_grade"
    if style_profile_markdown:
        append_style_profile(
            settings=settings,
            repository=repository,
            python_file_count=python_file_count,
            analyzed_file_count=analyzed_file_count,
            style_profile_markdown=style_profile_markdown,
            grade=grade,
            comment=comment,
        )

    append_csv_row(
        settings.results_csv,
        [
            timestamp,
            repo_full_name,
            author_login,
            f"{grade:.2f}",
            comment,
            "true" if starred else "false",
            "true" if followed else "false",
            status,
            error_message,
        ],
    )
    if settings.repo_dir.exists():
        shutil.rmtree(settings.repo_dir)


def parse_single_repo_arg(raw_repo: str) -> dict[str, Any]:
    """Convert username__reponame to repository descriptor."""
    if "__" not in raw_repo:
        raise ValueError("single repo must be in username__reponame format")
    owner, repo = raw_repo.split("__", 1)
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        raise ValueError("single repo must contain both username and reponame")
    full_name = f"{owner}/{repo}"
    return {
        "full_name": full_name,
        "owner_login": owner,
        "clone_url": f"https://github.com/{full_name}.git",
        "html_url": f"https://github.com/{full_name}",
        "stargazers_count": 0,
        "pushed_at": "",
    }


def run_repositories(settings: Settings, repositories: list[dict[str, Any]]) -> None:
    """Run processing loop for provided repositories."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.code_style_dir.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(settings.results_csv)
    logger.info(
        f"Starting grading: repos={len(repositories)} threshold={settings.follow_y} csv={settings.results_csv}"
    )
    for index, repository in enumerate(repositories, start=1):
        logger.info(f"[{index}/{len(repositories)}] Processing {repository['full_name']}")
        process_repository(settings, repository)
    if settings.repo_dir.exists():
        shutil.rmtree(settings.repo_dir)
    logger.info("Scan completed")


def main() -> None:
    """Program entrypoint."""
    parser = argparse.ArgumentParser(description="Followme repository grading scan")
    parser.add_argument("-l", "--limit", type=int, default=None, help="How many repositories to scan")
    parser.add_argument("-t", "--threshold", type=float, default=None, help="Grade threshold for star/follow")
    parser.add_argument("--dry-run", action="store_true", help="Do not perform star/follow actions")
    parser.add_argument(
        "-i",
        "--infinite",
        action="store_true",
        help="Run forever: fetch scan_limit repos each cycle, then sleep between cycles",
    )
    parser.add_argument(
        "-s",
        "--sleep",
        type=float,
        default=None,
        help="Seconds to sleep between infinite cycles (default: FOLLOW_INFINITE_SLEEP_SECONDS from .env)",
    )
    parser.add_argument(
        "-r",
        "--repo",
        type=str,
        default=None,
        help="Single repository in username__reponame format",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    settings = load_settings(project_root)
    if args.limit is not None:
        settings = Settings(
            github_token=settings.github_token,
            follow_y=settings.follow_y,
            scan_limit=max(1, args.limit),
            language=settings.language,
            output_language=settings.output_language,
            max_stars=settings.max_stars,
            infinite_sleep_seconds=settings.infinite_sleep_seconds,
            results_csv=settings.results_csv,
            data_dir=settings.data_dir,
            repo_dir=settings.repo_dir,
            code_style_dir=settings.code_style_dir,
            codecat_dir=settings.codecat_dir,
            request_timeout_seconds=settings.request_timeout_seconds,
            dry_run=settings.dry_run,
        )
    if args.threshold is not None:
        settings = Settings(
            github_token=settings.github_token,
            follow_y=max(0.0, min(10.0, args.threshold)),
            scan_limit=settings.scan_limit,
            language=settings.language,
            output_language=settings.output_language,
            max_stars=settings.max_stars,
            infinite_sleep_seconds=settings.infinite_sleep_seconds,
            results_csv=settings.results_csv,
            data_dir=settings.data_dir,
            repo_dir=settings.repo_dir,
            code_style_dir=settings.code_style_dir,
            codecat_dir=settings.codecat_dir,
            request_timeout_seconds=settings.request_timeout_seconds,
            dry_run=settings.dry_run,
        )
    if args.dry_run:
        settings = Settings(
            github_token=settings.github_token,
            follow_y=settings.follow_y,
            scan_limit=settings.scan_limit,
            language=settings.language,
            output_language=settings.output_language,
            max_stars=settings.max_stars,
            infinite_sleep_seconds=settings.infinite_sleep_seconds,
            results_csv=settings.results_csv,
            data_dir=settings.data_dir,
            repo_dir=settings.repo_dir,
            code_style_dir=settings.code_style_dir,
            codecat_dir=settings.codecat_dir,
            request_timeout_seconds=settings.request_timeout_seconds,
            dry_run=True,
        )
    if args.repo:
        repository = parse_single_repo_arg(args.repo)
        run_repositories(settings, [repository])
        return
    if args.infinite:
        cycle_sleep_seconds = settings.infinite_sleep_seconds if args.sleep is None else max(0.0, args.sleep)
        cycle_index = 0
        while True:
            cycle_index += 1
            repositories = fetch_recent_python_repositories(settings)
            logger.info(
                f"Infinite cycle {cycle_index}: fetched {len(repositories)} repositories "
                f"(scan_limit={settings.scan_limit})"
            )
            run_repositories(settings, repositories)
            logger.info(f"Infinite cycle {cycle_index}: sleeping {cycle_sleep_seconds}s before next fetch")
            try:
                time.sleep(cycle_sleep_seconds)
            except KeyboardInterrupt:
                logger.info("Interrupted, stopping infinite loop")
                break
        return
    repositories = fetch_recent_python_repositories(settings)
    run_repositories(settings, repositories)


if __name__ == "__main__":
    main()
