#!/usr/bin/env python3
"""Append explicit user prompts from local Codex sessions to .ai-log.

Codex Desktop stores each local conversation as JSONL under
``~/.codex/sessions/YYYY/MM/DD``. This scanner reads explicit user messages
from both the legacy ``event_msg/user_message`` schema and the current
``response_item/message`` schema, limits them to sessions opened for the
current repository, and uses a stable entry ID so a prompt is never appended
twice.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


VN_TZ = timezone(timedelta(hours=7))
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def git(command: str) -> str:
    try:
        return subprocess.check_output(
            command.split(), text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def normalize(path: str) -> str:
    return path.strip().lower().replace("/", "\\").rstrip("\\") if path else ""


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def logged_ids(log_file: Path, archive_dir: Path) -> set[str]:
    ids: set[str] = set()
    files = [log_file]
    if archive_dir.exists():
        files.extend(archive_dir.glob("*.jsonl"))
    for path in files:
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig") as stream:
            for line in stream:
                try:
                    entry_id = json.loads(line).get("entry_id")
                except json.JSONDecodeError:
                    continue
                if entry_id:
                    ids.add(entry_id)
    return ids


def session_metadata(session_file: Path) -> tuple[str, str]:
    """Return the session ID and working directory recorded in its first line."""
    try:
        with open(session_file, encoding="utf-8") as stream:
            first_entry = json.loads(next(stream))
    except (OSError, StopIteration, json.JSONDecodeError):
        return "", ""

    payload = first_entry.get("payload") or {}
    return str(payload.get("session_id") or payload.get("id") or ""), str(payload.get("cwd") or "")


def user_prompts(sessions_dir: Path, repo_root: str, cutoff: datetime | None):
    for session_file in sessions_dir.rglob("*.jsonl"):
        session_id, cwd = session_metadata(session_file)
        if not session_id or normalize(cwd) != repo_root:
            continue

        try:
            with open(session_file, encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    payload = entry.get("payload") or {}
                    prompt = None
                    if entry.get("type") == "event_msg" and payload.get("type") == "user_message":
                        prompt = payload.get("message")
                    elif (
                        entry.get("type") == "response_item"
                        and payload.get("type") == "message"
                        and payload.get("role") == "user"
                    ):
                        text_parts = [
                            item.get("text", "")
                            for item in payload.get("content", [])
                            if isinstance(item, dict) and item.get("type") == "input_text"
                        ]
                        prompt = "\n".join(part for part in text_parts if part)

                    if not isinstance(prompt, str) or len(prompt.strip()) < 2:
                        continue

                    timestamp = str(entry.get("timestamp") or "")
                    recorded_at = parse_timestamp(timestamp)
                    if cutoff and recorded_at and recorded_at < cutoff:
                        continue

                    yield session_id, line_number, timestamp, prompt.strip()
        except OSError:
            continue


def main() -> None:
    parser = argparse.ArgumentParser(description="Log local Codex user prompts into .ai-log/session.jsonl.")
    parser.add_argument("--auto", action="store_true", help="Scan the last 24 hours (default).")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours (default: 24).")
    parser.add_argument("--all", action="store_true", help="Ignore the time window.")
    parser.add_argument("--dry-run", action="store_true", help="Report matches without writing a log file.")
    args = parser.parse_args()

    sessions_dir = Path(os.environ.get("CODEX_SESSIONS_DIR", CODEX_SESSIONS_DIR))
    if not sessions_dir.exists():
        print("[codex-log] No Codex sessions directory found.", file=sys.stderr)
        return

    repo_root = normalize(str(Path.cwd()))
    cutoff = None if args.all else datetime.now(timezone.utc) - timedelta(hours=args.hours)
    log_dir = Path(os.environ.get("AI_LOG_DIR", ".ai-log"))
    log_file = log_dir / "session.jsonl"
    existing_ids = logged_ids(log_file, log_dir / "archive")
    repo = git("git remote get-url origin").split("/")[-1].removesuffix(".git")
    branch = git("git rev-parse --abbrev-ref HEAD")
    commit = git("git rev-parse --short HEAD")
    student = git("git config user.email") or os.environ.get("USERNAME", "unknown")

    entries = []
    for session_id, line_number, timestamp, prompt in user_prompts(sessions_dir, repo_root, cutoff):
        entry_id = f"codex-{session_id}-{line_number:05d}"
        if entry_id in existing_ids:
            continue
        recorded_at = parse_timestamp(timestamp)
        entries.append({
            "ts": (recorded_at.astimezone(VN_TZ).isoformat() if recorded_at else datetime.now(VN_TZ).isoformat()),
            "tool": "codex",
            "event": "UserPrompt",
            "entry_id": entry_id,
            "session_id": session_id,
            "model": "codex",
            "repo": repo,
            "branch": branch,
            "commit": commit,
            "student": student,
            "prompt": prompt,
            "response_summary": "",
        })

    if not entries:
        print("[codex-log] No new prompts.", file=sys.stderr)
        return
    if args.dry_run:
        print(f"[codex-log] Would log {len(entries)} prompt(s).", file=sys.stderr)
        return

    log_dir.mkdir(exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as stream:
        for entry in entries:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[codex-log] Logged {len(entries)} prompt(s) from Codex.", file=sys.stderr)


if __name__ == "__main__":
    main()
