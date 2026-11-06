"""Small helpers shared by every module: time, ids, safe paths inside a project, atomic JSON/YAML files."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(text: str, fallback: str = "item") -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s[:48] or fallback


def safe_join(root: Path, rel: str) -> Path:
    """Resolve rel inside root; refuse anything that escapes it (.., absolute paths, symlinks out)."""
    if rel is None:
        raise HTTPException(400, "path is required")
    rel = rel.replace("\\", "/").lstrip("/")
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise HTTPException(400, f"path escapes the project: {rel}")
    return target


def rel_to(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        # mkstemp creates 0600; keep the file's own mode (an executable script stays executable)
        try:
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


class _NoAliasLoader(yaml.SafeLoader):
    """Research Deck's own YAML (project.yaml, glossary, ...) never needs anchors; refusing aliases stops alias bombs."""
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not allowed in Research Deck files")
        return super().compose_node(parent, index)


def read_yaml(path: Path, default: Any = None) -> Any:
    try:
        return loads_yaml(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def loads_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_NoAliasLoader)


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):   # a shared object is written out again, never as &id001 (read_yaml refuses aliases)
        return True


def write_yaml(path: Path, data: Any) -> None:
    write_text_atomic(path, yaml.dump(data, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False))


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def run_killable(cmd: list[str], *, timeout: float, cwd=None, env=None, input: str | None = None) -> subprocess.CompletedProcess:
    """subprocess.run in its own process group: on timeout the whole group (the script and anything it started) is
    killed, not only the direct child. Raises subprocess.TimeoutExpired like subprocess.run."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                out, err = proc.communicate(timeout=2)
                break
            except subprocess.TimeoutExpired:
                continue
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


_FILTER_CACHE: dict[str, tuple[float, list[str]]] = {}


def git_filter_overrides(git: str, cwd) -> list[str]:
    """-c options that switch off every filter driver configured for the repo at cwd. A clean/smudge/process filter
    in .git/config (or a global one) runs arbitrary commands during `git status` / `git diff`; reading a project
    must never run its commands. Cached by the repo config's mtime."""
    key = str(cwd)
    try:
        mtime = max((Path(cwd) / ".git" / "config").stat().st_mtime, Path.home().joinpath(".gitconfig").stat().st_mtime
                    if Path.home().joinpath(".gitconfig").exists() else 0)
    except OSError:
        mtime = 0
    hit = _FILTER_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        out = subprocess.run([git, "-C", key, "config", "--get-regexp", r"^filter\."], capture_output=True, text=True,
                             timeout=10, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    names = {m.group(1) for m in re.finditer(r"^filter\.(.+)\.(?:clean|smudge|process|required)\s", out, re.M)}
    opts: list[str] = []
    for n in sorted(names):
        opts += ["-c", f"filter.{n}.clean=", "-c", f"filter.{n}.smudge=", "-c", f"filter.{n}.process=",
                 "-c", f"filter.{n}.required=false"]
    _FILTER_CACHE[key] = (mtime, opts)
    return opts
