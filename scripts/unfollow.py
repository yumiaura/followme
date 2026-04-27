#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unfollow GitHub users who do not follow back."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from libs.github import github_request
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
    parser = argparse.ArgumentParser(
        description="Unfollow GitHub users who do not follow the authenticated user back",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only log users that would be unfollowed",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of users to unfollow in this run",
    )
    return parser.parse_args()


def fetch_paginated_user_logins(settings: dict[str, Any], path: str) -> set[str]:
    """Fetch paginated GitHub user list and return login set."""
    logins: set[str] = set()
    page = 1
    per_page = 100
    while True:
        status_code, body = github_request(
            method="GET",
            path=path,
            settings=settings,
            params={"per_page": per_page, "page": page},
        )
        if status_code != 200:
            raise RuntimeError(f"GitHub API failed for {path}: {status_code} {body}")
        if not isinstance(body, list) or not body:
            break
        for item in body:
            if not isinstance(item, dict):
                continue
            login = str(item.get("login", "")).strip()
            if login:
                logins.add(login)
        if len(body) < per_page:
            break
        page += 1
    return logins


def collect_non_mutual_following(settings: dict[str, Any]) -> list[str]:
    """Collect users followed by us who do not follow us back."""
    following = fetch_paginated_user_logins(settings, "/user/following")
    followers = fetch_paginated_user_logins(settings, "/user/followers")
    non_mutual = sorted(following - followers)
    logger.info(
        "GitHub follow graph loaded: "
        f"following={len(following)} followers={len(followers)} "
        f"non_mutual={len(non_mutual)}"
    )
    return non_mutual


def unfollow_user(settings: dict[str, Any], username: str) -> bool:
    """Unfollow one GitHub user."""
    status_code, body = github_request(
        method="DELETE",
        path=f"/user/following/{username}",
        settings=settings,
    )
    if status_code == 204:
        return True
    logger.warning(f"Failed to unfollow {username}: {status_code} {body}")
    return False


def limit_usernames(usernames: list[str], limit: int | None) -> list[str]:
    """Apply optional operation limit."""
    if limit is None:
        return usernames
    return usernames[: max(0, limit)]


def run_unfollow(settings: dict[str, Any], dry_run: bool, limit: int | None) -> None:
    """Run non-mutual unfollow workflow."""
    if limit is not None and limit <= 0:
        logger.info("Limit is 0, nothing to do")
        return

    usernames = limit_usernames(collect_non_mutual_following(settings), limit)
    if not usernames:
        logger.info("No non-mutual GitHub users to unfollow")
        return

    if dry_run:
        for username in usernames:
            logger.info(f"Would unfollow {username}")
        logger.info(f"Dry-run completed: users={len(usernames)}")
        return

    unfollowed = 0
    for username in usernames:
        if unfollow_user(settings, username):
            unfollowed += 1
            logger.info(f"Unfollowed {username}")
    logger.info(f"Unfollow completed: requested={len(usernames)} unfollowed={unfollowed}")


def main() -> int:
    """Program entrypoint."""
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    try:
        settings = load_settings(project_root)
        run_unfollow(settings, dry_run=args.dry_run, limit=args.limit)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted, stopping")
        return 130
    except Exception as exc:
        logger.error(f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
