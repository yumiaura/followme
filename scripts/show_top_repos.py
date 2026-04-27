#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Print repositories from results.csv above TELEGRAM_GRADE threshold."""

from __future__ import annotations

import csv
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


def load_threshold(project_root: Path) -> float:
    """Load TELEGRAM_GRADE from .env with fallback."""
    env_values = parse_env_file(project_root / ".env")
    raw_threshold = env_values.get("TELEGRAM_GRADE", "9.49")
    try:
        return float(raw_threshold)
    except ValueError:
        return 9.49


def parse_grade(raw_value: str) -> float | None:
    """Parse CSV grade value."""
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def collect_top_rows(csv_path: Path, threshold: float) -> list[dict[str, str | float]]:
    """Collect unique repositories above threshold from results.csv."""
    with csv_path.open("r", encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        fieldnames = set(reader.fieldnames or [])
        required_columns = {"repository", "grade", "comment"}
        if not required_columns.issubset(fieldnames):
            raise SystemExit("CSV must contain columns: repository, grade, comment")

        top_rows: list[dict[str, str | float]] = []
        seen_repositories: set[str] = set()
        for row in reader:
            repository = str(row.get("repository", "")).strip()
            if not repository or repository in seen_repositories:
                continue
            grade = parse_grade(str(row.get("grade", "")))
            if grade is None or grade <= threshold:
                continue
            seen_repositories.add(repository)
            top_rows.append(
                {
                    "repository": repository,
                    "grade": grade,
                    "comment": str(row.get("comment", "")).strip(),
                }
            )
    top_rows.sort(key=lambda item: float(item["grade"]), reverse=True)
    return top_rows


def main() -> None:
    """Program entrypoint."""
    project_root = Path(__file__).resolve().parent.parent
    threshold = load_threshold(project_root)
    csv_path = project_root / "data" / "results.csv"
    if not csv_path.exists():
        raise SystemExit(f"File not found: {csv_path}")

    top_rows = collect_top_rows(csv_path, threshold)
    if not top_rows:
        print(f"No repositories with grade > {threshold:.2f}")
        return

    for row in top_rows:
        comment = str(row["comment"]).strip()
        repository = str(row["repository"])
        grade = float(row["grade"])
        if comment:
            print(f"https://github.com/{repository} - {grade:.2f} - {comment}")
        else:
            print(f"https://github.com/{repository} - {grade:.2f}")


if __name__ == "__main__":
    main()
