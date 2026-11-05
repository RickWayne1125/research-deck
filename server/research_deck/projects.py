"""The project registry (machine-local) and each project's folder: config, file tree, file read/write.

A project is any folder. Research Deck keeps its own state in <root>/.research/ (committed with the project):
  project.yaml      name, venue, deadline, stage, where the paper/code/figures/experiments live
  dag/              the research DAG (see dag/)
  sessions.json     which Codex/Claude session each panel is bound to (see agents/)
  context/          the shared brief, handoff notes and dashboard transcripts both agents read
  writing/          glossary, learned rules, review findings, snapshots
  figures.json      the figure registry (see viz/)
  experiments/      experiment records (see experiments/)
  style.json        optional per-project figure style overrides
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import config, demo
from .events import hub
from .util import now_iso, read_json, read_yaml, rel_to, safe_join, sha256_text, slugify, write_json, write_text_atomic, write_yaml

router = APIRouter(prefix="/api/projects", tags=["projects"])

RESEARCH_DIR = ".research"
STATE_RE = re.compile(r"^\.research(-[a-z0-9][a-z0-9-]{0,40})?$")      # .research or .research-<slug>
IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build", ".DS_Store"}
MAX_FILE_BYTES = 4 * 1024 * 1024

# kind: "research" (the full pipeline: DAG, gates, lenses) or "engineering" (code, docs, runs and figures of a
# non-research effort such as a PR; no research pipeline). views: the views to show, overriding the kind's default.
KINDS = ("research", "engineering")
DEFAULT_CONFIG = {
    "name": "",
    "kind": "research",
    "views": None,
    "summary": "",
    "venue": "",
    "deadline": None,
    "stage": "idea",
    "language": "en",            # the paper's language; the UI language is a browser setting
    "paper": {"main": "paper/main.tex", "dir": "paper"},
    "code": {"roots": ["src"]},
    "figures": {"dir": "figures"},
    "experiments": {"dir": "experiments"},
}


# ---------------------------------------------------------------- registry

def _registry() -> dict:
    data = read_json(config.REGISTRY_FILE, None)
    changed = data is None
    if data is None:
        data = {"version": 1, "projects": []}
    # A demo entry whose folder is gone (e.g. the demo an older version shipped inside the repository) is forgotten.
    gone = [p for p in data["projects"] if p.get("demo") and not Path(p["root"]).exists()]
    if gone:
        data["projects"] = [p for p in data["projects"] if p not in gone]
        changed = True
    # The demo, materialized from demo/minimal into LOCAL_DIR/demo/ on first start, is offered until the user removes
    # it (then "demo_dismissed" keeps it away).
    if config.DEMO_ENABLED and not data.get("demo_dismissed"):
        root = demo.ensure_demo()
        if root is not None and not any(p.get("demo") for p in data["projects"]) and \
                not any(Path(p["root"]).resolve() == root.resolve() for p in data["projects"]):
            taken, pid, n = {p["id"] for p in data["projects"]}, demo.PROJECT_ID, 2
            while pid in taken:
                pid, n = f"{demo.PROJECT_ID}-{n}", n + 1
            data["projects"].insert(0, {"id": pid, "root": str(root), "demo": True, "added_at": now_iso()})
            changed = True
    if changed:
        write_json(config.REGISTRY_FILE, data)
    return data


def _save_registry(data: dict) -> None:
    write_json(config.REGISTRY_FILE, data)


def _entry(pid: str) -> dict:
    for p in _registry()["projects"]:
        if p["id"] == pid:
            return p
    raise HTTPException(404, f"unknown project: {pid}")


def state_name(entry: dict) -> str:
    """The project's state folder under its root: ".research" unless the registry names another one, so that two
    projects can share one workspace folder (e.g. an engineering project and a research project over the same repos)."""
    name = str(entry.get("state") or RESEARCH_DIR)
    if not STATE_RE.match(name):
        raise HTTPException(500, f"bad state folder name in the registry: {name!r}")
    return name


def project_root(pid: str) -> Path:
    root = Path(_entry(pid)["root"])
    if not root.exists():
        raise HTTPException(404, f"project folder is missing: {root}")
    return root


def project_state(pid: str) -> str:
    return state_name(_entry(pid))


def research_dir(pid: str) -> Path:
    d = project_root(pid) / project_state(pid)
    d.mkdir(exist_ok=True)
    return d


def project_config(pid: str) -> dict:
    cfg = read_yaml(research_dir(pid) / "project.yaml", {}) or {}
    merged = {**DEFAULT_CONFIG, **cfg}
    merged["name"] = merged.get("name") or project_root(pid).name
    return merged


def _summary(entry: dict) -> dict:
    root = Path(entry["root"])
    cfg = {**DEFAULT_CONFIG, **(read_yaml(root / state_name(entry) / "project.yaml", {}) or {})}
    return {
        "id": entry["id"], "root": str(root), "demo": bool(entry.get("demo")), "exists": root.exists(),
        "name": cfg.get("name") or root.name, "summary": cfg.get("summary", ""), "venue": cfg.get("venue", ""),
        "deadline": cfg.get("deadline"), "stage": cfg.get("stage", "idea"), "is_git": (root / ".git").exists(),
        "kind": cfg.get("kind") if cfg.get("kind") in KINDS else "research", "views": cfg.get("views") or None,
        "state": state_name(entry),
    }


def init_research_dir(root: Path, name: str | None = None, state: str = RESEARCH_DIR, kind: str = "research") -> None:
    rd = root / state
    rd.mkdir(parents=True, exist_ok=True)
    if not (rd / "project.yaml").exists():
        write_yaml(rd / "project.yaml", {**DEFAULT_CONFIG, "name": name or root.name, "kind": kind})
    for sub in ("dag", "context", "writing", "experiments"):
        (rd / sub).mkdir(exist_ok=True)
    ignore = rd / ".gitignore"
    if not ignore.exists():
        # Machine-local state: session ids point into this Mac's ~/.claude and ~/.codex; transcripts and caches are local.
        write_text_atomic(ignore, "sessions.json\ncontext/transcripts/\ncontext/pending/\nwriting/reviews/\n"
                                  "figures/previews/\ndag/.cache/\n")


# ---------------------------------------------------------------- routes

class AddProject(BaseModel):
    root: str
    name: str | None = None
    kind: str = "research"
    # another project already uses this folder: give this one its own state folder (".research-<slug>")
    state: str | None = None


@router.get("")
def list_projects():
    return [_summary(p) for p in _registry()["projects"]]


@router.post("")
def add_project(body: AddProject):
    root = Path(os.path.expanduser(body.root)).resolve()
    if not root.is_dir():
        raise HTTPException(400, f"not a folder: {root}")
    if body.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of {KINDS}")
    state = body.state or RESEARCH_DIR
    if not STATE_RE.match(state):
        raise HTTPException(400, "state must be .research or .research-<lowercase-slug>")
    data = _registry()
    for p in data["projects"]:
        if Path(p["root"]).resolve() == root and state_name(p) == state:
            return _summary(p)
    pid = slugify(body.name or root.name, "project")
    taken = {p["id"] for p in data["projects"]}
    base, n = pid, 2
    while pid in taken:
        pid, n = f"{base}-{n}", n + 1
    init_research_dir(root, body.name, state, body.kind)
    entry = {"id": pid, "root": str(root), "added_at": now_iso(), **({"state": state} if state != RESEARCH_DIR else {})}
    data["projects"].append(entry)
    _save_registry(data)
    return _summary(entry)


@router.delete("/{pid}")
def remove_project(pid: str):
    """Forget the project (its folder and .research/ stay untouched)."""
    data = _registry()
    if any(p["id"] == pid and p.get("demo") for p in data["projects"]):
        data["demo_dismissed"] = True
    data["projects"] = [p for p in data["projects"] if p["id"] != pid]
    _save_registry(data)
    return {"ok": True}


@router.get("/{pid}")
def get_project(pid: str):
    entry = next((p for p in _registry()["projects"] if p["id"] == pid), None)
    if not entry:
        raise HTTPException(404, f"unknown project: {pid}")
    return {**_summary(entry), "config": project_config(pid)}


@router.patch("/{pid}/config")
def patch_config(pid: str, body: dict):
    path = research_dir(pid) / "project.yaml"
    cfg = read_yaml(path, {}) or {}
    if "stage" in body and body["stage"] != cfg.get("stage"):
        # Blocking gates (dag config gates.blocking): a later stage opens only once the gates before it are passed.
        try:
            from .dag.gates import stage_blockers
            from .dag.service import store_for
            missing = stage_blockers(store_for(pid), cfg.get("stage") or "idea", str(body["stage"]))
        except ImportError:
            missing = []
        if missing:
            raise HTTPException(409, {"message": "pass these gates first: " + ", ".join(missing), "gates": missing})
    cfg.update(body)
    write_yaml(path, cfg)
    hub.publish(pid, "project", {"config": cfg})
    return project_config(pid)


@router.get("/{pid}/tree")
def tree(pid: str, dir: str = Query(""), depth: int = Query(4, ge=1, le=8)):
    root = project_root(pid)
    root_resolved = root.resolve()
    base = safe_join(root, dir) if dir else root

    def walk(d: Path, level: int) -> list[dict]:
        items = []
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return items
        for p in entries:
            if p.name in IGNORED_DIRS or (p.name.startswith(".") and p.name != RESEARCH_DIR):
                continue
            try:
                if p.is_symlink():
                    # Listed, never descended: a link may point outside the project or back up into it (a loop).
                    target = p.resolve()
                    if root_resolved not in target.parents and target != root_resolved:
                        continue
                    node = {"path": p.relative_to(root).as_posix(), "name": p.name, "kind": "link"}
                else:
                    node = {"path": p.relative_to(root).as_posix(), "name": p.name, "kind": "dir" if p.is_dir() else "file"}
                    if p.is_dir():
                        node["children"] = walk(p, level + 1) if level < depth else []
                    else:
                        st = p.stat()
                        node.update(size=st.st_size, mtime=st.st_mtime)
            except OSError:
                continue
            items.append(node)
        return items

    return walk(base, 1)


@router.get("/{pid}/file")
def read_file(pid: str, path: str = Query(...)):
    root = project_root(pid)
    target = safe_join(root, path)
    if not target.is_file():
        raise HTTPException(404, f"no such file: {path}")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(413, "file too large to open here")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "not a text file")
    return {"path": rel_to(root, target), "content": content, "sha": sha256_text(content), "mtime": target.stat().st_mtime}


class WriteFile(BaseModel):
    path: str
    content: str
    base_sha: str | None = None   # the sha the editor loaded; a different sha on disk means someone else wrote it


@router.put("/{pid}/file")
def write_file(pid: str, body: WriteFile):
    root = project_root(pid)
    target = safe_join(root, body.path)
    if body.base_sha and target.exists():
        current = sha256_text(target.read_text(encoding="utf-8"))
        if current != body.base_sha:
            raise HTTPException(409, {"message": "the file changed on disk", "sha": current})
    write_text_atomic(target, body.content)
    sha = sha256_text(body.content)
    hub.publish(pid, "file", {"path": rel_to(root, target), "sha": sha})
    return {"path": rel_to(root, target), "sha": sha, "mtime": target.stat().st_mtime}
