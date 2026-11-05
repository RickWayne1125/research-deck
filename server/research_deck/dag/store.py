"""The DAG on disk (docs/DAG.md §6): node heads, append-only history, immutable runs, proposals, snapshots, the event log.

Every write happens under `locked()` (a thread lock plus an fcntl lock on .cache/lock, so two servers or a CLI never
interleave). A store can also be read-only over the files of a past commit (`GET /graph?at=<commit>`).
"""
from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import re
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import yaml

from .. import config as _config

from ..util import append_jsonl, now_iso, read_json, read_yaml, write_json, write_text_atomic, write_yaml

log = logging.getLogger("research_deck.dag")

DAG_DIR = ".research/dag"            # the default project state folder's DAG; a project may name another state folder
SUBDIRS = ("nodes", "history", "runs", "proposals", "snapshots", "envs", "datasets", ".cache")
def gitattributes(dag_rel: str) -> list[str]:
    return [f"{dag_rel}/history/*.jsonl merge=union", f"{dag_rel}/log.jsonl merge=union"]

# §6 defaults, adjusted by §11: neutral (no autocommit, no agent run queueing, advisory gates). A user turns them
# on for all their projects in ~/.research-deck/settings.json (dag_defaults) or per project in config.yaml.
DEFAULT_CONFIG: dict[str, Any] = {
    "schema": "rd-dag/1",
    "fp_algo": "rd/1",
    "home_branch": "main",
    "code": {"roots": ["src", "bench", "proto", "plots"], "exclude": ["**/*.md", "notebooks/**", "**/test_*.py"]},
    "config": {"roots": ["configs"], "ignore_keys": ["output_dir", "run_name", "wandb.*", "log_level"]},
    "datasets_roots": {"local": "data/"},
    "env": {"key": ["python", "gpu_model", "gpu_count", "driver_major", "cuda", "pkg:*"], "lockfile": "uv.lock"},
    "outputs": {"default_tol": {"rel": 0.03}, "sig": 4},
    "paper": {"root": "paper", "macros": "paper/generated/rdvalues.tex"},
    "gates": {"blocking": False, "G1": {"min_refs": 5, "baseline_repro_tol": 0.10},
              "G2": {"min_workloads": 2, "min_replicates": 3}, "G3": {"min_headroom": 1.3},
              "G4": {"min_captured": 0.5, "min_alternatives": 2}, "G5": {"microbench_vs_proto": 0.8}},
    "policy": {"agent_auto_apply": "safe",
               "agent_auto_run": {"max_gpu_hours_per_day": 0, "platforms": [], "kinds": ["experiment", "figure"]}},
    "autocommit": {"enabled": False, "debounce_s": 30, "paths": ["{dag}", "paper/generated"]},   # {dag} = this store's DAG folder
}

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_DEPTH = threading.local()
_RUN_CACHE: dict[str, tuple[tuple, dict]] = {}       # path -> (stat signature, record)


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def safe_name(name: str, what: str = "name") -> str:
    if not isinstance(name, str) or not _SAFE_NAME.match(name) or ".." in name:
        raise ValueError(f"bad {what}: {name!r}")
    return name


def cell_dir(cell: str) -> str:
    return quote(cell, safe="=,._-+") or "_"


class DagStore:
    def __init__(self, root: Path, files: dict[str, bytes] | None = None, at: str | None = None, state: str = ".research"):
        self.root = Path(root)
        self.state = state                      # the project's state folder under root (".research" or ".research-<slug>")
        self.dag_rel = f"{state}/dag"
        self.dir = self.root / self.dag_rel
        self._files = files          # read-only view of a past commit: {path under .research/dag: bytes}
        self.at = at
        self._run_paths: dict[str, Path] = {}

    # ------------------------------------------------------------ reading
    @property
    def readonly(self) -> bool:
        return self._files is not None

    @property
    def exists(self) -> bool:
        return bool(self._files) if self.readonly else self.dir.is_dir()

    def _text(self, rel: str) -> str | None:
        if self._files is not None:
            b = self._files.get(rel)
            return None if b is None else b.decode("utf-8", errors="replace")
        try:
            return (self.dir / rel).read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return None

    def _list(self, sub: str, suffix: str) -> list[str]:
        """Paths (relative to the DAG dir) of files under sub/ ending with suffix."""
        if self._files is not None:
            return sorted(p for p in self._files if p.startswith(sub + "/") and p.endswith(suffix))
        base = self.dir / sub
        if not base.is_dir():
            return []
        return sorted(p.relative_to(self.dir).as_posix() for p in base.rglob(f"*{suffix}") if p.is_file())

    def _yaml(self, rel: str) -> Any:
        t = self._text(rel)
        try:
            return yaml.load(t, Loader=_LOADER) if t else None
        except yaml.YAMLError as e:
            log.warning("unreadable %s: %s", rel, e)
            return None

    def _jsonl(self, rel: str) -> list[dict]:
        out = []
        for line in (self._text(rel) or "").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def config(self) -> dict:
        # repository defaults <- the user's own defaults (~/.research-deck/settings.json) <- this project's config.yaml
        base = deep_merge(DEFAULT_CONFIG, (_config.user_settings().get("dag_defaults") or {}))
        cfg = deep_merge(base, self._yaml("config.yaml") or {})
        if self._text("config.yaml") is None:      # no config yet: take the code roots from project.yaml
            roots = ((read_yaml(self.root / self.state / "project.yaml", {}) or {}).get("code") or {}).get("roots")
            if roots:
                cfg["code"]["roots"] = list(dict.fromkeys([*roots, *cfg["code"]["roots"]]))
        return cfg

    def nodes(self) -> dict[str, dict]:
        out = {}
        for rel in self._list("nodes", ".yaml"):
            n = self._yaml(rel)
            if isinstance(n, dict) and n.get("id"):
                out[n["id"]] = n
        return out

    def node(self, nid: str) -> dict | None:
        n = self._yaml(f"nodes/{nid}.yaml")
        return n if isinstance(n, dict) else None

    def history(self, nid: str) -> list[dict]:
        return self._jsonl(f"history/{nid}.jsonl")

    def history_ids(self) -> list[str]:
        return [Path(p).stem for p in self._list("history", ".jsonl")]

    def runs(self) -> list[dict]:
        out = []
        for rel in self._list("runs", ".json"):
            if self._files is not None:
                try:
                    out.append(json.loads(self._files[rel]))
                except ValueError:
                    pass
                continue
            p = self.dir / rel
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            sig = (st.st_mtime_ns, st.st_size)
            hit = _RUN_CACHE.get(str(p))
            if hit and hit[0] == sig:
                rec = hit[1]
            else:
                rec = read_json(p, None)
                if not isinstance(rec, dict):
                    continue
                _RUN_CACHE[str(p)] = (sig, rec)
            self._run_paths[rec.get("id", "")] = p
            out.append(rec)
        return out

    def events(self) -> list[dict]:
        return self._jsonl("log.jsonl")

    def proposals(self) -> list[dict]:
        return [p for p in (self._yaml(r) for r in self._list("proposals", ".yaml")) if isinstance(p, dict)]

    def proposal(self, pid: str) -> dict | None:
        p = self._yaml(f"proposals/{safe_name(pid, 'proposal id')}.yaml")
        return p if isinstance(p, dict) else None

    def snapshots(self) -> list[dict]:
        return [s for s in (self._yaml(r) for r in self._list("snapshots", ".yaml")) if isinstance(s, dict)]

    def snapshot(self, name: str) -> dict | None:
        s = self._yaml(f"snapshots/{safe_name(name, 'snapshot name')}.yaml")
        return s if isinstance(s, dict) else None

    def env_probe(self, platform: str) -> dict | None:
        if not platform or not _SAFE_NAME.match(platform):
            return None
        t = self._text(f"envs/{platform}.json")
        try:
            return json.loads(t) if t else None
        except ValueError:
            return None

    def dataset_manifest(self, ds: str) -> Any:
        t = self._text(f"datasets/{ds}.manifest.json")
        try:
            return json.loads(t) if t else None
        except ValueError:
            return None

    def signature(self) -> tuple:
        """(newest mtime, file count, total bytes) of everything under the DAG dir except .cache."""
        if self._files is not None:
            return ("at", self.at, len(self._files))
        newest = count = size = 0
        if self.dir.is_dir():
            for dirpath, dirnames, filenames in os.walk(self.dir):
                if dirpath == str(self.dir):
                    dirnames[:] = [d for d in dirnames if d != ".cache"]
                for f in filenames:
                    try:
                        st = os.stat(os.path.join(dirpath, f))
                    except FileNotFoundError:
                        continue
                    newest, count, size = max(newest, st.st_mtime_ns), count + 1, size + st.st_size
        return (newest, count, size)

    # ------------------------------------------------------------ writing
    def _w(self) -> None:
        if self.readonly:
            raise PermissionError("a past state of the DAG is read-only")

    def ensure(self) -> None:
        """Create the layout, config.yaml, .gitignore (.cache/) and the merge=union attributes of a git project."""
        self._w()
        for sub in SUBDIRS:
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        if not (self.dir / "config.yaml").exists():
            # Only this project's own settings: the defaults stay layered (repository <- ~/.research-deck/settings.json),
            # so changing the user's defaults later still reaches this project.
            own: dict = {"schema": DEFAULT_CONFIG["schema"]}
            roots = ((read_yaml(self.root / self.state / "project.yaml", {}) or {}).get("code") or {}).get("roots")
            if roots:
                own["code"] = {"roots": list(dict.fromkeys([*roots, *DEFAULT_CONFIG["code"]["roots"]]))}
            write_text_atomic(self.dir / "config.yaml",
                              "# This project's DAG settings. Defaults: the repository's, then dag_defaults in\n"
                              "# ~/.research-deck/settings.json; anything set here overrides both (docs/DAG.md §6, §11).\n"
                              + yaml.safe_dump(own, allow_unicode=True, sort_keys=False))
        if not (self.dir / ".gitignore").exists():
            write_text_atomic(self.dir / ".gitignore", ".cache/\n")
        if (self.root / ".git").exists():
            ga = self.root / ".gitattributes"
            have = ga.read_text(encoding="utf-8").splitlines() if ga.exists() else []
            missing = [line for line in gitattributes(self.dag_rel) if line not in have]
            if missing:
                write_text_atomic(ga, "\n".join([*have, *missing]) + "\n")

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Re-entrant within a thread; exclusive across threads (RLock) and processes (fcntl on .cache/lock)."""
        self._w()
        key = str(self.dir.resolve())
        with _LOCKS_GUARD:
            tlock = _THREAD_LOCKS.setdefault(key, threading.RLock())
        depths = _DEPTH.__dict__.setdefault("d", {})
        with tlock:
            if depths.get(key):
                depths[key] += 1
                try:
                    yield
                finally:
                    depths[key] -= 1
                return
            (self.dir / ".cache").mkdir(parents=True, exist_ok=True)
            with open(self.dir / ".cache" / "lock", "w") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                depths[key] = 1
                try:
                    yield
                finally:
                    depths[key] = 0
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def write_node(self, node: dict) -> None:
        self._w()
        write_yaml(self.dir / "nodes" / f"{node['id']}.yaml", node)

    def delete_node(self, nid: str) -> None:
        self._w()
        (self.dir / "nodes" / f"{nid}.yaml").unlink(missing_ok=True)

    def append_history(self, nid: str, line: dict) -> None:
        self._w()
        append_jsonl(self.dir / "history" / f"{nid}.jsonl", line)

    def run_path(self, rec: dict) -> Path:
        return self.dir / "runs" / rec["node"] / cell_dir(rec.get("cell") or "_") / f"{safe_name(rec['id'], 'run id')}.json"

    def find_run_path(self, run_id: str) -> Path | None:
        if run_id not in self._run_paths:
            self.runs()
        return self._run_paths.get(run_id)

    def write_run(self, rec: dict) -> Path:
        self._w()
        path = self.find_run_path(rec["id"]) or self.run_path(rec)
        write_json(path, rec)
        self._run_paths[rec["id"]] = path
        return path

    def write_proposal(self, prop: dict) -> None:
        self._w()
        write_yaml(self.dir / "proposals" / f"{safe_name(prop['id'], 'proposal id')}.yaml", prop)

    def next_proposal_id(self) -> str:
        nums = [int(m.group(1)) for p in self._list("proposals", ".yaml") if (m := re.search(r"p-(\d+)\.yaml$", p))]
        return f"p-{max(nums, default=0) + 1:04d}"

    def write_snapshot(self, snap: dict) -> None:
        self._w()
        write_yaml(self.dir / "snapshots" / f"{safe_name(snap['name'], 'snapshot name')}.yaml", snap)

    def append_events(self, events: list[dict]) -> list[dict]:
        """Give each event the next e-NNNNNN id and its timestamp; append to log.jsonl."""
        self._w()
        path = self.dir / "log.jsonl"
        last = 0
        if path.exists():
            with path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 4096))
                tail = f.read().decode("utf-8", errors="replace").strip().splitlines()
            for line in reversed(tail):
                m = re.search(r'"e":\s*"e-(\d+)"', line)
                if m:
                    last = int(m.group(1))
                    break
        out = []
        for ev in events:
            last += 1
            rec = {"e": f"e-{last:06d}", "at": ev.get("at") or now_iso(), **{k: v for k, v in ev.items() if k not in ("e", "at")}}
            append_jsonl(path, rec)
            out.append(rec)
        if out:
            maybe_autocommit(self, out)
        return out


# ---------------------------------------------------------------- reading a past commit

def at_commit(root: Path, rev: str, state: str = ".research") -> DagStore:
    """A read-only store over <state>/dag as it was at a commit (git ls-tree + cat-file --batch)."""
    from .resolve import git_bytes   # noqa: PLC0415 — resolve imports store helpers
    dag_rel = f"{state}/dag"
    listing = git_bytes(root, "ls-tree", "-r", "-z", rev, "--", dag_rel)
    entries = []
    for item in (listing or b"").split(b"\0"):
        if b"\t" in item:
            meta, path = item.split(b"\t", 1)
            parts = meta.split()
            if len(parts) == 3 and parts[1] == b"blob":
                entries.append((parts[2].decode(), path.decode()))
    files: dict[str, bytes] = {}
    if entries:
        proc = subprocess.run(["git", "-C", str(root), "-c", "core.fsmonitor=false", "cat-file", "--batch"], input="\n".join(s for s, _ in entries).encode() + b"\n",
                              capture_output=True, timeout=60)
        buf, pos = proc.stdout, 0
        for _, path in entries:
            nl = buf.index(b"\n", pos)
            size = int(buf[pos:nl].split()[2])
            files[path[len(dag_rel) + 1:]] = buf[nl + 1: nl + 1 + size]
            pos = nl + 1 + size + 1
    return DagStore(root, files=files, at=rev, state=state)


# ---------------------------------------------------------------- autocommit (off by default, §11)

_COMMIT_TIMERS: dict[str, threading.Timer] = {}
_PENDING_EVENTS: dict[str, list[str]] = {}


def maybe_autocommit(store: DagStore, events: list[dict]) -> None:
    cfg = store.config().get("autocommit") or {}
    if not cfg.get("enabled") or not (store.root / ".git").exists():
        return
    key = str(store.root)
    _PENDING_EVENTS.setdefault(key, []).extend(e["e"] for e in events)
    actor = events[-1].get("by") or "system"
    if key in _COMMIT_TIMERS:
        _COMMIT_TIMERS[key].cancel()
    paths = [str(x).replace("{dag}", store.dag_rel).replace(DAG_DIR, store.dag_rel) for x in (cfg.get("paths") or ["{dag}"])]
    t = threading.Timer(float(cfg.get("debounce_s", 30)), _autocommit, args=(store, paths, actor))
    t.daemon = True
    _COMMIT_TIMERS[key] = t
    t.start()


def _autocommit(store: DagStore, paths: list[str], actor: str) -> None:
    """`git commit --only` of the DAG paths, only on home_branch; never code."""
    from .resolve import git_text   # noqa: PLC0415
    key = str(store.root)
    branch = (git_text(store.root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    if branch != store.config().get("home_branch", "main"):
        return                                  # files stay written; the UI shows the hold
    ids = _PENDING_EVENTS.pop(key, [])
    existing = [p for p in paths if (store.root / p).exists()]
    if not ids or not existing:
        return
    git_text(store.root, "add", "--", *existing)
    msg = f"dag: {len(ids)} event(s)\n\nRD-Events: {ids[0]}..{ids[-1]}\nRD-Actor: {actor}\n"
    git_text(store.root, "commit", "--only", "-m", msg, "--", *existing)
