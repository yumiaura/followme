#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rerun followme scan for repositories above TELEGRAM_GRADE from .env."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path


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


def load_grade_threshold(project_root: Path) -> float:
    """Load TELEGRAM_GRADE from .env with fallback."""
    env_values = parse_env_file(project_root / ".env")
    raw = env_values.get("TELEGRAM_GRADE", "9.49")
    try:
        return float(raw)
    except ValueError:
        return 9.49


def parse_grade(raw_value: str) -> float | None:
    """Parse CSV grade value."""
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def collect_repositories(project_root: Path, threshold: float) -> list[str]:
    """Collect unique repositories from results.csv above threshold."""
    csv_path = project_root / "data" / "results.csv"
    if not csv_path.exists():
        raise SystemExit(f"File not found: {csv_path}")

    rows: list[tuple[str, float]] = []
    seen_repositories: set[str] = set()
    with csv_path.open("r", encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        fieldnames = set(reader.fieldnames or [])
        required_columns = {"repository", "grade"}
        if not required_columns.issubset(fieldnames):
            raise SystemExit("CSV must contain columns: repository and grade")

        for row in reader:
            repository = str(row.get("repository", "")).strip()
            if not repository or repository in seen_repositories:
                continue
            grade = parse_grade(str(row.get("grade", "")))
            if grade is None or grade <= threshold:
                continue
            seen_repositories.add(repository)
            rows.append((repository, grade))

    rows.sort(key=lambda item: item[1], reverse=True)
    return [repository for repository, _ in rows]


def repo_to_single_arg(repository_full_name: str) -> str:
    """Convert owner/repo into owner__repo format for --repo."""
    if "/" not in repository_full_name:
        return repository_full_name
    owner, repo = repository_full_name.split("/", 1)
    return f"{owner}__{repo}"


def main() -> None:
    """Program entrypoint."""
    project_root = Path(__file__).resolve().parent.parent
    threshold = load_grade_threshold(project_root)
    repositories = collect_repositories(project_root, threshold)
    if not repositories:
        print(f"No repositories with grade > {threshold:.2f}")
        return

    print(f"Restarting scan for {len(repositories)} repositories with grade > {threshold:.2f}")
    for index, repository in enumerate(repositories, start=1):
        single_repo_arg = repo_to_single_arg(repository)
        print(f"[{index}/{len(repositories)}] Re-running: {repository}")
        command = [sys.executable, "followme.py", "-r", single_repo_arg]
        result = subprocess.run(command, cwd=project_root)
        if result.returncode != 0:
            print(f"Failed for {repository}, exit_code={result.returncode}")


if __name__ == "__main__":
    main()
