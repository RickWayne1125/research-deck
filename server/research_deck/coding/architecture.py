"""The system's architecture as the Coding panel draws it: modules and their imports, grouped into components.

Modules come from the project's code roots (project.yaml `code.roots`):
  Python      parsed with ast; `import` / `from ... import` resolved to modules of this project (relative imports too)
  TS / JS     import / export-from / require / dynamic import() with a relative specifier, resolved like a bundler
Module ids are project-relative paths, so they are stable and unique across languages.

Components come from `.research/architecture.yaml` ({"components": [{id, label, node_id, paths: [globs], description}]})
and, when the DAG engine is available, from design nodes that declare code paths (dag.design_components). Each module
belongs to the first component with a matching glob (`**` crosses directories, `*` does not; a plain path matches the
file or everything under that folder).

The module graph is cached per project and rebuilt only when a file in the code roots changes (path, mtime, size).
"""
from __future__ import annotations

import ast
import hashlib
import os
import posixpath
import re
import threading
from pathlib import Path

from fastapi import HTTPException

from ..projects import IGNORED_DIRS, project_config, project_root, research_dir
from ..util import now_iso, read_yaml, safe_join, slugify

LANGS = {".py": "py", ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js"}
JS_RESOLVE_EXTS = (".ts", ".tsx", ".mts", ".js", ".jsx", ".mjs", ".cjs")
SKIP_DIRS = IGNORED_DIRS | {"venv", "env", ".tox", "site-packages", ".next", "coverage", ".ipynb_checkpoints"}
MAX_MODULES = 800
MAX_FILE_BYTES = 1_000_000

_cache: dict[str, tuple[str, dict]] = {}
_cache_lock = threading.Lock()

# import x from './y' | export {a} from "./y" | import './y' | require('./y') | import('./y')
_JS_IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*|^\s*import\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)(['"])([^'"\n]+)\1""", re.M)
_JS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_JS_LINE_COMMENT_RE = re.compile(r"^\s*//.*$", re.M)
_PY_MAIN_RE = re.compile(r"""^if\s+__name__\s*==\s*['"]__main__['"]\s*:""", re.M)


# ------------------------------------------------------------------ public

def architecture(pid: str) -> dict:
    root = project_root(pid)
    roots = _code_roots(pid)
    files, warnings = _collect(root, roots)
    graph = _graph_cached(root, files)
    components = load_components(pid)
    matchers = [(c["id"], [_glob_matcher(g) for g in c["paths"]]) for c in components]
    modules = []
    for m in graph["modules"]:
        comp = next((cid for cid, ms in matchers if any(match(m["path"]) for match in ms)), None)
        modules.append({**m, "component": comp})
    return {"modules": modules, "edges": graph["edges"], "components": components, "generated_at": graph["generated_at"],
            "roots": roots, "truncated": graph["truncated"], "warnings": warnings}


def load_components(pid: str) -> list[dict]:
    """Declared components: architecture.yaml first, then DAG design nodes (which may also fill in a node_id)."""
    out: list[dict] = []
    by_id: dict[str, dict] = {}
    by_node: dict[str, dict] = {}              # declared components by the DAG node they link to
    doc = read_yaml(research_dir(pid) / "architecture.yaml", None) or {}
    declared = list(doc.get("components") or []) if isinstance(doc, dict) else []
    try:
        from ..dag import service as dag  # the DAG engine is optional here
        declared += [dict(c, _from_dag=True) for c in (dag.design_components(pid) or [])]
    except Exception:  # noqa: BLE001 — a missing or failing DAG must not break the architecture view
        pass
    for raw in declared:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("id") or "").strip()
        cid = str(raw.get("id") or slugify(label, "component")).strip()
        if not cid:
            continue
        paths = raw.get("paths") or []
        paths = [paths] if isinstance(paths, str) else [str(p) for p in paths if p]
        known = by_id.get(cid) or (by_node.get(str(raw.get("node_id"))) if raw.get("_from_dag") else None)
        if known:                               # a DAG node describing a component the YAML already declares
            known["node_id"] = known["node_id"] or raw.get("node_id")
            known["description"] = known["description"] or str(raw.get("description") or "")
            known["paths"] = known["paths"] or paths
            continue
        comp = {"id": cid, "label": label or cid, "node_id": raw.get("node_id") or None, "paths": paths,
                "description": str(raw.get("description") or ""), "source": "dag" if raw.get("_from_dag") else "yaml"}
        by_id[cid] = comp
        if comp["node_id"]:
            by_node.setdefault(str(comp["node_id"]), comp)
        out.append(comp)
    return out


def module_context(pid: str, path: str) -> dict | None:
    """What the architecture says about one file (for explanations): component, imports and importers."""
    arch = architecture(pid)
    mod = next((m for m in arch["modules"] if m["path"] == path), None)
    if not mod:
        return None
    comp = next((c for c in arch["components"] if c["id"] == mod["component"]), None)
    return {
        "module": mod, "component": comp,
        "imports": sorted(e["to"] for e in arch["edges"] if e["from"] == path),
        "imported_by": sorted(e["from"] for e in arch["edges"] if e["to"] == path),
    }


# ------------------------------------------------------------------ files

def _code_roots(pid: str) -> list[str]:
    code = project_config(pid).get("code") or {}
    roots = code.get("roots") if isinstance(code, dict) else None
    if isinstance(roots, str):
        roots = [roots]
    return [str(r) for r in (roots or ["src"]) if str(r).strip()]


def _collect(root: Path, roots: list[str]) -> tuple[list[tuple[str, Path, str]], list[str]]:
    """[(project-relative path, absolute path, code root relative path)] for every source file under the code roots."""
    root = root.resolve()
    seen: set[str] = set()
    out: list[tuple[str, Path, str]] = []
    warnings: list[str] = []
    for code_root in roots:
        try:
            base = safe_join(root, code_root)
        except HTTPException:
            warnings.append(f"code root outside the project ignored: {code_root}")
            continue
        if not base.exists():
            warnings.append(f"code root not found: {code_root}")
            continue
        base_rel = base.relative_to(root).as_posix()
        candidates: list[Path] = []
        if base.is_file():
            candidates.append(base)
        else:
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
                candidates.extend(Path(dirpath) / f for f in sorted(filenames))
        for path in candidates:
            if path.suffix not in LANGS or path.name.endswith(".d.ts") or path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            out.append((rel, path, base_rel if base.is_dir() else posixpath.dirname(base_rel)))
    return out, warnings


def _graph_cached(root: Path, files: list[tuple[str, Path, str]]) -> dict:
    h = hashlib.sha1()
    for rel, path, base in files:
        try:
            st = path.stat()
        except OSError:
            continue
        h.update(f"{rel}\0{base}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
    signature = h.hexdigest()
    key = str(root.resolve())
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == signature:
            return hit[1]
    graph = _build(root.resolve(), files)
    with _cache_lock:
        _cache[key] = (signature, graph)
    return graph


# ------------------------------------------------------------------ graph

def _build(root: Path, files: list[tuple[str, Path, str]]) -> dict:
    truncated = len(files) > MAX_MODULES
    files = files[:MAX_MODULES]
    modules: list[dict] = []
    sources: dict[str, str] = {}
    py_names: dict[str, str] = {}              # dotted module name -> module id
    for rel, path, base in files:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                text = ""
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lang = LANGS[path.suffix]
        loc = sum(1 for line in text.splitlines() if line.strip())
        if lang == "py":
            dotted = _py_module_name(root, path, root / base if base else root)
            kind = "package" if path.name == "__init__.py" else (
                "script" if path.name == "__main__.py" or _PY_MAIN_RE.search(text) else "module")
            label = dotted
            py_names.setdefault(dotted, rel)
        else:
            stem = posixpath.splitext(posixpath.relpath(rel, base) if base else rel)[0]
            kind = "script" if text.startswith("#!") or "/scripts/" in f"/{rel}" else "module"
            label = stem
        modules.append({"id": rel, "path": rel, "label": label, "kind": kind, "loc": loc, "lang": lang})
        sources[rel] = text

    ids = {m["id"] for m in modules}
    edges: set[tuple[str, str]] = set()
    for m in modules:
        text = sources[m["id"]]
        targets = _py_imports(m, text, py_names) if m["lang"] == "py" else _js_imports(m["path"], text, ids)
        edges.update((m["id"], t) for t in targets if t != m["id"])
    return {"modules": modules, "edges": [{"from": a, "to": b, "kind": "import"} for a, b in sorted(edges)],
            "generated_at": now_iso(), "truncated": truncated}


def _py_module_name(root: Path, path: Path, code_root: Path) -> str:
    """Dotted name: climb while the folder is a package (has __init__.py); below the code root, folders without
    __init__.py still count (namespace packages in a src layout)."""
    parts = [] if path.name == "__init__.py" else [path.stem]
    d = path.parent
    while d != root and root in d.parents and (d / "__init__.py").exists():
        parts.insert(0, d.name)
        d = d.parent
    if d != code_root and code_root in d.parents:
        parts = list(d.relative_to(code_root).parts) + parts
    return ".".join(parts) or path.stem


def _resolve_dotted(name: str, py_names: dict[str, str]) -> str | None:
    """The module for a dotted name, or for its longest known prefix (import a.b.c depends on a.b.c, else a.b ...)."""
    parts = name.split(".")
    while parts:
        hit = py_names.get(".".join(parts))
        if hit:
            return hit
        parts.pop()
    return None


def _py_imports(mod: dict, text: str, py_names: dict[str, str]) -> set[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    own = mod["label"]
    package = own if mod["kind"] == "package" else own.rpartition(".")[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _resolve_dotted(alias.name, py_names)
                if hit:
                    out.add(hit)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                if node.level - 1 > len(base):
                    continue
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if not target:
                continue
            for alias in node.names:
                # `from pkg import sub` imports the submodule pkg.sub when there is one
                hit = py_names.get(f"{target}.{alias.name}") if alias.name != "*" else None
                hit = hit or _resolve_dotted(target, py_names)
                if hit:
                    out.add(hit)
    return out


def _js_imports(rel: str, text: str, ids: set[str]) -> set[str]:
    text = _JS_LINE_COMMENT_RE.sub("", _JS_BLOCK_COMMENT_RE.sub("", text))
    folder = posixpath.dirname(rel)
    out: set[str] = set()
    for m in _JS_IMPORT_RE.finditer(text):
        spec = m.group(2).split("?", 1)[0]
        if not spec.startswith("."):
            continue                              # packages and path aliases are outside the project graph
        target = posixpath.normpath(posixpath.join(folder, spec))
        hit = _resolve_js(target, ids)
        if hit:
            out.add(hit)
    return out


def _resolve_js(target: str, ids: set[str]) -> str | None:
    stem, ext = posixpath.splitext(target)
    candidates = [target]
    if ext in (".js", ".jsx", ".mjs", ".cjs"):    # TS sources imported with their emitted extension
        candidates += [stem + ".ts", stem + ".tsx", stem + ".mts"]
    candidates += [target + e for e in JS_RESOLVE_EXTS]
    candidates += [f"{target}/index{e}" for e in JS_RESOLVE_EXTS]
    return next((c for c in candidates if c in ids), None)


# ------------------------------------------------------------------ globs

def _glob_matcher(pattern: str):
    pattern = pattern.strip()
    if pattern.startswith("./"):
        pattern = pattern[2:]
    if not pattern:
        return lambda _path: False
    if not any(ch in pattern for ch in "*?["):
        prefix = pattern.rstrip("/")
        return lambda path: path == prefix or path.startswith(prefix + "/")
    regex, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex, i = regex + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            regex, i = regex + ".*", i + 2
        elif pattern[i] == "*":
            regex, i = regex + "[^/]*", i + 1
        elif pattern[i] == "?":
            regex, i = regex + "[^/]", i + 1
        else:
            regex, i = regex + re.escape(pattern[i]), i + 1
    compiled = re.compile(regex + "$")
    return lambda path: bool(compiled.match(path))
