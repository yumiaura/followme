#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan GitHub repositories, analyze with Ollama, and run plugins."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from libs.github import fetch_recent_repositories, follow_user, star_repository
from libs.ollama import ensure_ollama_available, ollama_generate
from libs.plugin_loader import PluginCallback, load_plugin_callbacks, run_plugin_callbacks
from libs.prompting import build_grade_prompt, build_profile_prompt, parse_grade_response
from libs.reports import append_csv_row, append_markdown_report, ensure_csv_header, write_text
from libs.repository import (
    build_digest,
    build_prompt_target,
    clone_repository,
    collect_file_snippets,
    make_repository_from_arg,
    reset_repo_dir,
    sanitize_label,
)
from libs.settings import load_settings


LOGGING = {
    "handlers": [logging.StreamHandler()],
    "format": "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s",
    "level": logging.INFO,
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
logging.basicConfig(**LOGGING)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Followme repository grading scan")
    parser.add_argument("-l", "--limit", type=int, default=None, help="How many repositories to scan")
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=None,
        help="Compatibility alias: set both follow and star grade thresholds",
    )
    parser.add_argument(
        "--follow-grade",
        type=float,
        default=None,
        help="Grade threshold for following repository owner",
    )
    parser.add_argument(
        "--star-grade",
        type=float,
        default=None,
        help="Grade threshold for starring repository",
    )
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
        help="Seconds to sleep between infinite cycles",
    )
    parser.add_argument(
        "-r",
        "--repo",
        type=str,
        default=None,
        help="Single repository as URL, owner/repo, or owner__repo",
    )
    return parser.parse_args()


def apply_cli_overrides(settings: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Apply command-line overrides to loaded settings."""
    updated_settings = dict(settings)
    if args.limit is not None:
        updated_settings["scan_limit"] = max(1, args.limit)
    if args.threshold is not None and args.follow_grade is None and args.star_grade is None:
        threshold = max(0.0, min(10.0, args.threshold))
        updated_settings["follow_grade"] = threshold
        updated_settings["star_grade"] = threshold
    if args.follow_grade is not None:
        updated_settings["follow_grade"] = max(0.0, min(10.0, args.follow_grade))
    if args.star_grade is not None:
        updated_settings["star_grade"] = max(0.0, min(10.0, args.star_grade))
    if args.dry_run:
        updated_settings["dry_run"] = True
    return updated_settings


def default_grade_payload(comment: str) -> dict[str, Any]:
    """Build default grade payload for non-analysis outcomes."""
    return {
        "grade": 0.0,
        "comment": comment,
        "verdict": "weak",
        "risk_level": "high",
        "evidence": [],
        "raw_response": "",
    }


def save_digest_if_enabled(
    settings: dict[str, Any],
    repository: dict[str, Any],
    timestamp_utc: str,
    digest: str,
) -> None:
    """Persist digest when configured."""
    if not settings["save_digest"]:
        return
    label = sanitize_label(f"{repository['full_name']}_{timestamp_utc}")
    digest_path = Path(settings["analysis_dir"]) / f"{label}_digest.txt"
    write_text(digest_path, digest)


def evaluate_repository(
    settings: dict[str, Any],
    repository: dict[str, Any],
    snippets: list[dict[str, Any]],
    selected_paths_count: int,
    timestamp_utc: str,
) -> tuple[dict[str, Any], str]:
    """Generate markdown profile and grade payload for repository."""
    repo_dir = Path(settings["repo_dir"])
    digest = build_digest(repository, repo_dir, snippets, selected_paths_count)
    save_digest_if_enabled(settings, repository, timestamp_utc, digest)
    target = build_prompt_target(repository, repo_dir)

    profile_system, profile_prompt = build_profile_prompt(settings, target, digest)
    profile_markdown = ollama_generate(
        settings,
        profile_prompt,
        profile_system,
        temperature=0.2,
        call_tag="profile",
    ).strip()
    if not profile_markdown:
        profile_markdown = "No style profile generated."

    grade_system, grade_prompt = build_grade_prompt(settings, target, profile_markdown)
    grade_raw = ollama_generate(
        settings,
        grade_prompt,
        grade_system,
        temperature=0.1,
        call_tag="grade",
    )
    grade_payload = parse_grade_response(grade_raw)
    return grade_payload, profile_markdown


def build_csv_row(result: dict[str, Any]) -> list[Any]:
    """Build CSV row preserving current schema."""
    return [
        result["timestamp_utc"],
        result["repository"],
        result["author"],
        f"{float(result['grade']):.2f}",
        result["comment"],
        "true" if result["starred"] else "false",
        "true" if result["followed"] else "false",
        result["status"],
        result["error"],
    ]


def build_result_payload(
    timestamp_utc: str,
    repository: dict[str, Any],
    grade_payload: dict[str, Any],
    profile_markdown: str,
    starred: bool,
    followed: bool,
    status: str,
    error_message: str,
    repo_dir: Path,
) -> dict[str, Any]:
    """Build result payload passed to reports and plugins."""
    grade = float(grade_payload.get("grade", 0.0))
    result = {
        "timestamp_utc": timestamp_utc,
        "repository": repository["full_name"],
        "author": repository["owner_login"],
        "grade": grade,
        "comment": str(grade_payload.get("comment", "")),
        "starred": starred,
        "followed": followed,
        "status": status,
        "error": error_message,
        "profile_markdown": profile_markdown,
        "csv_row": [],
        "markdown_path": "",
        "repo_dir": str(repo_dir),
    }
    result["csv_row"] = build_csv_row(result)
    return result


def attach_markdown_path(result: dict[str, Any], markdown_path: Path) -> None:
    """Attach markdown path to result payload after report creation."""
    result["markdown_path"] = str(markdown_path)


def process_repository(
    settings: dict[str, Any],
    repository: dict[str, Any],
    plugin_callbacks: list[PluginCallback],
) -> None:
    """Clone, inspect, grade, persist reports, run plugins, then cleanup."""
    timestamp_utc = datetime.now(timezone.utc).isoformat()
    repo_full_name = repository["full_name"]
    author_login = repository["owner_login"]
    starred = False
    followed = False
    status = "ok"
    error_message = ""
    profile_markdown = ""
    snippets: list[dict[str, Any]] = []
    selected_paths_count = 0
    grade_payload = default_grade_payload("no comment")
    repo_dir = Path(settings["repo_dir"])

    reset_repo_dir(repo_dir)
    clone_ok, clone_error = clone_repository(
        repository["clone_url"],
        repo_dir,
        settings["clone_depth"],
        settings["github_token"],
    )
    if not clone_ok:
        status = "clone_error"
        error_message = clone_error
        grade_payload = default_grade_payload("clone failed")
    else:
        snippets, selected_paths_count = collect_file_snippets(repo_dir, settings)
        if not snippets:
            status = "no_files"
            grade_payload = default_grade_payload("no eligible files found")
        else:
            try:
                grade_payload, profile_markdown = evaluate_repository(
                    settings,
                    repository,
                    snippets,
                    selected_paths_count,
                    timestamp_utc,
                )
                logger.info(
                    f"Grade result for {repo_full_name}: "
                    f"grade={grade_payload['grade']:.2f}, comment={grade_payload['comment']}"
                )
                grade = float(grade_payload["grade"])
                should_follow = grade > settings["follow_grade"]
                should_star = grade > settings["star_grade"]
                if should_follow or should_star:
                    if settings["dry_run"]:
                        status = "dry_run_high_grade"
                    else:
                        if should_star:
                            starred = star_repository(settings, repo_full_name)
                        if should_follow:
                            followed = follow_user(settings, author_login)
            except Exception as exc:
                status = "analysis_error"
                error_message = f"{type(exc).__name__}: {str(exc)}"
                grade_payload = default_grade_payload("analysis failed")
                logger.warning(
                    f"Profile/grade analysis failed for {repo_full_name}: "
                    f"{error_message}\n{traceback.format_exc()}"
                )

    result = build_result_payload(
        timestamp_utc=timestamp_utc,
        repository=repository,
        grade_payload=grade_payload,
        profile_markdown=profile_markdown,
        starred=starred,
        followed=followed,
        status=status,
        error_message=error_message,
        repo_dir=repo_dir,
    )
    markdown_path = append_markdown_report(
        settings,
        repository,
        result,
        snippets,
        selected_paths_count,
        grade_payload,
    )
    attach_markdown_path(result, markdown_path)
    append_csv_row(Path(settings["results_csv"]), result["csv_row"])
    payload = {"runtime": settings, "result": result}
    run_plugin_callbacks(plugin_callbacks, payload)
    if repo_dir.exists():
        shutil.rmtree(repo_dir)


def run_repositories(
    settings: dict[str, Any],
    repositories: list[dict[str, Any]],
    plugin_callbacks: list[PluginCallback],
) -> None:
    """Run processing loop for provided repositories."""
    data_dir = Path(settings["data_dir"])
    code_style_dir = Path(settings["code_style_dir"])
    repo_dir = Path(settings["repo_dir"])
    results_csv = Path(settings["results_csv"])
    data_dir.mkdir(parents=True, exist_ok=True)
    code_style_dir.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(results_csv)
    if repositories:
        ensure_ollama_available(settings)
    logger.info(
        "Starting grading: "
        f"repos={len(repositories)} follow_grade={settings['follow_grade']} "
        f"star_grade={settings['star_grade']} "
        f"csv={results_csv} language={settings['output_language']}"
    )
    logger.info(f"Plugin callbacks loaded: {len(plugin_callbacks)}")
    for index, repository in enumerate(repositories, start=1):
        logger.info(f"[{index}/{len(repositories)}] Processing {repository['full_name']}")
        process_repository(settings, repository, plugin_callbacks)
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    logger.info("Scan completed")


def run_infinite(
    settings: dict[str, Any],
    args: argparse.Namespace,
    plugin_callbacks: list[PluginCallback],
) -> None:
    """Run scan loop forever until interrupted."""
    cycle_sleep_seconds = settings["infinite_sleep_seconds"] if args.sleep is None else max(0.0, args.sleep)
    cycle_index = 0
    while True:
        cycle_index += 1
        repositories = fetch_recent_repositories(settings)
        logger.info(
            f"Infinite cycle {cycle_index}: fetched {len(repositories)} repositories "
            f"(scan_limit={settings['scan_limit']})"
        )
        run_repositories(settings, repositories, plugin_callbacks)
        logger.info(f"Infinite cycle {cycle_index}: sleeping {cycle_sleep_seconds}s before next fetch")
        time.sleep(cycle_sleep_seconds)


def main() -> int:
    """Program entrypoint."""
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    try:
        settings = apply_cli_overrides(load_settings(project_root), args)
        plugin_callbacks = load_plugin_callbacks(Path(settings["plugins_dir"]), settings)
        if args.repo:
            repository = make_repository_from_arg(args.repo)
            run_repositories(settings, [repository], plugin_callbacks)
            return 0
        if args.infinite:
            run_infinite(settings, args, plugin_callbacks)
            return 0
        repositories = fetch_recent_repositories(settings)
        run_repositories(settings, repositories, plugin_callbacks)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted, stopping")
        return 130
    except Exception as exc:
        logger.error(f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
