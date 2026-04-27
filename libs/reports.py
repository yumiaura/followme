#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV and markdown report writers."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any


RESULTS_CSV_HEADER = [
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


def ensure_parent_dir(file_path: Path) -> None:
    """Create parent directory for file path."""
    file_path.parent.mkdir(parents=True, exist_ok=True)


def ensure_csv_header(csv_path: Path) -> None:
    """Create CSV file with current header if missing."""
    ensure_parent_dir(csv_path)
    if not csv_path.exists():
        with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.writer(file_handle)
            writer.writerow(RESULTS_CSV_HEADER)
        return

    with csv_path.open("r", encoding="utf-8", newline="") as file_handle:
        rows = list(csv.reader(file_handle))
    if not rows:
        with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.writer(file_handle)
            writer.writerow(RESULTS_CSV_HEADER)
        return
    header = rows[0]
    if header == RESULTS_CSV_HEADER:
        return
    if "repository_description" not in header:
        return

    drop_index = header.index("repository_description")
    migrated_rows = [RESULTS_CSV_HEADER]
    for row in rows[1:]:
        adjusted = list(row)
        if len(adjusted) <= drop_index:
            adjusted.extend([""] * (drop_index + 1 - len(adjusted)))
        adjusted.pop(drop_index)
        while len(adjusted) < len(RESULTS_CSV_HEADER):
            adjusted.append("")
        migrated_rows.append(adjusted[: len(RESULTS_CSV_HEADER)])
    with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle)
        writer.writerows(migrated_rows)


def append_csv_row(csv_path: Path, row: list[Any]) -> None:
    """Append one result row to CSV."""
    with csv_path.open("a", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle)
        writer.writerow(row)


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text to file."""
    ensure_parent_dir(path)
    path.write_text(text, encoding="utf-8")


def parse_repo_slug(repository_full_name: str) -> tuple[str, str]:
    """Split owner/repository from full_name."""
    if "/" not in repository_full_name:
        return "unknown", repository_full_name
    owner, repo = repository_full_name.split("/", 1)
    return owner.strip(), repo.strip()


def style_profile_path(settings: dict[str, Any], repository_full_name: str) -> Path:
    """Build markdown profile path data/code_style/username__reponame.md."""
    owner, repo = parse_repo_slug(repository_full_name)
    safe_owner = re.sub(r"[^A-Za-z0-9_.-]", "_", owner)
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]", "_", repo)
    return Path(settings["code_style_dir"]) / f"{safe_owner}__{safe_repo}.md"


def build_csv_value_lines(result: dict[str, Any]) -> str:
    """Build markdown list describing current CSV row values."""
    csv_row = result.get("csv_row", [])
    if isinstance(csv_row, list) and len(csv_row) == len(RESULTS_CSV_HEADER):
        return "\n".join(
            f"- {key}: `{value}`"
            for key, value in zip(RESULTS_CSV_HEADER, csv_row, strict=False)
        )
    lines = []
    for key in RESULTS_CSV_HEADER:
        value = result.get(key, "")
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines)


def build_evidence_lines(grade_payload: dict[str, Any]) -> str:
    """Build markdown evidence list."""
    evidence = grade_payload.get("evidence", [])
    if not evidence:
        return "- none"
    return "\n".join(f"- {item}" for item in evidence)


def build_inspected_file_lines(snippets: list[dict[str, Any]]) -> str:
    """Build markdown inspected file list."""
    if not snippets:
        return "- none"
    return "\n".join(f"- `{snippet['relative_path']}`" for snippet in snippets)


def append_markdown_report(
    settings: dict[str, Any],
    repository: dict[str, Any],
    result: dict[str, Any],
    snippets: list[dict[str, Any]],
    selected_paths_count: int,
    grade_payload: dict[str, Any],
) -> Path:
    """Append one analysis block to repository markdown profile."""
    Path(settings["code_style_dir"]).mkdir(parents=True, exist_ok=True)
    profile_path = style_profile_path(settings, repository["full_name"])
    block_lines = [
        "",
        f"## Analysis {result['timestamp_utc']}",
        "",
        "### CSV values",
        "",
        build_csv_value_lines(result),
        "",
        "### Analysis metadata",
        "",
        f"- Verdict: `{grade_payload.get('verdict', '')}`",
        f"- Risk level: `{grade_payload.get('risk_level', '')}`",
        f"- Files included in digest: `{len(snippets)}`",
        f"- Candidate files after filters: `{selected_paths_count}`",
        "",
        "### Evidence",
        "",
        build_evidence_lines(grade_payload),
        "",
        "### Files included in digest",
        "",
        build_inspected_file_lines(snippets),
        "",
        "### Repository description and detailed profile",
        "",
        result.get("profile_markdown", "").strip() or "No style profile generated.",
        "",
    ]
    if not profile_path.exists():
        header = [
            f"# Style profile: {repository['full_name']}",
            "",
            "Accumulated coding style and repository analysis.",
            "",
        ]
        write_text(profile_path, "\n".join(header + block_lines))
        return profile_path
    with profile_path.open("a", encoding="utf-8") as file_handle:
        file_handle.write("\n".join(block_lines))
    return profile_path


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
