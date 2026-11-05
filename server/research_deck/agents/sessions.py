"""The project conversation: which Codex/Claude session it is bound to, in <project>/.research/sessions.json.

{
  "version": 1,
  "panels": {
    "project": {"active": "claude",
                "claude": {"session_id": "6f1c…", "model": "claude-opus-5-5", "effort": "xhigh", "fast": false, "permission": "read", "updated_at": "…"},
                "codex":  {"session_id": null,    "model": "gpt-6-astra",     "effort": "xhigh", "fast": false, "permission": "read"}}
  }
}

A project has one conversation, whichever view a request comes from: ORIGINS are the views that may ask (a run's
`panel`), and every one of them resolves to "project". The conversation keeps one session per backend, so switching
Claude -> Codex -> Claude resumes the earlier Claude session (and the handoff note carries what happened meanwhile).
Calls to the same session are serialized (session_lock). Older files may hold entries for the views that once had
their own sessions; they are left as they are and no longer used.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict

from ..events import hub
from ..projects import research_dir
from ..util import now_iso, read_json, write_json
from . import catalog

PANELS = ("project",)
ORIGINS = ("project", "writing", "coding", "experiments", "visualization")
PROVIDERS = ("claude", "codex")
# Claude session ids are UUIDs, Codex thread ids UUID-like; anything else (e.g. "--dangerously-…") never reaches argv.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{7,63}$")


def valid_session_id(value) -> str | None:
    return value if isinstance(value, str) and SESSION_ID_RE.match(value) else None
_lock = threading.RLock()
_session_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def _default_provider_session(provider: str) -> dict:
    d = catalog.claude_default() if provider == "claude" else catalog.codex_default()
    return {"session_id": None, "model": d["model"], "effort": d["effort"], "fast": False, "permission": "read", "updated_at": None}


def _default_panel(panel: str) -> dict:
    return {"active": "claude", **{p: _default_provider_session(p) for p in PROVIDERS}}


def load(pid: str) -> dict:
    with _lock:
        doc = read_json(research_dir(pid) / "sessions.json", None) or {"version": 1, "panels": {}}
        for panel in PANELS:
            entry = doc["panels"].setdefault(panel, _default_panel(panel))
            if entry.get("active") not in PROVIDERS:
                entry["active"] = "claude"
            entry.pop("shared", None)
            for prov in PROVIDERS:
                sess = {**_default_provider_session(prov), **(entry.get(prov) or {})}
                sess["session_id"] = valid_session_id(sess.get("session_id"))
                sess["permission"] = "write" if sess.get("permission") == "write" else "read"
                sess["model"], sess["effort"], sess["fast"] = catalog.normalize(prov, sess.get("model"), sess.get("effort"), sess.get("fast"))
                entry[prov] = sess
        return doc


def save(pid: str, doc: dict) -> None:
    with _lock:
        write_json(research_dir(pid) / "sessions.json", doc)
    hub.publish(pid, "sessions", doc)


def effective_panel(pid: str, panel: str) -> str:
    """The conversation a request from `panel` goes to: always the project's."""
    return "project"


def get_binding(pid: str, panel: str = "project") -> dict:
    """The active backend and its session settings: {"panel": "project", "provider", "session_id", "model", ...}."""
    entry = load(pid)["panels"]["project"]
    provider = entry["active"]
    return {"panel": "project", "provider": provider, **entry[provider]}


def update_binding(pid: str, panel: str, changes: dict) -> dict:
    """changes: {provider?, model?, effort?, fast?, permission?, session_id?, title?}. Returns the conversation's entry."""
    with _lock:
        doc = load(pid)
        entry = doc["panels"][effective_panel(pid, panel)]
        provider = changes.get("provider") or entry["active"]
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        entry["active"] = provider
        sess = entry[provider]
        for key in ("model", "effort", "fast", "permission", "title"):
            if key in changes and changes[key] is not None:
                sess[key] = changes[key]
        if "session_id" in changes:
            if changes["session_id"] and not valid_session_id(changes["session_id"]):
                raise ValueError(f"not a session id: {changes['session_id']!r}")
            sess["session_id"] = changes["session_id"] or None
        if sess.get("permission") not in ("read", "write"):
            raise ValueError(f"unknown permission: {sess.get('permission')!r}")
        sess["model"], sess["effort"], sess["fast"] = catalog.normalize(provider, sess["model"], sess["effort"], sess["fast"])
        sess["updated_at"] = now_iso()
        save(pid, doc)
        return entry


def set_session_id(pid: str, panel: str, provider: str, session_id: str) -> None:
    if not valid_session_id(session_id) or provider not in PROVIDERS:
        return
    with _lock:
        doc = load(pid)
        sess = doc["panels"][effective_panel(pid, panel)][provider]
        if sess.get("session_id") != session_id:
            sess["session_id"] = session_id
            sess["updated_at"] = now_iso()
            save(pid, doc)


def session_lock(provider: str, session_id: str | None) -> threading.Lock | None:
    """Calls to one session run one at a time; one-shot and new-session runs need no lock (None)."""
    return _session_locks[f"{provider}:{session_id}"] if session_id else None
