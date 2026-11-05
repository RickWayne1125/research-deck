"""Tasks: the work an outline item needs (a literature review, coding, a figure, an experiment), kept apart from the
outline itself. One item can have several tasks and one task can serve several items.

.research/outline/tasks.json
    {"version": 1, "tasks": [{"id": "t-3f9a2c", "type": "lit|code|fig|exp", "title": "…", "items": ["claim.…"],
                              "status": "todo|doing|blocked|done|sugg", "note": "…", "assignee": "me|agent|",
                              "links": {"node": "exp.…", "figure": "…", "survey": "sv-…", "branch": "…", "path": "…"},
                              "by": "human:…", "created_at": "…", "updated_at": "…"}]}

`status` is what the researcher (or an agent's suggestion, "sugg") set. effective() derives what the outline shows: an
experiment task linked to a map node is done once the node has a succeeded run and is fresh, blocked when its latest
run failed; a literature task linked to a survey follows the survey; a task whose items sit in a phase the project
has not reached waits for it ("locked") under the stage rules.
"""
from __future__ import annotations

import re
import threading
import uuid
from typing import Any

from fastapi import HTTPException

from ..projects import research_dir
from ..util import now_iso, read_json, write_json
from .templates import TASK_KINDS

STATUSES = ("todo", "doing", "blocked", "done", "sugg")
ASSIGNEES = ("", "me", "agent")
LINK_KEYS = ("node", "figure", "survey", "branch", "path")
ID_RE = re.compile(r"^t-[0-9a-f]{6,12}$")
_lock = threading.RLock()


def _path(pid: str):
    return research_dir(pid) / "outline" / "tasks.json"


def load(pid: str) -> list[dict]:
    doc = read_json(_path(pid), None) or {}
    return [t for t in doc.get("tasks") or [] if isinstance(t, dict) and ID_RE.match(str(t.get("id") or ""))]


def _save(pid: str, tasks: list[dict]) -> None:
    p = _path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json(p, {"version": 1, "tasks": tasks})


def _clean(change: dict, base: dict | None = None) -> dict:
    t = dict(base or {})
    if "type" in change:
        if change["type"] not in TASK_KINDS:
            raise HTTPException(400, f"type must be one of {', '.join(TASK_KINDS)}")
        t["type"] = change["type"]
    if "title" in change:
        title = str(change["title"] or "").strip()
        if not title or len(title) > 200:
            raise HTTPException(400, "a task needs a title (at most 200 characters)")
        t["title"] = title
    if "items" in change:
        items = change["items"]
        if not isinstance(items, list) or not all(isinstance(i, str) and i.startswith("claim.") for i in items):
            raise HTTPException(400, "items: a list of outline item ids (claim.…)")
        t["items"] = list(dict.fromkeys(items))
    if "status" in change:
        if change["status"] not in STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
        t["status"] = change["status"]
    if "note" in change:
        t["note"] = str(change["note"] or "")[:500]
    if "assignee" in change:
        if change["assignee"] not in ASSIGNEES:
            raise HTTPException(400, "assignee: me, agent or empty")
        t["assignee"] = change["assignee"]
    if "links" in change:
        links = change["links"] or {}
        if not isinstance(links, dict):
            raise HTTPException(400, "links must be a mapping")
        t["links"] = {k: str(v)[:300] for k, v in links.items() if k in LINK_KEYS and v}
    return t


def create(pid: str, data: dict, actor: str) -> dict:
    t = _clean({"status": "todo", "note": "", "assignee": "", "links": {}, "items": [], **data})
    for k in ("type", "title"):
        if k not in t:
            raise HTTPException(400, f"a task needs {k}")
    t.update(id=f"t-{uuid.uuid4().hex[:8]}", by=actor, created_at=now_iso(), updated_at=now_iso())
    with _lock:
        tasks = load(pid)
        tasks.append(t)
        _save(pid, tasks)
    return t


def update(pid: str, tid: str, change: dict) -> dict:
    with _lock:
        tasks = load(pid)
        for i, t in enumerate(tasks):
            if t["id"] == tid:
                tasks[i] = {**_clean(change, t), "updated_at": now_iso()}
                _save(pid, tasks)
                return tasks[i]
    raise HTTPException(404, f"no such task: {tid}")


def remove(pid: str, tid: str) -> bool:
    with _lock:
        tasks = load(pid)
        left = [t for t in tasks if t["id"] != tid]
        if len(left) == len(tasks):
            raise HTTPException(404, f"no such task: {tid}")
        _save(pid, left)
    return True


def drop_items(pid: str, item_ids: set[str]) -> None:
    """Items left the outline: they no longer count among the items a task serves."""
    with _lock:
        tasks = load(pid)
        changed = False
        for t in tasks:
            keep = [i for i in t.get("items") or [] if i not in item_ids]
            if keep != t.get("items"):
                t["items"], changed = keep, True
        if changed:
            _save(pid, tasks)


def effective(t: dict, st: Any, surveys: dict[str, dict] | None = None) -> tuple[str, str]:
    """(status, note) as the outline shows it, before the phase lock: derived from what the task is linked to."""
    status, note = t.get("status") or "todo", t.get("note") or ""
    if status == "sugg":
        return status, note
    node = (t.get("links") or {}).get("node")
    n = st.nodes.get(node) if st is not None and node else None
    if n is not None and n.get("kind") == "experiment":
        runs = st.runs.by_node.get(node) or []
        if runs and runs[0].get("state") == "failed":
            return "blocked", note or "the latest run failed"
        ev = st.E.get(node)
        ok = [r for r in runs if r.get("state", "succeeded") == "succeeded" and not r.get("excluded")]
        if ok and ev is not None and ev.level == "fresh":
            return "done", note
        if ok:
            return "doing", note or "results are not fresh: rerun"
    survey = (t.get("links") or {}).get("survey")
    if survey and surveys and survey in surveys:
        s = surveys[survey].get("status")
        return {"running": ("doing", note), "done": ("done", note)}.get(s, ("blocked", note or f"survey {s}"))
    return status, note
