#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub API helpers for followme."""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


GITHUB_API = "https://api.github.com"

logger = logging.getLogger(__name__)


def auth_headers(token: str) -> dict[str, str]:
    """Build standard GitHub API headers."""
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "followme-grader",
    }


def build_git_basic_auth_header(token: str) -> str:
    """Build git clone HTTP basic auth header for GitHub tokens."""
    if not token:
        return ""
    raw_auth = f"x-access-token:{token}"
    encoded = base64.b64encode(raw_auth.encode("utf-8")).decode("ascii")
    return f"Authorization: Basic {encoded}"


def github_request(
    method: str,
    path: str,
    settings: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """Execute GitHub request and return status + parsed JSON body if possible."""
    url = f"{GITHUB_API}{path}"
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"
    request = urllib.request.Request(
        url=url,
        method=method,
        headers=auth_headers(settings["github_token"]),
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["request_timeout_seconds"]) as response:
            status_code = response.getcode()
            raw_body = response.read().decode("utf-8", errors="replace")
            if not raw_body:
                return status_code, None
            return status_code, json.loads(raw_body)
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw_body) if raw_body else None
        except json.JSONDecodeError:
            body = {"raw": raw_body}
        return exc.code, body


def fetch_recent_repositories(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch latest repositories using GitHub Search API."""
    repositories: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_page = 100
    page = 1
    query = f"language:{settings['language']} stars:<{settings['max_stars']}"
    while len(repositories) < settings["scan_limit"]:
        status_code, body = github_request(
            method="GET",
            path="/search/repositories",
            settings=settings,
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
            if not isinstance(item, dict):
                continue
            owner = item.get("owner", {})
            owner_login = str(owner.get("login", "")).strip() if isinstance(owner, dict) else ""
            full_name = str(item.get("full_name", "")).strip()
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
            if len(repositories) >= settings["scan_limit"]:
                break
        page += 1
    logger.info(f"Fetched {len(repositories)} repositories for scan")
    return repositories


def is_repo_starred(settings: dict[str, Any], repository_full_name: str) -> bool:
    """Check if repository is already starred."""
    status_code, _ = github_request(
        method="GET",
        path=f"/user/starred/{repository_full_name}",
        settings=settings,
    )
    return status_code == 204


def star_repository(settings: dict[str, Any], repository_full_name: str) -> bool:
    """Star repository if not already starred."""
    if is_repo_starred(settings, repository_full_name):
        return False
    status_code, body = github_request(
        method="PUT",
        path=f"/user/starred/{repository_full_name}",
        settings=settings,
    )
    if status_code == 204:
        return True
    logger.warning(f"Failed to star {repository_full_name}: {status_code} {body}")
    return False


def is_user_followed(settings: dict[str, Any], username: str) -> bool:
    """Check if current token follows username."""
    status_code, _ = github_request(
        method="GET",
        path=f"/user/following/{username}",
        settings=settings,
    )
    return status_code == 204


def follow_user(settings: dict[str, Any], username: str) -> bool:
    """Follow user if not followed yet."""
    if is_user_followed(settings, username):
        return False
    status_code, body = github_request(
        method="PUT",
        path=f"/user/following/{username}",
        settings=settings,
    )
    if status_code == 204:
        return True
    logger.warning(f"Failed to follow {username}: {status_code} {body}")
    return False


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
