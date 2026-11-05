"""The figure registry (<project>/.research/figures.json), figure files, previews and their freshness.

figures.json  {"version": 1, "figures": [{"id", "title", "kind", "source", "data": [], "node_id", "caption", "updated_at"}]}
previews      .research/figures/previews/<id>.svg (or .png), generated, plus <id>.json:
              {"ok": {"at", "sig", "duration_ms"} | null, "error": {"at", "sig", "log"} | null}
              `sig` is the signature of the source (and data files) the preview was made from, so a figure is
              "ok" when its saved files still match the last good preview, "stale" when they changed since, "error"
              when the saved files fail to render, "unrendered" when there is no preview yet.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from fastapi import HTTPException

from .. import config
from ..projects import project_config, project_root, research_dir
from ..util import now_iso, read_json, rel_to, safe_join, sha256_text, slugify, write_json, write_text_atomic
from . import style, templates

KINDS = ("drawio", "matplotlib", "omnigraffle", "datagraph")
KIND_LABELS = {"drawio": "draw.io", "matplotlib": "matplotlib", "omnigraffle": "OmniGraffle", "datagraph": "DataGraph"}
EXTENSIONS = {".drawio": "drawio", ".py": "matplotlib", ".graffle": "omnigraffle", ".dgraph": "datagraph", ".dgraphs": "datagraph"}
NATIVE_APP = {"drawio": "drawio", "omnigraffle": "omnigraffle", "datagraph": "datagraph"}   # config.APPS keys
PREVIEW_EXTS = (".svg", ".png")
MAX_HASH_BYTES = 64 * 1024 * 1024

_lock = threading.RLock()


# ---------------------------------------------------------------- paths

def figures_dir_rel(pid: str) -> str:
    fig = project_config(pid).get("figures")
    d = fig.get("dir") if isinstance(fig, dict) else fig
    return (d or "figures").strip("/") or "figures"


def registry_path(pid: str) -> Path:
    return research_dir(pid) / "figures.json"


def previews_dir(pid: str) -> Path:
    d = research_dir(pid) / "figures" / "previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def preview_file(pid: str, fid: str) -> Path | None:
    for ext in PREVIEW_EXTS:
        path = previews_dir(pid) / f"{fid}{ext}"
        if path.is_file():
            return path
    return None


def sidecar_path(pid: str, fid: str) -> Path:
    return previews_dir(pid) / f"{fid}.json"


# ---------------------------------------------------------------- registry

def load(pid: str) -> dict:
    doc = read_json(registry_path(pid), None)
    if not isinstance(doc, dict) or not isinstance(doc.get("figures"), list):
        doc = {"version": 1, "figures": []}
    return doc


def save(pid: str, doc: dict) -> None:
    write_json(registry_path(pid), doc)


def get_entry(pid: str, fid: str) -> dict:
    entry = next((f for f in load(pid)["figures"] if f.get("id") == fid), None)
    if not entry:
        raise HTTPException(404, f"unknown figure: {fid}")
    return entry


def update_entry(pid: str, fid: str, changes: dict) -> dict:
    with _lock:
        doc = load(pid)
        entry = next((f for f in doc["figures"] if f.get("id") == fid), None)
        if not entry:
            raise HTTPException(404, f"unknown figure: {fid}")
        entry.update(changes)
        entry["updated_at"] = now_iso()
        save(pid, doc)
        return entry


def remove_entry(pid: str, fid: str) -> None:
    """Forget a figure; its source, data and exports stay on disk (only the generated preview goes)."""
    with _lock:
        doc = load(pid)
        before = len(doc["figures"])
        doc["figures"] = [f for f in doc["figures"] if f.get("id") != fid]
        if len(doc["figures"]) == before:
            raise HTTPException(404, f"unknown figure: {fid}")
        save(pid, doc)
    for path in (*(previews_dir(pid) / f"{fid}{ext}" for ext in PREVIEW_EXTS), sidecar_path(pid, fid)):
        path.unlink(missing_ok=True)


def source_path(pid: str, entry: dict) -> Path:
    return safe_join(project_root(pid), entry.get("source") or "")


# ---------------------------------------------------------------- signatures and status

def _path_signature(path: Path) -> str | None:
    """Content hash of a file, or a listing hash (path, size, mtime) of a package folder (.graffle/.dgraph)."""
    try:
        if path.is_file():
            if path.stat().st_size > MAX_HASH_BYTES:
                st = path.stat()
                return sha256_text(f"{st.st_size}:{st.st_mtime_ns}")
            return hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_dir():
            parts = sorted(f"{p.relative_to(path).as_posix()}:{p.stat().st_size}:{p.stat().st_mtime_ns}"
                           for p in path.rglob("*") if p.is_file())
            return sha256_text("\n".join(parts))
    except OSError:
        return None
    return None


def signature(pid: str, entry: dict, source_text: str | None = None) -> str | None:
    """What a preview depends on: the source (saved, or the unsaved text being rendered) and the data files."""
    root = project_root(pid)
    src = sha256_text(source_text) if source_text is not None else _path_signature(source_path(pid, entry))
    if src is None:
        return None
    data = []
    if entry.get("kind") == "matplotlib":
        try:
            helper = helper_path(pid)
            if helper.is_file():
                data.append(_path_signature(helper) or "missing")
        except HTTPException:
            pass
    for rel in entry.get("data") or []:
        try:
            data.append(_path_signature(safe_join(root, rel)) or "missing")
        except HTTPException:
            data.append("invalid")
    return sha256_text("|".join([src, *data])) if data else src


def read_sidecar(pid: str, fid: str) -> dict:
    data = read_json(sidecar_path(pid, fid), None)
    return data if isinstance(data, dict) else {"ok": None, "error": None}


def record_render(pid: str, fid: str, *, ok: bool, sig: str | None, duration_ms: int = 0, log: str = "") -> None:
    side = read_sidecar(pid, fid)
    if ok:
        side["ok"] = {"at": now_iso(), "sig": sig, "duration_ms": duration_ms}
        side["error"] = None
    else:
        side["error"] = {"at": now_iso(), "sig": sig, "log": log[-4000:]}
    write_json(sidecar_path(pid, fid), side)


def preview_url(pid: str, fid: str) -> str | None:
    path = preview_file(pid, fid)
    if not path:
        return None
    return f"/api/projects/{pid}/figures/{fid}/preview?v={path.stat().st_mtime_ns}"


def status(pid: str, entry: dict) -> str:
    fid = entry["id"]
    side = read_sidecar(pid, fid)
    current = signature(pid, entry)
    err = side.get("error") or {}
    if err and err.get("sig") == current:
        return "error"
    if not preview_file(pid, fid):
        return "unrendered"
    ok = side.get("ok") or {}
    if not ok:
        # A preview without a record (exported by hand, copied in): trust it unless the source is newer.
        try:
            return "ok" if preview_file(pid, fid).stat().st_mtime >= source_path(pid, entry).stat().st_mtime else "stale"
        except OSError:
            return "stale"
    return "ok" if ok.get("sig") == current else "stale"


def _dag_node(pid: str, node_id: str | None) -> dict | None:
    """Label and state of the linked DAG node, when the DAG engine is available (it may not be)."""
    if not node_id:
        return None
    try:
        from ..dag import service as dag   # noqa: PLC0415 — optional; written by another slice
        getter = getattr(dag, "get_node", None)
        node = getter(pid, node_id) if callable(getter) else None
        if isinstance(node, dict):
            return {"id": node_id, "label": node.get("label") or node.get("title"),
                    "status": node.get("status") or node.get("state"), "freshness": node.get("freshness")}
    except Exception:  # noqa: BLE001 — the DAG is optional here
        return None
    return None


def view(pid: str, entry: dict) -> dict:
    """A registry entry as the client sees it: Figure (web/src/types.ts) plus file/app details."""
    fid = entry["id"]
    kind = entry.get("kind")
    try:
        exists = source_path(pid, entry).exists()
    except HTTPException:
        exists = False
    app_key = NATIVE_APP.get(kind)
    app = config.app_path(app_key) if app_key else None
    side = read_sidecar(pid, fid)
    return {
        "id": fid, "title": entry.get("title") or fid, "kind": kind, "source": entry.get("source"),
        "data": list(entry.get("data") or []), "preview": preview_url(pid, fid), "updated_at": entry.get("updated_at"),
        "node_id": entry.get("node_id"), "caption": entry.get("caption") or "", "status": status(pid, entry),
        "exists": exists, "kind_label": KIND_LABELS.get(kind, kind),
        "native": {"app": app_key, "installed": bool(app), "path": app} if app_key else None,
        "last_render": side.get("ok"), "last_error": side.get("error"),
        "node": _dag_node(pid, entry.get("node_id")),
    }


def list_views(pid: str) -> list[dict]:
    return [view(pid, f) for f in load(pid)["figures"] if f.get("id")]


# ---------------------------------------------------------------- creating figures

def _unique_id(pid: str, title: str, taken: set[str], fig_dir: Path, exts: tuple[str, ...]) -> str:
    base = slugify(title, "figure")
    fid, n = base, 2
    while fid in taken or any((fig_dir / f"{fid}{e}").exists() for e in exts) or (fig_dir / "data" / f"{fid}.csv").exists():
        fid, n = f"{base}-{n}", n + 1
    return fid


def helper_path(pid: str) -> Path:
    return safe_join(project_root(pid), f"{figures_dir_rel(pid)}/{templates.HELPER_NAME}")


def ensure_helper(pid: str, tok: dict | None = None) -> Path | None:
    """Write figures/_rdstyle.py from the current style tokens (only when its content would change).
    A helper whose first line is not the generated marker was edited by hand and is left alone (returns None)."""
    path = helper_path(pid)
    current = None
    if path.exists():
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        if not current.startswith(templates.HELPER_MARKER):
            return None
    text = templates.helper_source(tok or style.tokens(research_dir(pid)))
    if current != text:
        write_text_atomic(path, text)
    return path


def create(pid: str, *, kind: str, title: str, node_id: str | None = None, source: str | None = None,
           caption: str | None = None) -> dict:
    if kind not in KINDS:
        raise HTTPException(400, f"unknown figure kind: {kind}")
    root = project_root(pid)
    title = (title or "").strip() or (Path(source).stem if source else "") or KIND_LABELS[kind]
    fig_rel = figures_dir_rel(pid)
    fig_dir = safe_join(root, fig_rel)
    with _lock:
        doc = load(pid)
        taken = {f.get("id") for f in doc["figures"]}
        data: list[str] = []
        if source:
            # Register an existing file (any kind, including native OmniGraffle/DataGraph documents).
            target = safe_join(root, source)
            if not target.exists():
                raise HTTPException(404, f"no such file: {source}")
            ext_kind = EXTENSIONS.get(target.suffix.lower())
            if ext_kind and ext_kind != kind:
                raise HTTPException(400, f"{target.name} looks like a {KIND_LABELS[ext_kind]} file, not {KIND_LABELS[kind]}")
            if any(f.get("source") == rel_to(root, target) for f in doc["figures"]):
                raise HTTPException(409, f"{rel_to(root, target)} is already in the figure registry")
            fid = _unique_id(pid, title, taken, fig_dir, ())
            src_rel = rel_to(root, target)
        elif kind == "drawio":
            fid = _unique_id(pid, title, taken, fig_dir, (".drawio",))
            src_rel = f"{fig_rel}/{fid}.drawio"
            tok = style.tokens(research_dir(pid))
            write_text_atomic(safe_join(root, src_rel), templates.drawio_template(tok, title, f"rd-{fid}"))
        elif kind == "matplotlib":
            fid = _unique_id(pid, title, taken, fig_dir, (".py", ".pdf"))
            src_rel = f"{fig_rel}/{fid}.py"
            data_rel = f"{fig_rel}/data/{fid}.csv"
            write_text_atomic(safe_join(root, data_rel), templates.sample_csv())
            write_text_atomic(safe_join(root, src_rel), templates.matplotlib_template(title, f"data/{fid}.csv"))
            ensure_helper(pid)
            data = [data_rel]
        else:
            raise HTTPException(400, f"Research Deck cannot create {KIND_LABELS[kind]} documents; create it in "
                                     f"{KIND_LABELS[kind]} and register the existing file (source)")
        entry = {"id": fid, "title": title, "kind": kind, "source": src_rel, "data": data,
                 "node_id": node_id or None, "caption": caption or "", "updated_at": now_iso()}
        doc["figures"].append(entry)
        save(pid, doc)
    return entry


def discover(pid: str) -> list[dict]:
    """Figure files in the figures folder (and the paper folder) that are not registered yet."""
    root = project_root(pid)
    registered = {f.get("source") for f in load(pid)["figures"]}
    cfg = project_config(pid)
    paper = cfg.get("paper") if isinstance(cfg.get("paper"), dict) else {}
    out: list[dict] = []
    seen: set[str] = set()
    for rel in dict.fromkeys([figures_dir_rel(pid), paper.get("dir") or "paper"]):
        try:
            base = safe_join(root, rel)
        except HTTPException:
            continue
        if not base.is_dir():
            continue
        stack = [base]
        while stack and len(out) < 200:
            d = stack.pop()
            try:
                entries = sorted(d.iterdir())
            except OSError:
                continue
            for p in entries:
                if p.name.startswith(".") or p.name in ("node_modules", "__pycache__"):
                    continue
                kind = EXTENSIONS.get(p.suffix.lower())
                if kind and not (kind == "matplotlib" and (p.name.startswith("_") or not p.is_file())):
                    r = rel_to(root, p)
                    if r not in registered and r not in seen:
                        seen.add(r)
                        out.append({"path": r, "kind": kind})
                    if p.is_dir():
                        continue   # a package document: do not look inside
                if p.is_dir() and not p.is_symlink() and p.name != "previews":   # a linked folder may loop or leave
                    stack.append(p)
    return out
