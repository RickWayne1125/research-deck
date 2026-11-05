"""A panel's conversation as the dock shows it: the dashboard's own record, handoff lines and, on request, the tail of
the bound session's own log (messages the researcher exchanged with that session outside the dashboard).

Sources:
  .research/context/transcripts/<panel>.jsonl   written by runner._transcript (user/assistant) and by handoff.py
                                                (role "handoff": a backend switch, or kind "note": a note one agent
                                                left for the other)
  .research/context/transcripts/runs.jsonl      model/effort/fast of each dock run (the transcript lines lack them)
  Claude Code  ~/.claude/projects/<cwd slug>/<session id>.jsonl                   user / assistant text blocks
  Codex        ~/.codex/sessions/YYYY/MM/DD/rollout-*<thread id>*.jsonl          response_item messages
Imported lines are read-only and bounded (the last IMPORT_MAX_MESSAGES messages within IMPORT_MAX_BYTES of the file's
tail); messages the dashboard itself sent through that session are dropped so nothing shows twice.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..projects import project_root, research_dir
from ..util import append_jsonl, now_iso, read_jsonl
from . import discover, runner, sessions

IMPORT_MAX_MESSAGES = 40
IMPORT_MAX_BYTES = 256 * 1024
IMPORT_MAX_CHARS = 8000          # per imported message
RUN_META_TAIL_BYTES = 256 * 1024
_TAG_BLOCK = re.compile(r"<([A-Za-z][\w-]*)(?:\s[^>]*)?>[\s\S]*?</\1>")


def transcript_path(pid: str, panel: str) -> Path:
    return research_dir(pid) / "context" / "transcripts" / f"{panel}.jsonl"


def _runs_meta_path(pid: str) -> Path:
    return research_dir(pid) / "context" / "transcripts" / "runs.jsonl"


def append(pid: str, panel: str, entry: dict) -> dict:
    """Add a line to the panel's transcript (used for handoff lines; the runner writes user/assistant lines)."""
    record = {"ts": now_iso(), "panel": panel, **entry}
    append_jsonl(transcript_path(pid, panel), record)
    return record


def record_run_meta(pid: str, run: runner.Run) -> None:
    """Remember which model answered a dock run, so the transcript can say so after the server restarts."""
    s = run.spec
    if s.ephemeral:
        return
    try:
        append_jsonl(_runs_meta_path(pid), {"run_id": run.id, "panel": s.panel, "provider": s.provider, "model": s.model,
                                            "effort": s.effort, "fast": s.fast, "ts": now_iso()})
    except OSError:
        pass


def _tail_lines(path: Path, max_bytes: int) -> list[str]:
    """The complete lines within the last max_bytes of a file (a partial first line is dropped)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            data = f.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def _run_meta(pid: str) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    for line in _tail_lines(_runs_meta_path(pid), RUN_META_TAIL_BYTES):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("run_id"):
            meta[d["run_id"]] = d
    return meta


def dashboard_entries(pid: str, panel: str) -> list[dict]:
    """The dashboard's record of a panel (after resolving a shared panel to the project panel), oldest first."""
    owner = sessions.effective_panel(pid, panel)
    return read_jsonl(transcript_path(pid, owner))


def since_last_handoff(entries: list[dict]) -> list[dict]:
    """User/assistant entries after the last backend switch (notes left by agents do not count as a switch)."""
    start = 0
    for i, e in enumerate(entries):
        if e.get("role") == "handoff" and e.get("kind") != "note":
            start = i + 1
    return [e for e in entries[start:] if e.get("role") in ("user", "assistant")]


def _ts_key(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _iso(ts: str | None) -> str:
    """Normalize a log timestamp to the dashboard's second-precision UTC form."""
    t = _ts_key(ts)
    return datetime.fromtimestamp(t, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if t else ""


def _strip_injected(text: str) -> str:
    """Drop blocks the CLIs or the dashboard inject around a message (<handoff>, <context>, <environment_context>…)."""
    return _TAG_BLOCK.sub(" ", text or "").strip()


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def _clip(text: str, limit: int = IMPORT_MAX_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _block_texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text") and block.get("text"):
            out.append(block["text"])
    return out


def _claude_messages(path: Path) -> list[dict]:
    out: list[dict] = []
    last_msg_id = None
    for line in _tail_lines(path, IMPORT_MAX_BYTES):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("isSidechain") or d.get("isMeta"):
            continue
        msg = d.get("message") or {}
        content = msg.get("content")
        if d.get("type") == "user":
            if (d.get("origin") or {}).get("kind", "human") != "human":
                continue
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                continue        # tool output, not something the researcher typed
            text = _strip_injected("\n".join(_block_texts(content)))
            if text:
                out.append({"role": "user", "text": text, "ts": d.get("timestamp")})
            last_msg_id = None
        elif d.get("type") == "assistant":
            text = "\n".join(_block_texts(content)).strip()
            if not text:
                continue
            # Claude Code writes one line per content block; blocks of one API message share its id.
            if last_msg_id and msg.get("id") == last_msg_id and out and out[-1]["role"] == "assistant":
                out[-1]["text"] += "\n\n" + text
            else:
                out.append({"role": "assistant", "text": text, "ts": d.get("timestamp")})
            last_msg_id = msg.get("id")
    return out


def _codex_messages(path: Path) -> list[dict]:
    out: list[dict] = []
    for line in _tail_lines(path, IMPORT_MAX_BYTES):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = d.get("payload") or {}
        if d.get("type") != "response_item" or p.get("type") != "message" or p.get("role") not in ("user", "assistant"):
            continue
        text = "\n".join(_block_texts(p.get("content"))).strip()
        if p["role"] == "user":
            text = _strip_injected(text)
        if text:
            out.append({"role": p["role"], "text": text, "ts": d.get("timestamp")})
    return out


def _codex_rollout(session_id: str) -> Path | None:
    root = config.CODEX_HOME / "sessions"
    if not root.is_dir() or not re.fullmatch(r"[\w-]+", session_id):
        return None
    files = sorted(root.glob(f"*/*/*/rollout-*{session_id}*.jsonl"), key=lambda f: f.name, reverse=True)
    if files:
        return files[0]
    # The file name may not carry the thread id; check the newest files' session_meta.
    for f in sorted(root.glob("*/*/*/rollout-*.jsonl"), key=lambda f: f.name, reverse=True)[:400]:
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                meta = json.loads(fh.readline() or "{}").get("payload") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if session_id in (meta.get("id"), meta.get("session_id")):
            return f
    return None


def session_log_path(pid: str, provider: str, session_id: str) -> Path | None:
    if not session_id:
        return None
    if provider == "claude":
        if not re.fullmatch(r"[\w-]+", session_id):
            return None
        path = config.CLAUDE_HOME / "projects" / discover.claude_slug(str(project_root(pid))) / f"{session_id}.jsonl"
        return path if path.is_file() else None
    if provider == "codex":
        return _codex_rollout(session_id)
    return None


def imported_entries(pid: str, panel: str, known: list[dict]) -> list[dict]:
    """The tail of the bound session's own log, minus what the dashboard already recorded."""
    b = sessions.get_binding(pid, panel)
    provider, sid = b["provider"], b.get("session_id")
    path = session_log_path(pid, provider, sid) if sid else None
    if not path:
        return []
    messages = _claude_messages(path) if provider == "claude" else _codex_messages(path)
    seen = {_norm(e.get("text", ""))[-400:] for e in known if e.get("role") in ("user", "assistant")}
    out = []
    for m in messages[-IMPORT_MAX_MESSAGES:]:
        key = _norm(m["text"])[-400:]
        if key in seen:
            continue
        out.append({"ts": _iso(m.get("ts")), "panel": b["panel"], "provider": provider, "session_id": sid,
                    "role": m["role"], "text": _clip(m["text"]), "imported": True})
    return out


def entries(pid: str, panel: str, limit: int = 100, include_imported: bool = False) -> list[dict]:
    """What the dock shows for a panel, oldest first: dashboard record + handoff lines (+ imported tail)."""
    items = dashboard_entries(pid, panel)
    meta = _run_meta(pid)
    for e in items:
        rid = e.get("run_id")
        if not rid or e.get("role") != "assistant":
            continue
        live = runner.get(rid)
        m = {"model": live.spec.model, "effort": live.spec.effort, "fast": live.spec.fast} if live else meta.get(rid)
        if m:
            e.update({k: m.get(k) for k in ("model", "effort", "fast")})
    if include_imported:
        try:
            items = items + imported_entries(pid, panel, items)
        except OSError:
            pass
        items.sort(key=lambda e: _ts_key(e.get("ts")))    # stable: same-second lines keep their file order
    return items[-max(1, limit):]
