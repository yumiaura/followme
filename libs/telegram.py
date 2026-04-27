#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram delivery helpers."""

from __future__ import annotations

import csv
import io
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from libs.ollama import ollama_generate
from libs.settings import parse_env_file, read_float_setting, read_setting


logger = logging.getLogger(__name__)


MAX_DOCUMENT_BYTES = 49_000_000
MAX_MESSAGE_CHARS = 4000


def load_telegram_config(project_root: str | Path) -> dict[str, Any]:
    """Load Telegram plugin settings from process env and project .env."""
    env_values = parse_env_file(Path(project_root) / ".env")
    bot_token = read_setting("TELEGRAM_BOT_TOKEN", env_values, default="")
    home_channel = read_setting("TELEGRAM_HOME_CHANNEL", env_values, default="")
    security_channel = read_setting("TELEGRAM_CHAT_SECURITY", env_values, default="")
    grade_threshold = min(
        10.0,
        read_float_setting("TELEGRAM_GRADE", env_values, default=9.49, minimum=0.0),
    )
    language = read_setting("TELEGRAM_LANGUAGE", env_values, default="")
    return {
        "bot_token": bot_token,
        "home_channel": home_channel,
        "security_channel": security_channel,
        "grade_threshold": grade_threshold,
        "language": language,
        "configured": bool(bot_token.strip() and home_channel.strip()),
        "security_configured": bool(bot_token.strip() and security_channel.strip()),
    }


def telegram_is_configured(telegram_config: dict[str, Any]) -> bool:
    """Check that Telegram credentials and channel are configured."""
    return bool(telegram_config.get("configured", False))


def telegram_csv_path(runtime: dict[str, Any]) -> Path:
    """Path for Telegram delivery log CSV."""
    return Path(runtime["data_dir"]) / "telegram.csv"


def ensure_telegram_csv_header(csv_path: Path) -> None:
    """Create telegram.csv with header if missing."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        return
    with csv_path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle)
        writer.writerow(["timestamp_utc", "repository"])


def append_telegram_row(csv_path: Path, timestamp_utc: str, repository_full_name: str) -> None:
    """Append a sent Telegram notification record."""
    with csv_path.open("a", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle)
        writer.writerow([timestamp_utc, repository_full_name])


def build_repo_zip_bytes(repo_dir: Path, repository_full_name: str) -> bytes:
    """Build in-memory ZIP archive for repository directory."""
    if not repo_dir.exists():
        raise FileNotFoundError(f"Repository directory not found: {repo_dir}")
    top_dir_name = repository_full_name.replace("/", "__")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(repo_dir.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(repo_dir)
            archive_name = str(Path(top_dir_name) / relative_path)
            archive.write(path, arcname=archive_name)
    return buffer.getvalue()


def build_multipart_form_data(
    fields: dict[str, str],
    file_field_name: str,
    file_name: str,
    file_bytes: bytes,
    file_content_type: str,
) -> tuple[str, bytes]:
    """Build multipart/form-data request body."""
    boundary = "----followmeBoundary7MA4YWxkTrZu0gW"
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field_name}"; '
            f'filename="{file_name}"\r\n'
        ).encode("utf-8")
    )
    body.extend(f"Content-Type: {file_content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return f"multipart/form-data; boundary={boundary}", bytes(body)


def telegram_api_get_chat(
    bot_token: str,
    chat_id: str,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """Fetch chat metadata from Telegram Bot API getChat method."""
    query = urllib.parse.urlencode({"chat_id": chat_id})
    url = f"https://api.telegram.org/bot{bot_token}/getChat?{query}"
    request = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw_body = response.read().decode("utf-8", errors="replace")
    payload = json.loads(raw_body) if raw_body else {}
    if isinstance(payload, dict):
        return payload
    return {}


def resolve_telegram_channel_label(
    telegram_config: dict[str, Any],
    runtime: dict[str, Any] | None = None,
) -> str:
    """Resolve readable Telegram channel label for logs."""
    raw_channel = str(telegram_config.get("home_channel", "")).strip()
    if not raw_channel:
        return raw_channel

    bot_token = str(telegram_config.get("bot_token", "")).strip()
    if not bot_token:
        return raw_channel

    timeout_seconds = 10
    if runtime is not None:
        try:
            timeout_seconds = int(runtime.get("request_timeout_seconds", 10))
        except (TypeError, ValueError):
            timeout_seconds = 10

    try:
        chat_payload = telegram_api_get_chat(bot_token, raw_channel, timeout_seconds=timeout_seconds)
        if not (isinstance(chat_payload, dict) and chat_payload.get("ok") is True):
            return raw_channel
        chat = chat_payload.get("result") or {}
        if not isinstance(chat, dict):
            return raw_channel

        username = str(chat.get("username", "")).strip()
        if username:
            return f"https://t.me/{username}"

        invite_link = str(chat.get("invite_link", "")).strip()
        if invite_link:
            return invite_link

        title = str(chat.get("title", "")).strip()
        if title:
            return f"{title} ({raw_channel})"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return raw_channel
    except Exception:
        return raw_channel

    return raw_channel


def send_telegram_document_to(
    runtime: dict[str, Any],
    bot_token: str,
    chat_id: str,
    caption: str,
    file_name: str,
    file_bytes: bytes,
    file_content_type: str = "application/zip",
    parse_mode: str = "",
) -> tuple[bool, str]:
    """Send a document to an arbitrary Telegram chat_id."""
    if not file_bytes:
        return False, "Telegram sendDocument skipped: file is empty"
    if len(caption) > 1024:
        caption = caption[:1021] + "..."
    document_url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    fields = {"chat_id": chat_id, "caption": caption}
    if parse_mode:
        fields["parse_mode"] = parse_mode
    content_type, multipart_body = build_multipart_form_data(
        fields=fields,
        file_field_name="document",
        file_name=file_name,
        file_bytes=file_bytes,
        file_content_type=file_content_type,
    )
    document_request = urllib.request.Request(url=document_url, data=multipart_body, method="POST")
    document_request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(document_request, timeout=runtime["request_timeout_seconds"]) as response:
            raw_document_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        return False, f"Telegram sendDocument HTTPError {exc.code}: {body_text}"
    except urllib.error.URLError as exc:
        return False, f"Telegram sendDocument URLError: {type(exc).__name__}: {exc}"
    document_body = json.loads(raw_document_body) if raw_document_body else {}
    if isinstance(document_body, dict) and document_body.get("ok") is True:
        return True, ""
    return False, f"Telegram sendDocument error response: {document_body}"


def send_telegram_message(
    runtime: dict[str, Any],
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "",
) -> tuple[bool, str]:
    """Send plain text message via sendMessage. Truncates to MAX_MESSAGE_CHARS."""
    body_text = text if len(text) <= MAX_MESSAGE_CHARS else text[: MAX_MESSAGE_CHARS - 3] + "..."
    message_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    fields = {"chat_id": chat_id, "text": body_text}
    if parse_mode:
        fields["parse_mode"] = parse_mode
    payload = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url=message_url, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=runtime["request_timeout_seconds"]) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"Telegram sendMessage HTTPError {exc.code}: {body}"
    except urllib.error.URLError as exc:
        return False, f"Telegram sendMessage URLError: {type(exc).__name__}: {exc}"
    body = json.loads(raw_body) if raw_body else {}
    if isinstance(body, dict) and body.get("ok") is True:
        return True, ""
    return False, f"Telegram sendMessage error response: {body}"


def send_telegram_document(
    runtime: dict[str, Any],
    telegram_config: dict[str, Any],
    repository_full_name: str,
    comment: str,
    repository_zip_bytes: bytes,
) -> tuple[bool, str]:
    """Send repository ZIP archive with caption to Telegram home channel."""
    caption = f"https://github.com/{repository_full_name}\n\n{comment}"
    zip_file_name = f"{repository_full_name.replace('/', '__')}.zip"
    return send_telegram_document_to(
        runtime=runtime,
        bot_token=telegram_config["bot_token"],
        chat_id=telegram_config["home_channel"],
        caption=caption,
        file_name=zip_file_name,
        file_bytes=repository_zip_bytes,
        file_content_type="application/zip",
    )


def translate_comment_for_telegram(
    runtime: dict[str, Any],
    telegram_config: dict[str, Any],
    comment: str,
) -> str:
    """Translate comment to TELEGRAM_LANGUAGE via Ollama when configured."""
    target_language = str(telegram_config.get("language", "")).strip()
    source_text = comment.strip()
    if not target_language or not source_text:
        return source_text
    if target_language.lower() == str(runtime["output_language"]).strip().lower():
        return source_text

    try:
        system_prompt = (
            "You are a precise translator for technical software summaries. "
            "Return only translated text with no explanations."
        )
        user_prompt = (
            f"Translate the text below to {target_language}.\n"
            "Keep meaning, tone, and technical terms accurate.\n"
            "Do not add any extra words before or after the translation.\n\n"
            f"text:\n{source_text}"
        )
        translated = ollama_generate(
            runtime,
            user_prompt,
            system_prompt,
            temperature=0.1,
            call_tag="telegram_translate",
        ).strip()
        return translated if translated else source_text
    except Exception as exc:
        logger.warning(f"Telegram translation failed: {type(exc).__name__}: {str(exc)}")
        return source_text


def log_telegram_delivery(
    runtime: dict[str, Any],
    timestamp_utc: str,
    repository_full_name: str,
) -> None:
    """Append successful Telegram delivery to CSV log."""
    csv_path = telegram_csv_path(runtime)
    ensure_telegram_csv_header(csv_path)
    append_telegram_row(csv_path, timestamp_utc, repository_full_name)


def main() -> None:
    """Module entrypoint placeholder."""
    pass


if __name__ == "__main__":
    main()
