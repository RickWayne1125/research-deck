"""Outline templates: which sections a new outline has, what each must make the reader accept, which phase it belongs
to, which kinds of task it usually needs, and what the phases are called.

Built-in templates are package data (outline/templates/*.yaml); the user's own live in ~/.research-deck/templates/
(config.LOCAL_DIR / "templates"), one file per template, and win over a built-in with the same id. Changing a
template never changes an outline made from it: each project edits its own sections afterwards.

    id: systems
    name: {zh: 系统论文, en: Systems paper}
    description: {zh: …, en: …}
    phases: {idea: {zh: 想法, en: Idea}, insight: …, design: …, evaluation: …}      display names only
    sections:
      - key: motivation                       becomes the section node sec.<key>
        title: {zh: 背景与动机, en: Background and Motivation}
        role: {zh: …, en: …}                  what the section must make the reader accept
        phase: insight                        idea | insight | design | evaluation | summary
        tasks: [exp, fig, lit]                the kinds of task it usually needs (lit, code, fig, exp)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .. import config
from ..util import read_yaml, write_yaml

BUILTIN_DIR = Path(__file__).parent / "templates"
PHASES = ("idea", "insight", "design", "evaluation")
SECTION_PHASES = PHASES + ("summary",)
TASK_KINDS = ("lit", "code", "fig", "exp")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
DEFAULT_PHASES = {"idea": {"zh": "想法", "en": "Idea"}, "insight": {"zh": "动机与洞察", "en": "Motivation & insight"},
                  "design": {"zh": "系统设计", "en": "System design"}, "evaluation": {"zh": "评估", "en": "Evaluation"}}


def user_dir() -> Path:
    return config.LOCAL_DIR / "templates"


def _text(v: Any, field: str) -> dict:
    """A bilingual text: {zh, en} (a plain string counts for both)."""
    if isinstance(v, str):
        v = {"zh": v, "en": v}
    if not isinstance(v, dict) or not any(isinstance(v.get(k), str) and v[k].strip() for k in ("zh", "en")):
        raise ValueError(f"{field} needs zh or en text")
    zh, en = str(v.get("zh") or v.get("en")).strip(), str(v.get("en") or v.get("zh")).strip()
    return {"zh": zh[:200], "en": en[:200]}


def validate(data: Any) -> dict:
    """A clean template, or ValueError saying what is wrong."""
    if not isinstance(data, dict):
        raise ValueError("a template is a mapping")
    tid = str(data.get("id") or "")
    if not ID_RE.match(tid):
        raise ValueError("id: lowercase letters, digits and -")
    phases = {p: _text((data.get("phases") or {}).get(p) or DEFAULT_PHASES[p], f"phases.{p}") for p in PHASES}
    sections, keys = [], set()
    for i, s in enumerate(data.get("sections") or []):
        if not isinstance(s, dict):
            raise ValueError(f"sections[{i}] is not a mapping")
        key = str(s.get("key") or "")
        if not KEY_RE.match(key) or key in keys:
            raise ValueError(f"sections[{i}].key must be unique: lowercase letters, digits and -")
        keys.add(key)
        phase = s.get("phase")
        if phase not in SECTION_PHASES:
            raise ValueError(f"sections[{i}].phase must be one of {', '.join(SECTION_PHASES)}")
        tasks = [t for t in s.get("tasks") or [] if t in TASK_KINDS]
        sections.append({"key": key, "title": _text(s.get("title"), f"sections[{i}].title"),
                         "role": _text(s.get("role") or s.get("title"), f"sections[{i}].role"), "phase": phase, "tasks": tasks})
    if not sections:
        raise ValueError("a template needs at least one section")
    return {"id": tid, "name": _text(data.get("name") or tid, "name"),
            "description": _text(data.get("description") or data.get("name") or tid, "description"),
            "phases": phases, "sections": sections}


def _load(path: Path) -> dict | None:
    try:
        return validate(read_yaml(path, None))
    except (ValueError, OSError, Exception):  # noqa: BLE001 — a broken user file is skipped, not fatal
        return None


def all_templates() -> list[dict]:
    """Every template, built-ins first; `builtin` says which, `overrides` when a user file shadows a built-in."""
    out: dict[str, dict] = {}
    for p in sorted(BUILTIN_DIR.glob("*.yaml")):
        t = _load(p)
        if t:
            out[t["id"]] = {**t, "builtin": True}
    d = user_dir()
    for p in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        t = _load(p)
        if t:
            out[t["id"]] = {**t, "builtin": False, "overrides": t["id"] in out}
    return list(out.values())


def get(tid: str) -> dict:
    for t in all_templates():
        if t["id"] == tid:
            return t
    raise HTTPException(404, f"no such template: {tid}")


def save(data: dict) -> dict:
    """Write a user template (a built-in id makes a user copy that shadows it)."""
    try:
        t = validate(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    user_dir().mkdir(parents=True, exist_ok=True)
    write_yaml(user_dir() / f"{t['id']}.yaml", t)
    return get(t["id"])


def remove(tid: str) -> bool:
    """Remove a user template (built-ins stay; a user copy of one is removed, the built-in shows again)."""
    if not ID_RE.match(tid or ""):
        raise HTTPException(404, f"no such template: {tid}")
    path = user_dir() / f"{tid}.yaml"
    if not path.exists():
        raise HTTPException(404, f"no user template {tid} (built-in templates cannot be removed)")
    path.unlink()
    return True
