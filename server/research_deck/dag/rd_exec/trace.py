"""rd-exec: snapshot ref, the traced job, the verifying trace and output extraction (docs/DAG.md §3, §4.3). Stdlib only;
fingerprints come from research_deck.dag.fp, which is itself stdlib-only.

spec.json is the node's `spec` facet, or {"node", "spec", "outputs", "context"} where context (filled by the dashboard,
see service.exec_spec) carries what the host cannot know: ignore_keys, env_keys, datasets {id: {path, version}},
modules [{id, globs, opaque}], inputs {node:… address: fp at start}, code_roots.
"""
from __future__ import annotations

import json
import math
import os
import platform as _platform
import re
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import fp as F
from .rd_trace import rd as rdmod

TRACE_DIR = Path(__file__).resolve().parent / "rd_trace"
IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".DS_Store"}
MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024
T95 = {1: 12.71, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git(root: Path, *args: str, env: dict | None = None, input: bytes | None = None) -> bytes | None:
    try:
        p = subprocess.run(["git", "-C", str(root), "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", *args],
                           capture_output=True, input=input, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", **(env or {})}, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def is_git(root: Path) -> bool:
    return (root / ".git").exists() and git(root, "rev-parse", "--is-inside-work-tree") is not None


def manifest(root: Path) -> list[str]:
    """Files the job could depend on as code: tracked + untracked-not-ignored (or every file without git)."""
    if is_git(root):
        tracked = (git(root, "ls-files", "-z") or b"").decode("utf-8", "replace").split("\0")
        others = (git(root, "ls-files", "-z", "--others", "--exclude-standard") or b"").decode("utf-8", "replace").split("\0")
        return sorted({p for p in tracked + others if p and (root / p).is_file()})
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED and not d.startswith(".research")]
        rel = os.path.relpath(dirpath, root)
        out += [f if rel == "." else f"{rel}/{f}" for f in filenames if f not in IGNORED]
    return sorted(out)


def snapshot(root: Path, run_id: str) -> dict:
    """refs/rd/runs/<id>: a commit of the exact code, dirty and untracked-not-ignored files included (temporary index)."""
    if not is_git(root):
        return {"head": None, "snapshot": None, "dirty": None}
    head = (git(root, "rev-parse", "-q", "--verify", "HEAD") or b"").decode().strip() or None
    status = (git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all") or b"").decode("utf-8", "replace")
    paths, toks, i = [], status.split("\0"), 0
    while i < len(toks):
        t = toks[i]
        i += 1
        if len(t) > 3:
            p = t[3:]
            if t[0] in "RC":
                i += 1
            if not p.startswith(".research") and (not (root / p).is_file() or (root / p).stat().st_size <= MAX_SNAPSHOT_BYTES):
                paths.append(p)
    with tempfile.TemporaryDirectory(prefix="rd-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if git(root, "read-tree", head or "--empty", env=env) is None:
            return {"head": head, "snapshot": None, "dirty": bool(paths)}
        if paths:
            git(root, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", env=env, input="\0".join(paths).encode())
        tree = (git(root, "write-tree", env=env) or b"").decode().strip()
    if not tree:
        return {"head": head, "snapshot": None, "dirty": bool(paths)}
    args = ["commit-tree", tree, "-m", f"rd run {run_id}"] + (["-p", head] if head else [])
    commit = (git(root, "-c", "user.name=rd-exec", "-c", "user.email=rd-exec@localhost", *args) or b"").decode().strip()
    ref = f"refs/rd/runs/{run_id}"
    if commit and git(root, "update-ref", ref, commit) is not None:
        return {"head": head[:7] if head else None, "snapshot": ref, "dirty": bool(paths), "commit": commit}
    return {"head": head[:7] if head else None, "snapshot": None, "dirty": bool(paths)}


def probe_env() -> dict:
    """python, and the NVIDIA GPU when nvidia-smi exists: gpu_model, gpu_count, driver_major, cuda."""
    key: dict = {"python": _platform.python_version()}
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            q = subprocess.run([smi, "--query-gpu=name,driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
            rows = [r.split(",") for r in q.stdout.strip().splitlines() if r.strip()]
            if rows:
                key.update(gpu_model=rows[0][0].strip(), gpu_count=len(rows), driver_major=rows[0][1].strip().split(".")[0])
            head = subprocess.run([smi], capture_output=True, text=True, timeout=20).stdout
            m = re.search(r"CUDA Version:\s*([\d.]+)", head)
            if m:
                key["cuda"] = m.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return key


def read_dumps(trace_dir: Path) -> tuple[dict[str, set[str]], list[dict]]:
    events: dict[str, set[str]] = {"R": set(), "W": set(), "L": set(), "X": set()}
    dumps: list[dict] = []
    for f in sorted(trace_dir.glob("trace.*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, list) and len(rec) == 2 and rec[0] in events:
                events[rec[0]].add(rec[1])
            elif isinstance(rec, dict):
                dumps.append(rec)
    return events, dumps


def repo_rel(p: str, root: Path) -> str | None:
    try:
        rel = Path(os.path.realpath(p)).relative_to(root)
    except ValueError:
        return None
    s = rel.as_posix()
    return None if s.startswith("..") else s


def build_trace(spec: dict, cell: dict, events: dict, dumps: list[dict], root: Path, files: list[str], entry: list[str],
                context: dict, env: dict) -> tuple[dict, list[str], str]:
    """The verifying trace: every code/dir/cfg/data/env/input item the job read, fingerprinted on this host."""
    files_set = set(files)
    config_chain = set(spec.get("config") or [])
    datasets = context.get("datasets") or {}
    reads = set(events["R"]) | {m for d in dumps for m in d.get("modules") or []}
    reads |= {str(root / p) for p in entry}
    for g in spec.get("code_inputs") or []:
        reads |= {str(root / p) for p in files if F.glob_match(p, g)}
    for argv in events["X"]:
        for a in json.loads(argv):
            if isinstance(a, str) and (root / a).is_file():
                reads.add(str(root / a))
    reads -= set(events["W"])                     # files the job wrote itself are outputs, not inputs
    T: dict[str, dict] = {}
    untracked: list[str] = []

    def dataset_of(path: str) -> str | None:
        for ds, info in datasets.items():
            base = str(info.get("path") or "")
            if base and (path == base.rstrip("/") or path.startswith(base.rstrip("/") + "/")):
                return ds
        return None

    for p in sorted(reads):
        rel = repo_rel(p, root)
        ds = dataset_of(rel if rel is not None else os.path.realpath(p))
        if ds:
            T[f"data:{ds}"] = {"fp": str(datasets[ds].get("version") or F.MISSING)}
            continue
        if rel is None:
            continue                              # outside the project: packages are env:pkg:* below
        if rel in config_chain:
            continue                              # the declared chain is tracked per key below
        if rel not in files_set or rel.startswith(".research"):
            untracked.append(rel)
            continue
        data = (root / rel).read_bytes()
        T[f"code:{rel}"] = {"fp": F.fp_file(rel, data), "blob": F.git_blob_sha(data)[:12]}
    for d in sorted(events["L"]):
        rel = repo_rel(d, root)
        if rel is not None and not rel.startswith(".research"):
            rel = rel or "."
            prefix = "" if rel == "." else rel + "/"
            T[f"dir:{rel}"] = {"fp": F.fp_dir({p[len(prefix):].split("/")[0] for p in files if p.startswith(prefix)})}
    for m in context.get("modules") or []:
        if m.get("opaque") and any(F.glob_match(a[5:], g) for a in T if a.startswith("code:") for g in m.get("globs") or []):
            for p in files:
                if any(F.glob_match(p, g) for g in m.get("globs") or []):
                    data = (root / p).read_bytes()
                    T[f"code:{p}"] = {"fp": F.fp_file(p, data), "blob": F.git_blob_sha(data)[:12]}
    cfg_reads: dict = {}
    for d in dumps:
        cfg_reads.update(d.get("cfg_reads") or {})
    ignore = context.get("ignore_keys") or []
    if cfg_reads:
        for k, r in cfg_reads.items():
            T[f"cfg:{k}"] = {"fp": F.MISSING, "v": None} if r.get("miss") else {"fp": F.fp_json(r.get("v")), "v": r.get("v")}
    elif spec.get("config"):                      # fallback: every leaf plus the key set
        merged = rdmod.resolve(spec.get("config"), overrides_of(spec, cell), str(root))
        leaves = {k: v for k, v in flatten(merged).items()
                  if not any(k == pat or F.glob_match(k.replace(".", "/"), pat.replace(".", "/")) for pat in ignore)}
        T.update({f"cfg:{k}": {"fp": F.fp_json(v), "v": v} for k, v in leaves.items()})
        T["cfg:@keys"] = {"fp": F.fp_json(sorted(leaves))}
    python = next((d.get("python") for d in dumps if d.get("python")), None) or env.get("python")
    env_keys = spec.get("env_keys") or context.get("env_keys") or ["python", "gpu_model", "gpu_count", "driver_major", "cuda", "pkg:*"]
    probe = {**env, "python": python}
    for k in env_keys:
        if not k.startswith("pkg:") and probe.get(k) is not None:
            T[f"env:{k}"] = {"fp": F.fp_json(probe[k]), "v": probe[k]}
    if any(k.startswith("pkg:") for k in env_keys):
        want = {k[4:] for k in env_keys if k.startswith("pkg:")}
        for d in dumps:
            for dist, ver in (d.get("pkgs") or {}).items():
                if "*" in want or dist in want:
                    T[f"env:pkg:{dist}"] = {"fp": F.fp_json(ver), "v": ver}
    T.update({a: {"fp": f} for a, f in (context.get("inputs") or {}).items()})
    if not dumps and not spec.get("code_inputs"):  # coarse: every file under the code roots
        for p in files:
            if any(F.glob_match(p, r) for r in context.get("code_roots") or ["src"]):
                data = (root / p).read_bytes()
                T.setdefault(f"code:{p}", {"fp": F.fp_file(p, data), "blob": F.git_blob_sha(data)[:12]})
    quality = "traced" if dumps else ("declared" if spec.get("code_inputs") else "coarse")
    return T, sorted(set(untracked)), quality


def flatten(d, prefix: str = "") -> dict:
    if not isinstance(d, dict) or not d:
        return {prefix: d} if prefix else {}
    out: dict = {}
    for k, v in d.items():
        out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    return out


def overrides_of(spec: dict, cell: dict) -> dict:
    over = json.loads(json.dumps(spec.get("overrides") or {}))
    for k, v in (cell or {}).items():
        over[k] = v
    return over


def extract(src: str, cwd: Path, stdout: str):
    """`file.json:$.a.b[0]` or `stdout:<regex with one group>` → value (None when absent)."""
    if src.startswith("stdout:"):
        m = re.findall(src[7:], stdout)
        if not m:
            return None
        v = m[-1] if isinstance(m[-1], str) else m[-1][0]
        try:
            return float(v) if "." in v or "e" in v.lower() else int(v)
        except ValueError:
            return v
    path, _, expr = src.partition(":")
    try:
        data = json.loads((cwd / path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for tok in re.findall(r"\.([^.\[\]]+)|\[(\d+)\]", expr.lstrip("$")):
        key, idx = tok
        try:
            data = data[int(idx)] if idx else data[key]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def combine(values: list) -> dict:
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not nums or len(nums) != len(values):
        return {"value": values[-1] if values else None, "n": len(values)}
    mean = statistics.fmean(nums)
    out = {"value": round(mean, 10), "n": len(nums)}
    if len(nums) > 1:
        half = T95.get(len(nums) - 1, 1.96) * statistics.stdev(nums) / math.sqrt(len(nums))
        out["ci95"] = [round(mean - half, 10), round(mean + half, 10)]
    return out


def run_job(spec_doc: dict, cell: dict, command: list[str], root: Path, *, replicates: int | None = None,
            run_id: str | None = None, platform: str | None = None) -> dict:
    spec = spec_doc.get("spec") if isinstance(spec_doc.get("spec"), dict) else spec_doc
    outputs = spec_doc.get("outputs") or {}
    context = spec_doc.get("context") or {}
    root = root.resolve()
    run_id = run_id or datetime.now(timezone.utc).strftime("r-%Y%m%d-%H%M-") + secrets.token_hex(2)
    files = manifest(root)
    git_info = snapshot(root, run_id)
    env = probe_env()
    reps = max(1, int(replicates or spec.get("replicates") or 1))
    started, t0 = now(), time.time()
    values: dict[str, list] = {k: [] for k, o in outputs.items() if isinstance(o, dict) and o.get("from")}
    state, code = "succeeded", 0
    with tempfile.TemporaryDirectory(prefix="rd-trace-") as tdir:
        envv = {**os.environ, "RD_TRACE_DIR": tdir, "RD_ROOT": str(root), "RD_CELL": F.cell_id(cell),
                "RD_CELL_VALUES": json.dumps(cell), "RD_OVERRIDES": json.dumps(overrides_of(spec, cell)),
                "RD_CONFIG": json.dumps(list(spec.get("config") or [])),
                "PYTHONPATH": os.pathsep.join([str(TRACE_DIR), *filter(None, [os.environ.get("PYTHONPATH")])])}
        for _ in range(reps):
            proc = subprocess.run(command, cwd=str(root), env=envv, capture_output=True, text=True)
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            code = proc.returncode
            if code != 0:
                state = "failed"
                break
            for name in values:
                values[name].append(extract(outputs[name]["from"], root, proc.stdout))
        events, dumps = read_dumps(Path(tdir))
    entry = [a for a in command[1:] if (root / a).is_file()][:1]
    trace, untracked, quality = build_trace(spec, cell, events, dumps, root, files, entry, context, env)
    outs = {}
    for name, vals in values.items():
        vals = [v for v in vals if v is not None]
        if vals:
            outs[name] = {**combine(vals), **({"unit": outputs[name]["unit"]} if outputs[name].get("unit") else {})}
    hours = (time.time() - t0) / 3600
    return {"id": run_id, "node": spec_doc.get("node"), "cell": F.cell_id(cell), "cell_values": cell, "state": state,
            "exit_code": code, "platform": platform or spec.get("platform") or _platform.node(), "started": started,
            "ended": now(), "gpu_hours": round(hours * float(spec.get("gpus") or 0), 6), "git": git_info,
            "fp_algo": F.FP_ALGO, "trace_quality": quality, "spec_fp": F.spec_fp(spec), "trace": trace,
            "untracked_reads": untracked, "outputs": outs, "env": {"key": {**env, "python": trace.get("env:python", {}).get("v", env.get("python"))}}}
