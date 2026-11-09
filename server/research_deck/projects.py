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

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, demo
from .actors import actor_of
from .events import hub
from .util import now_iso, read_json, read_yaml, rel_to, safe_join, sha256_text, slugify, write_json, write_text_atomic, write_yaml

log = logging.getLogger("research_deck")
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
                                  "figures/previews/\ndag/.cache/\noutline/file.json\n")


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


# GET …/raw serves a project file as itself, for the links and pictures in documents (a survey's "PDF" links). The
# browser shows PDFs and pictures in its own viewer and other UTF-8 text as plain text; anything else downloads.
# Nothing served here may run as a page of the dashboard: HTML and scripts arrive as plain text, the browser may not
# sniff a type, and pictures and text get a sandboxed page with no powers. PDFs do not: Chrome's viewer refuses to open
# under a sandbox, and a PDF's own scripts run inside the viewer, not on the dashboard's origin.
VIEWABLE_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}
RAW_SANDBOX = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:"
TEXT_PROBE_BYTES = 8192


def looks_like_text(path: Path) -> bool:
    """UTF-8 with no NUL byte in the first 8 KiB (git's test for a binary file, plus the encoding)."""
    with path.open("rb") as f:
        head = f.read(TEXT_PROBE_BYTES)
    if b"\0" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        # a character cut in two by the 8 KiB probe is still text
        return len(head) == TEXT_PROBE_BYTES and e.reason == "unexpected end of data"
    return True


@router.get("/{pid}/raw")
def raw_file(pid: str, path: str = Query(...)):
    root = project_root(pid)
    target = safe_join(root, path)
    if not target.is_file():
        raise HTTPException(404, f"no such file: {path}")
    media = VIEWABLE_TYPES.get(target.suffix.lower())
    headers = {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"}
    if media != "application/pdf":
        headers["Content-Security-Policy"] = RAW_SANDBOX
    if media is None and looks_like_text(target):
        media = "text/plain; charset=utf-8"
    if media is None:
        return FileResponse(target, media_type="application/octet-stream", headers=headers, filename=target.name)
    return FileResponse(target, media_type=media, headers=headers, filename=target.name, content_disposition_type="inline")


class WriteFile(BaseModel):
    path: str
    content: str
    base_sha: str | None = None   # the sha the editor loaded; a different sha on disk means someone else wrote it


# Run after PUT …/file wrote a file: hook(pid, rel, content, actor) -> None, or, for a file Research Deck keeps in step
# with something else (the outline file, outline/doc.py), {"content": the file as it is now, ...what to report}.
FILE_HOOKS: list = []


@router.put("/{pid}/file")
def write_file(pid: str, body: WriteFile, request: Request):
    root = project_root(pid)
    target = safe_join(root, body.path)
    if body.base_sha and target.exists():
        current = sha256_text(target.read_text(encoding="utf-8"))
        if current != body.base_sha:
            raise HTTPException(409, {"message": "the file changed on disk", "sha": current})
    write_text_atomic(target, body.content)
    rel = rel_to(root, target)
    extra: dict = {}
    for hook in FILE_HOOKS:
        try:
            extra = hook(pid, rel, body.content, actor_of(request)) or {}
        except Exception:  # noqa: BLE001 — the file is written whatever a hook makes of it
            log.exception("file hook failed for %s", rel)
            extra = {}
        if extra:
            break
    content = extra.pop("content", body.content)
    sha = sha256_text(content)
    hub.publish(pid, "file", {"path": rel, "sha": sha})
    out = {"path": rel, "sha": sha, "mtime": target.stat().st_mtime, **extra}
    if content != body.content:
        out["content"] = content
    return out
