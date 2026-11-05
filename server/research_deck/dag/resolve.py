"""The current-value resolver R (docs/DAG.md §4.4): what every trace address fingerprints to right now.

- `Repo` reads git once per evaluation (`ls-files -s -z`, `status --porcelain=v2 -z --untracked-files=all`), or walks
  the folder when the project is not a git repository. Blob → fp results live in .cache/blobfp.sqlite.
- `Tree` is the set of files at one ref (worktree, index, a commit or branch, another worktree); `PatchedTree` lays a
  file overlay over it (config edits, code diffs) so previews resolve exactly.
- `Resolver` answers code:/dir:/cfg:/data:/env:/node:/run: addresses for one evaluation, memoized, with predicted
  (UNKNOWN) entries taking precedence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess

from ..util import git_filter_overrides
import threading
import tomllib
from pathlib import Path
from typing import Any

import yaml

from .fp import MISSING, UNKNOWN, H, fp_dir, fp_file, fp_json, git_blob_sha, glob_match, show
from .model import facet_value, parse_addr, spec_of

GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}
GIT_SAFE = ["-c", "core.quotepath=off", "-c", "core.fsmonitor=false", "-c", "color.ui=never"]
WALK_IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".research",
                ".DS_Store", ".ipynb_checkpoints"}
REV_RE = re.compile(r"^(?![-/.])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?:[~^][0-9]{0,4})*$")
NOPROBE: Any = type("NoProbe", (), {"__repr__": lambda s: "NOPROBE"})()   # env value the target platform never probed
_NONE = object()
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
SEC_RE = re.compile(r"^\s*%\s*rd:sec\s+(\S+)\s*$")
END_RE = re.compile(r"^\s*%\s*rd:end\b")


def git_bytes(root: Path, *args: str, input: bytes | None = None, timeout: int = 30) -> bytes | None:
    try:
        p = subprocess.run(["git", "-C", str(root), *GIT_SAFE, *git_filter_overrides("git", root), *args], input=input,
                           capture_output=True, timeout=timeout, env=GIT_ENV)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def git_text(root: Path, *args: str) -> str | None:
    out = git_bytes(root, *args)
    return None if out is None else out.decode("utf-8", errors="replace")


def check_rev(rev: str) -> str:
    if not REV_RE.match(rev or ""):
        raise ValueError(f"bad revision: {rev!r}")
    return rev


# ---------------------------------------------------------------- blob -> fp cache

_MEM_FP: dict[str, str] = {}
_DB_LOCK = threading.Lock()


class BlobCache:
    """A blob sha is content, so each one is fingerprinted once, ever (sqlite in .cache when the DAG exists)."""

    def __init__(self, cache_dir: Path | None):
        self.db = None
        if cache_dir is not None and (cache_dir.parent / ".gitignore").is_file():   # only once .cache/ is ignored
            try:
                cache_dir.mkdir(exist_ok=True)
                self.db = sqlite3.connect(str(cache_dir / "blobfp.sqlite"), timeout=5, check_same_thread=False,
                                          isolation_level=None)
                self.db.execute("CREATE TABLE IF NOT EXISTS fp (blob TEXT PRIMARY KEY, fp TEXT NOT NULL)")
            except sqlite3.Error:
                self.db = None

    def get(self, key: str) -> str | None:
        if key in _MEM_FP:
            return _MEM_FP[key]
        if self.db is not None:
            with _DB_LOCK:
                row = self.db.execute("SELECT fp FROM fp WHERE blob = ?", (key,)).fetchone()
            if row:
                _MEM_FP[key] = row[0]
                return row[0]
        return None

    def put(self, key: str, fp: str) -> None:
        _MEM_FP[key] = fp
        if self.db is not None:
            try:
                with _DB_LOCK:
                    self.db.execute("INSERT OR REPLACE INTO fp VALUES (?, ?)", (key, fp))
            except sqlite3.Error:
                pass


def _kind(path: str) -> str:
    return "p" if path.endswith(".py") else "j" if path.endswith(".json") else "g"


# ---------------------------------------------------------------- trees

class Tree:
    """Files at one ref: {path: blob sha, or None = read it from disk}."""

    def __init__(self, repo: "Repo", files: dict[str, str | None], rev: str | None = None, disk: Path | None = None):
        self.repo, self.files, self.rev, self.disk = repo, files, rev, disk
        self._dirs: dict[str, set[str]] | None = None
        self._fp: dict[str, str] = {}

    def read(self, path: str) -> bytes | None:
        if path not in self.files:
            return None
        blob = self.files[path]
        if self.disk is not None:
            try:
                return (self.disk / path).read_bytes()
            except OSError:
                return None
        return git_bytes(self.repo.root, "cat-file", "blob", blob) if blob else None

    def fp(self, path: str) -> str:
        if path in self._fp:
            return self._fp[path]
        if path not in self.files:
            return MISSING
        blob, kind = self.files[path], _kind(path)
        if blob and kind == "g":
            out = "g:" + blob[:12]
        elif blob and (hit := self.repo.blobs.get(f"{kind}:{blob}")):
            out = hit
        else:
            data = self.read(path)
            if data is None:
                out = MISSING
            else:
                out = fp_file(path, data)
                if kind != "g":
                    self.repo.blobs.put(f"{kind}:{blob or git_blob_sha(data)}", out)
        self._fp[path] = out
        return out

    def names(self, d: str) -> set[str]:
        if self._dirs is None:
            dirs: dict[str, set[str]] = {}
            for p in self.files:
                parts = p.split("/")
                for i in range(len(parts)):
                    dirs.setdefault("/".join(parts[:i]) or ".", set()).add(parts[i])
            self._dirs = dirs
        return self._dirs.get(d.strip("/") or ".", set())


class PatchedTree(Tree):
    """A tree with some files replaced (bytes) or removed (None): config edits and code diffs in previews."""

    def __init__(self, base: Tree, patch: dict[str, bytes | None]):
        files = dict(base.files)
        for p, data in patch.items():
            if data is None:
                files.pop(p, None)
            else:
                files[p] = "patched"
        super().__init__(base.repo, files, base.rev, base.disk)
        self.base, self.patch = base, patch

    def read(self, path: str) -> bytes | None:
        if path in self.patch:
            return self.patch[path]
        return self.base.read(path)

    def fp(self, path: str) -> str:
        if path in self.patch:
            data = self.patch[path]
            return MISSING if data is None else fp_file(path, data)
        return self.base.fp(path)


_REPO_INFO: dict[str, tuple[bool, str, Path]] = {}


def _repo_info(root: Path) -> tuple[bool, str, Path]:
    """(is a git work tree, prefix inside the repo, index path), cached per folder while .git stays the same."""
    key = str(root)
    git_dir = root / ".git"
    hit = _REPO_INFO.get(key)
    if hit and hit[0] == git_dir.exists():
        return hit
    info: tuple[bool, str, Path] = (False, "", git_dir / "index")
    if git_dir.exists():
        out = git_text(root, "rev-parse", "--is-inside-work-tree", "--show-prefix", "--git-path", "index")
        if out is not None:
            lines = out.split("\n")
            info = (True, lines[1].strip() if len(lines) > 1 else "", root / (lines[2].strip() if len(lines) > 2 else ".git/index"))
    _REPO_INFO[key] = info
    return info


class Repo:
    def __init__(self, root: Path, cache_dir: Path | None = None):
        self.root = Path(root)
        self.blobs = BlobCache(cache_dir)
        self._status: bytes | None = None
        self._trees: dict[str, Tree] = {}
        self.is_git, self._prefix, self._index = _repo_info(self.root)

    # status and HEAD -------------------------------------------------
    def status_raw(self) -> bytes:
        if self._status is None:
            # .research/ is DAG state (the store signature covers it), never code
            self._status = git_bytes(self.root, "status", "--porcelain=v2", "-z", "--branch", "--untracked-files=all",
                                     "--", ".", ":(exclude).research*") or b""
        return self._status

    def _status_entries(self) -> list[tuple[str, str, str]]:
        """[(kind, worktree status Y, path)] from porcelain v2: kind 1/2/u/?."""
        toks = self.status_raw().split(b"\0")
        out, i = [], 0
        while i < len(toks):
            t = toks[i].decode("utf-8", errors="replace")
            i += 1
            if not t or t.startswith("#"):
                continue
            kind = t[0]
            if kind == "?":
                out.append(("?", "?", t[2:]))
            elif kind in "12u":
                fields = t.split(" ", {"1": 8, "2": 9, "u": 10}[kind])
                out.append((kind, fields[1][1], fields[-1]))
                if kind == "2":
                    i += 1                       # the rename's original path
        pre = self._prefix
        return [(k, y, p[len(pre):] if pre and p.startswith(pre) else p) for k, y, p in out]

    def head(self) -> str | None:
        for t in self.status_raw().split(b"\0"):
            if t.startswith(b"# branch.oid "):
                oid = t[13:].decode()
                return None if oid.startswith("(") else oid
        return None

    def signature(self) -> str:
        """Cheap state of the code: index stat + status + stat of every dirty file (or a folder walk without git)."""
        h = hashlib.sha256()
        if self.is_git:
            try:
                st = os.stat(self._index)
                h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
            except OSError:
                pass
            h.update(self.status_raw())
            for _, y, p in self._status_entries():
                try:
                    st = os.stat(self.root / p)
                    h.update(f"{p}:{st.st_mtime_ns}:{st.st_size}".encode())
                except OSError:
                    h.update(f"{p}:gone".encode())
        else:
            for p in sorted(self._walk()):
                try:
                    st = os.stat(self.root / p)
                    h.update(f"{p}:{st.st_mtime_ns}:{st.st_size}\0".encode())
                except OSError:
                    pass
        return h.hexdigest()[:16]

    def _walk(self, limit: int = 50000) -> list[str]:
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in WALK_IGNORED and not d.startswith(".research"))
            rel = os.path.relpath(dirpath, self.root)
            for f in filenames:
                if f not in WALK_IGNORED:
                    out.append(f if rel == "." else f"{rel}/{f}".replace(os.sep, "/"))
            if len(out) > limit:
                break
        return out

    # trees ------------------------------------------------------------
    def _ls_files(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in (git_bytes(self.root, "ls-files", "-s", "-z") or b"").split(b"\0"):
            if b"\t" not in item:
                continue
            meta, path = item.split(b"\t", 1)
            mode, sha, stage = meta.decode().split()
            if mode != "160000" and stage == "0":
                out[path.decode("utf-8", errors="replace")] = sha
        return out

    def _ls_tree(self, rev: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in (git_bytes(self.root, "ls-tree", "-r", "-z", rev) or b"").split(b"\0"):
            if b"\t" in item:
                meta, path = item.split(b"\t", 1)
                parts = meta.decode().split()
                if len(parts) == 3 and parts[1] == "blob":
                    out[path.decode("utf-8", errors="replace")] = parts[2]
        return out

    def tree(self, ref: str = "worktree") -> Tree:
        if ref in self._trees:
            return self._trees[ref]
        if ref == "worktree":
            if self.is_git:
                files: dict[str, str | None] = dict(self._ls_files())
                for kind, y, p in self._status_entries():
                    if y == "D":
                        files.pop(p, None)
                    elif kind in "?u" or y != ".":
                        files[p] = None          # read it from disk
                t = Tree(self, files, disk=self.root)
                for p, blob in files.items():    # clean tracked files: content = index blob, read from disk when needed
                    if blob is not None and _kind(p) == "g":
                        t._fp[p] = "g:" + blob[:12]
            else:
                t = Tree(self, {p: None for p in self._walk()}, disk=self.root)
        elif ref == "index":
            t = Tree(self, dict(self._ls_files()))
        elif ref.startswith("wt:"):
            other = Repo(Path(ref[3:]) if Path(ref[3:]).is_absolute() else self.root / ref[3:], None)
            t = other.tree("worktree")
        else:
            rev = check_rev(ref.split(":", 1)[1] if ref.startswith(("branch:", "commit:")) else ref)
            t = Tree(self, dict(self._ls_tree(rev)) if self.is_git else {}, rev=rev)
        self._trees[ref] = t
        return t


# ---------------------------------------------------------------- config

def load_yaml(data: bytes | None) -> Any:
    if not data:
        return None
    try:
        return yaml.load(data.decode("utf-8", errors="replace"), Loader=_LOADER)
    except yaml.YAMLError:
        return None


def get_dotted(d: Any, key: str) -> Any:
    cur = d
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _NONE
    return cur


def set_dotted(d: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    cur = d
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(d, dict) or not d:
        return {prefix: d} if prefix else {}
    out: dict[str, Any] = {}
    for k, v in d.items():
        out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    return out


def merge_into(base: dict, over: dict) -> dict:
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge_into(base[k], v)
        elif "." in str(k) and not isinstance(v, dict):
            set_dotted(base, str(k), v)
        else:
            base[k] = json.loads(json.dumps(v, default=str))
    return base


def ignored_key(key: str, patterns: list[str]) -> bool:
    return any(key == p or glob_match(key.replace(".", "/"), p.replace(".", "/")) for p in patterns or [])


def yaml_set_text(text: str, key: str, value: Any) -> str:
    """Change one leaf of block-style YAML in place (comments and layout kept); otherwise re-dump the whole file."""
    def fallback() -> str:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("config file is not a mapping")
        set_dotted(data, key, value)
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    lines = text.splitlines(keepends=True)
    parts = key.split(".")
    start, end, indent = 0, len(lines), -1
    for depth, part in enumerate(parts):
        found, child = None, None
        for i in range(start, end):
            s = lines[i]
            body = s.lstrip(" ")
            if not body.strip() or body.startswith("#"):
                continue
            ind = len(s) - len(body)
            if ind <= indent:
                break
            child = ind if child is None else child
            if ind == child and re.match(rf"""(?:{re.escape(part)}|"{re.escape(part)}"|'{re.escape(part)}')\s*:(?:\s|$)""", body):
                found = i
                break
        if found is None:
            return fallback()
        if depth == len(parts) - 1:
            s = lines[found]
            head, _, rest = s.partition(":")
            nl = "\n" if s.endswith("\n") else ""
            val = rest.rstrip("\n")
            m = re.search(r"\s+#.*$", val)
            comment = m.group(0) if m and val[: m.start()].count('"') % 2 == 0 and val[: m.start()].count("'") % 2 == 0 else ""
            if not val[: len(val) - len(comment)].strip():
                return fallback()               # a block value: replace the subtree through a re-dump
            lines[found] = f"{head}: {json.dumps(value, ensure_ascii=False)}{comment}{nl}"
            out = "".join(lines)
            return out if get_dotted(yaml.safe_load(out), key) == value else fallback()
        start, indent = found + 1, child
        end = next((j for j in range(start, len(lines)) if lines[j].strip() and not lines[j].lstrip().startswith("#")
                    and len(lines[j]) - len(lines[j].lstrip(" ")) <= child), len(lines))
    return fallback()


def extract_region(text: str, sid: str) -> tuple[str | None, int | None]:
    """The text between `% rd:sec <sid>` and `% rd:end`, and the anchor's 1-based line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = SEC_RE.match(line)
        if m and m.group(1) == sid:
            body = []
            for line2 in lines[i + 1:]:
                if END_RE.match(line2):
                    break
                body.append(line2)
            return "\n".join(body), i + 1
    return None, None


# ---------------------------------------------------------------- the resolver

def ref_of(node: dict | None) -> str:
    return str(spec_of(node).get("code_ref") or "worktree") if node else "worktree"


class Resolver:
    def __init__(self, repo: Repo, nodes: dict, cfg: dict, store, *, files: dict[str, bytes | None] | None = None,
                 predicted: dict[str, Any] | None = None, runs_by_id: dict | None = None):
        self.repo, self.nodes, self.cfg, self.store = repo, nodes, cfg, store
        self.files = files or {}                 # path -> bytes | None, laid over the worktree
        self.exact: dict[str, Any] = {}          # addr -> fp (predicted, e.g. UNKNOWN)
        self.globs: list[tuple[str, Any]] = []   # (code glob, fp)
        for a, v in (predicted or {}).items():
            loc = a.split(":", 1)[1] if ":" in a else a
            (self.globs.append((loc, v)) if a.startswith("code:") and any(c in loc for c in "*?") else self.exact.__setitem__(a, v))
        self.runs_by_id = runs_by_id or {}
        self.E: dict = {}                        # set by evaluate(): output fps of earlier passes
        self._memo: dict = {}

    def tree(self, ref: str = "worktree") -> Tree:
        key = ("tree", ref)
        if key not in self._memo:
            base = self.repo.tree(ref)
            self._memo[key] = PatchedTree(base, self.files) if self.files and ref == "worktree" else base
        return self._memo[key]

    def predicted_code(self, path: str) -> Any:
        hit = self.exact.get(f"code:{path}", _NONE)
        if hit is not _NONE:
            return hit
        for pat, v in self.globs:
            if glob_match(path, pat):
                return v
        return _NONE

    def get(self, addr: str, node: dict | None = None, cell: dict | None = None) -> Any:
        if addr in self.exact:
            return self.exact[addr]
        scheme, _, loc = addr.partition(":")
        if scheme == "code":
            p = self.predicted_code(loc)
            return p if p is not _NONE else self.tree(ref_of(node)).fp(loc)
        if scheme == "dir":
            return fp_dir(self.tree(ref_of(node)).names(loc))
        if scheme == "cfg":
            return self.cfg_fp(loc, node, cell)
        if scheme == "data":
            return self.data_fp(loc)
        if scheme == "env":
            return self.env_fp(loc, node)
        return self.node_fp(addr)

    # cfg ---------------------------------------------------------------
    def merged_config(self, node: dict | None, cell: dict | None) -> dict:
        spec = spec_of(node)
        files = spec.get("config") or []
        files = [files] if isinstance(files, str) else list(files)
        key = ("cfg", tuple(files), ref_of(node), json.dumps(spec.get("overrides") or {}, sort_keys=True, default=str),
               json.dumps(cell or {}, sort_keys=True, default=str))
        if key not in self._memo:
            tree, merged = self.tree(ref_of(node)), {}
            for f in files:
                data = load_yaml(tree.read(f))
                if isinstance(data, dict):
                    merge_into(merged, data)
            merge_into(merged, spec.get("overrides") or {})
            for k, v in (cell or {}).items():
                set_dotted(merged, k, v)
            self._memo[key] = merged
        return self._memo[key]

    def cfg_fp(self, key: str, node: dict | None, cell: dict | None) -> str:
        merged = self.merged_config(node, cell)
        if key == "@keys":
            ignore = (self.cfg.get("config") or {}).get("ignore_keys") or []
            return fp_json(sorted(k for k in flatten(merged) if not ignored_key(k, ignore)))
        v = get_dotted(merged, key)
        return MISSING if v is _NONE else fp_json(v)

    def bound_value(self, bind: str) -> Any:
        path, _, key = str(bind).partition("#")
        data = load_yaml(self.tree().read(path))
        v = get_dotted(data, key) if key else data
        return None if v is _NONE else v

    # data and env -------------------------------------------------------
    def data_fp(self, ds: str) -> str:
        n = self.nodes.get(ds)
        if not n:
            return MISSING
        f = (n.get("facets") or {}).get("version") or {}
        if f.get("type") == "derived" or "value" not in f:
            manifest = self.store.dataset_manifest(ds) if self.store else None
            return H("m", json.dumps(manifest, sort_keys=True, separators=(",", ":"))) if manifest is not None else MISSING
        v = f.get("value")
        return v if isinstance(v, str) else fp_json(v)

    def env_fp(self, key: str, node: dict | None) -> Any:
        platform = spec_of(node).get("platform")
        mk = ("env", platform, key)
        if mk in self._memo:
            return self._memo[mk]
        probe = self.store.env_probe(platform) if (self.store and platform) else None
        v: Any = None
        if key.startswith("pkg:"):
            dist = re.sub(r"[-_.]+", "-", key[4:]).lower()
            v = self._lock_versions().get(dist)
            if v is None and probe:
                v = {re.sub(r"[-_.]+", "-", k).lower(): x for k, x in (probe.get("pkgs") or {}).items()}.get(dist)
        elif probe:
            v = (probe.get("key") or {}).get(key)
        out = NOPROBE if v is None else fp_json(v)
        self._memo[mk] = out
        return out

    def _lock_versions(self) -> dict[str, str]:
        if "lock" not in self._memo:
            lockfile = (self.cfg.get("env") or {}).get("lockfile")
            versions: dict[str, str] = {}
            data = self.tree().read(lockfile) if lockfile else None
            if data:
                try:
                    for pkg in tomllib.loads(data.decode("utf-8", errors="replace")).get("package", []):
                        if pkg.get("name") and pkg.get("version"):
                            versions[re.sub(r"[-_.]+", "-", pkg["name"]).lower()] = str(pkg["version"])
                except (tomllib.TOMLDecodeError, AttributeError):
                    pass
            self._memo["lock"] = versions
        return self._memo["lock"]

    # nodes -------------------------------------------------------------
    def version(self, nid: str, vid: str) -> dict | None:
        key = ("hist", nid)
        if key not in self._memo:
            self._memo[key] = {v.get("vid"): v for v in (self.store.history(nid) if self.store else [])}
        return self._memo[key].get(vid)

    def facet_fp(self, node: dict, name: str, f: dict) -> Any:
        t = f.get("type")
        if t in ("prose", "text", "json"):
            return fp_json(f.get("value"), t)
        if t == "bound":
            return fp_json(self.bound_value(f.get("bind", "")))
        if t == "artifact":
            data = self.tree().read(str(f.get("value") or f.get("path") or ""))
            return MISSING if data is None else "a:" + hashlib.sha256(data).hexdigest()[:12]
        if t == "derived":
            return self.derived_fp(node, name)
        return fp_json(f.get("value"))

    def derived_fp(self, node: dict, name: str) -> Any:
        kind = node.get("kind")
        if kind == "dataset":
            return self.data_fp(node["id"])
        if kind == "section":
            text, _ = self.section_text(node)
            return MISSING if text is None else fp_json(text, "text")
        if kind == "module":
            items = []
            for p in self.module_files(node):
                fp = self.get(f"code:{p}", None)
                if fp is UNKNOWN:
                    return UNKNOWN
                items.append([p, fp])
            return H("m", json.dumps(items))
        return MISSING

    def module_files(self, node: dict) -> list[str]:
        globs = facet_value(node, "globs") or []
        exclude = (self.cfg.get("code") or {}).get("exclude") or []
        tree = self.tree()
        return sorted(p for p in tree.files if any(glob_match(p, g) for g in globs) and not any(glob_match(p, x) for x in exclude))

    def section_text(self, node: dict) -> tuple[str | None, int | None]:
        path = facet_value(node, "file")
        data = self.tree().read(str(path)) if path else None
        return extract_region(data.decode("utf-8", errors="replace"), node["id"]) if data is not None else (None, None)

    def node_fp(self, addr: str, pin: str | None = None) -> Any:
        mk = ("node", addr, pin)
        if mk in self._memo:
            return self._memo[mk]
        try:
            a = parse_addr(addr)
        except ValueError:
            return MISSING
        if a.scheme == "run":
            run = self.runs_by_id.get(a.id)
            out = ((run or {}).get("outputs") or {}).get(a.out or "") if run else None
            return out.get("fp", MISSING) if isinstance(out, dict) else MISSING
        n = self.nodes.get(a.id)
        if n is None:
            return MISSING
        if a.out:                          # computed earlier in the pass order; not memoized (E changes in pass 1)
            ev = self.E.get(a.id)
            return ev.out_fp(a.out, a.sel) if ev is not None else MISSING
        if not a.facet and n.get("kind") == "dataset":   # input edge to a dataset: its version
            return self.data_fp(a.id)
        facets = n.get("facets") or {}
        if pin and (v := self.version(a.id, pin)):
            facets = v.get("facets") or {}
        if a.facet:
            f = facets.get(a.facet)
            out = MISSING if not isinstance(f, dict) else self.facet_fp(n, a.facet, f)
        else:
            fps = {k: self.facet_fp(n, k, f) for k, f in facets.items() if isinstance(f, dict)}
            out = UNKNOWN if any(v is UNKNOWN for v in fps.values()) else fp_json(sorted(fps.items()))
        self._memo[mk] = out
        return out


# ---------------------------------------------------------------- code diffs → file overlays

def code_patch(repo: Repo, code: dict) -> tuple[dict, dict, list[dict], list[dict]]:
    """(files_from, files_to, patched, ignored) for {diff: "A..B"} | {staged} | {worktree} | {branch}."""
    if not repo.is_git:
        raise ValueError("code previews need a git repository")
    untracked: list[str] = []
    if code.get("diff"):
        a, sep, b = str(code["diff"]).partition("..")
        if not sep:
            raise ValueError("diff must be A..B")
        a, b = check_rev(a or "HEAD"), check_rev(b or "HEAD")
        args, src, dst = ["diff", "--no-ext-diff", "--name-status", "-z", "-M", a, b], a, b
    elif code.get("staged"):
        args, src, dst = ["diff", "--no-ext-diff", "--cached", "--name-status", "-z", "-M"], "HEAD", ":"
    elif code.get("worktree"):
        args, src, dst = ["diff", "--no-ext-diff", "HEAD", "--name-status", "-z", "-M"], "HEAD", "disk"
        untracked = [p for k, _, p in repo._status_entries() if k == "?"]
    elif code.get("branch"):
        b = check_rev(str(code["branch"]))
        args, src, dst = ["diff", "--no-ext-diff", "--name-status", "-z", "-M", "HEAD", b], "HEAD", b
    else:
        return {}, {}, [], []

    def at(rev: str, path: str) -> bytes | None:
        if rev == "disk":
            try:
                return (repo.root / path).read_bytes()
            except OSError:
                return None
        return git_bytes(repo.root, "cat-file", "blob", f"{'' if rev == ':' else rev}:{path}")

    toks = [t.decode("utf-8", errors="replace") for t in (git_bytes(repo.root, *args) or b"").split(b"\0")]
    changes, i = [], 0
    while i < len(toks):
        st = toks[i]
        if not st:
            i += 1
            continue
        if st[0] in "RC":
            changes.append((st[0], toks[i + 2], toks[i + 1]))
            i += 3
        else:
            changes.append((st[0], toks[i + 1], None))
            i += 2
    changes += [("A", p, None) for p in untracked]
    changes = [c for c in changes if not c[1].startswith(".research")]       # state folders (.research*) are never code
    f_from: dict[str, bytes | None] = {}
    f_to: dict[str, bytes | None] = {}
    for st, path, old in changes:
        f_to[path] = None if st == "D" else at(dst, path)
        f_from[path] = None if st in "ARC" else at(src, path)
        if st == "R" and old:
            f_to[old], f_from[old] = None, at(src, old)
    patched, ignored = [], []
    for path in sorted(f_to):
        before = MISSING if f_from.get(path) is None else fp_file(path, f_from[path])
        after = MISSING if f_to[path] is None else fp_file(path, f_to[path])
        (patched if before != after else ignored).append(
            {"addr": f"code:{path}", "from": before, "to": after, **({} if before != after else {"note": "format/comments only"})})
    return f_from, f_to, patched, ignored


def digest(store, repo: Repo, nodes: dict | None = None) -> str:
    """base_digest: DAG files + code state + env probes + branches that code_refs read."""
    h = hashlib.sha256(repr(store.signature()).encode())
    h.update(repo.signature().encode())
    # the user's own defaults are part of every project's effective config (store.config())
    from .. import config as _config
    h.update(json.dumps(_config.user_settings().get("dag_defaults") or {}, sort_keys=True).encode())
    if repo.is_git:
        refs = sorted({ref_of(n) for n in (nodes or {}).values()} - {"worktree"})
        for ref in refs:
            if ref.startswith(("branch:", "commit:")):
                h.update(f"{ref}={git_text(repo.root, 'rev-parse', '-q', '--verify', ref.split(':', 1)[1])}".encode())
    return "d:" + h.hexdigest()[:12]


__all__ = ["Repo", "Resolver", "Tree", "code_patch", "digest", "git_bytes", "git_text", "show", "NOPROBE", "MISSING", "UNKNOWN"]
