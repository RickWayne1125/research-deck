"""Find the Claude Code and Codex sessions that already exist for a project folder, so a panel can be bound to one.

Claude Code: ~/.claude/projects/<cwd with every non-alphanumeric character as "-">/<session uuid>.jsonl; each line
carries cwd, sessionId and timestamp; the first human "user" line gives a title (or a later {"type": "summary"}).
Codex: ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<thread id>.jsonl; the first line is session_meta with the cwd and
thread_source (user | exec | subagent | guardian_review); ~/.codex/session_index.jsonl names threads. Older sessions
compressed as .jsonl.zst are skipped (zstd is not in the standard library).
Only metadata and the first lines are read; nothing is written.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

from .. import config

MAX_SCAN_BYTES = 256 * 1024     # enough for the opening lines of a session
MAX_CODEX_FILES = 4000


def claude_slug(cwd: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("text", "input_text") and block.get("text"):
                return block["text"]
    return ""


def _title(text: str) -> str:
    text = re.sub(r"<[^>]+>[\s\S]*?</[^>]+>", " ", text)   # drop injected context blocks
    text = " ".join(text.split())
    return text[:90] + ("…" if len(text) > 90 else "")


def claude_sessions(cwd: str) -> list[dict]:
    folder = config.CLAUDE_HOME / "projects" / claude_slug(cwd)
    out = []
    for f in folder.glob("*.jsonl") if folder.is_dir() else []:
        title, turns, summary = "", 0, ""
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(MAX_SCAN_BYTES)
        except OSError:
            continue
        for line in head.splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "summary" and d.get("summary"):
                summary = d["summary"]
            if d.get("type") == "user" and not d.get("isSidechain") and (d.get("origin") or {}).get("kind", "human") == "human":
                text = _text_of((d.get("message") or {}).get("content"))
                if text and not text.startswith("<"):
                    turns += 1
                    title = title or _title(text)
        out.append({"provider": "claude", "session_id": f.stem, "title": summary or title or f.stem[:8], "cwd": cwd,
                    "updated_at": _iso(f.stat().st_mtime), "turns": turns})
    return out


def _codex_names() -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        for line in (config.CODEX_HOME / "session_index.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                if d.get("id") and d.get("thread_name"):
                    names[d["id"]] = d["thread_name"]
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return names


def codex_sessions(cwd: str) -> list[dict]:
    root = config.CODEX_HOME / "sessions"
    if not root.is_dir():
        return []
    files = sorted(root.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.name, reverse=True)[:MAX_CODEX_FILES]
    names = _codex_names()
    target = os.path.realpath(cwd)
    out = []
    for f in files:
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                first = fh.readline()
                meta = (json.loads(first).get("payload") or {}) if first else {}
                if os.path.realpath(meta.get("cwd") or "") != target:
                    continue
                if meta.get("thread_source") in ("subagent", "guardian_review"):
                    continue
                head = fh.read(MAX_SCAN_BYTES)
        except (OSError, json.JSONDecodeError):
            continue
        sid = meta.get("id") or meta.get("session_id") or f.stem.split("-", 6)[-1]
        title, turns = names.get(sid, ""), 0
        for line in head.splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = d.get("payload") or {}
            if d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                text = _text_of(p.get("content"))
                if text and not text.lstrip().startswith("<"):
                    turns += 1
                    title = title or _title(text)
        out.append({"provider": "codex", "session_id": sid, "title": title or sid[:8], "cwd": cwd,
                    "updated_at": _iso(f.stat().st_mtime), "turns": turns})
    # A long thread can be split into several rollout segments: keep the newest entry per thread.
    seen, unique = set(), []
    for s in sorted(out, key=lambda s: s["updated_at"], reverse=True):
        if s["session_id"] not in seen:
            seen.add(s["session_id"])
            unique.append(s)
    return unique


def discover(cwd: str, provider: str | None = None) -> list[dict]:
    found = []
    if provider in (None, "claude"):
        found += claude_sessions(cwd)
    if provider in (None, "codex"):
        found += codex_sessions(cwd)
    return sorted(found, key=lambda s: s["updated_at"], reverse=True)
