"""Versions of a document: the panel's snapshots and the file's git history.

Snapshots live in .research/writing/snapshots/<path-slug>/<ts>.txt with an index.json per document:
  {"path": "paper/sections/intro.tex", "versions": [{"id": "snap-20261102T153012123Z", "label", "created_at",
   "file": "20261102T153012123Z.txt", "sha", "words", "auto"}]}
Git versions are read with `git log --follow` and `git show` (read-only); a project outside git has none.
Version ids: "snap-<ts>" and "git-<sha>".
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from ..projects import MAX_FILE_BYTES, project_root
from ..util import read_json, safe_join, sha256_text, slugify, write_json, write_text_atomic
from . import docs
from .store import _lock, writing_dir

MAX_SNAPSHOTS = 200
MAX_GIT_VERSIONS = 60
GIT_TIMEOUT_S = 15
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
_TS = re.compile(r"^\d{8}T\d{9}Z$")


def _slug(path: str) -> str:
    return f"{slugify(path, 'doc')[:40]}-{hashlib.sha256(path.encode('utf-8')).hexdigest()[:6]}"


def _dir(pid: str, path: str) -> Path:
    return writing_dir(pid) / "snapshots" / _slug(path)


def _index(pid: str, path: str) -> dict:
    data = read_json(_dir(pid, path) / "index.json", None) or {}
    return {"path": path, "versions": [v for v in data.get("versions") or [] if isinstance(v, dict) and v.get("id")]}


def _public(v: dict) -> dict:
    return {"id": v["id"], "label": v.get("label") or "", "created_at": v.get("created_at") or "", "source": "snapshot",
            "sha": (v.get("sha") or "")[:12], "words": v.get("words"), "auto": bool(v.get("auto"))}


def snapshot(pid: str, path: str, label: str | None = None, *, content: str | None = None, auto: bool = False) -> dict | None:
    """Snapshot the document (its file on disk unless content is given). An automatic snapshot is skipped when the
    text equals the newest snapshot; returns the DocVersion, or None when nothing was written."""
    if content is None:
        path, content = docs.read_doc(pid, path)
    else:
        path = docs.resolve_doc(pid, path)[1]
    sha = sha256_text(content)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"
    with _lock:
        index = _index(pid, path)
        if auto and index["versions"] and index["versions"][-1].get("sha") == sha:
            return None
        d = _dir(pid, path)
        write_text_atomic(d / f"{ts}.txt", content)
        entry = {"id": f"snap-{ts}", "label": (label or "").strip()[:120], "created_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                 "file": f"{ts}.txt", "sha": sha, "words": docs.word_count(content, docs.doc_kind(path) or "md"), "auto": auto}
        index["versions"].append(entry)
        # Keep the newest MAX_SNAPSHOTS, dropping automatic ones first.
        while len(index["versions"]) > MAX_SNAPSHOTS:
            victim = next((v for v in index["versions"] if v.get("auto")), index["versions"][0])
            index["versions"].remove(victim)
            (d / victim.get("file", "")).unlink(missing_ok=True)
        write_json(d / "index.json", index)
    return _public(entry)


# ------------------------------------------------------------------ git

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=GIT_TIMEOUT_S,
                          env={"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                               "HOME": str(Path.home())})


def _is_repo(root: Path) -> bool:
    try:
        return _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def _git_history(root: Path, path: str) -> list[dict]:
    """[{sha, short, date, author, subject, path}] newest first; path = the file's repo-relative path at that commit."""
    if not _is_repo(root):
        return []
    try:
        r = _git(root, "log", "--follow", f"-n{MAX_GIT_VERSIONS}", "--name-only",
                 "--format=%x1e%H%x1f%h%x1f%aI%x1f%an%x1f%s", "--", path)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out = []
    for record in r.stdout.split("\x1e"):
        if not record.strip():
            continue
        head, _, names = record.partition("\n")
        fields = head.split("\x1f")
        if len(fields) < 5:
            continue
        files = [n for n in names.splitlines() if n.strip()]
        out.append({"sha": fields[0], "short": fields[1], "date": fields[2], "author": fields[3], "subject": fields[4],
                    "path": files[0] if files else None})
    return out


def list_versions(pid: str, path: str) -> list[dict]:
    root = project_root(pid)
    path = docs.resolve_doc(pid, path)[1]
    snaps = [_public(v) for v in reversed(_index(pid, path)["versions"])]
    commits = [{"id": f"git-{c['sha']}", "label": c["subject"], "created_at": c["date"], "source": "git",
                "sha": c["short"], "author": c["author"]} for c in _git_history(root, path)]
    return snaps + commits


def version_content(pid: str, path: str, version_id: str) -> str:
    root = project_root(pid)
    path = docs.resolve_doc(pid, path)[1]
    if version_id.startswith("snap-"):
        ts = version_id[5:]
        entry = next((v for v in _index(pid, path)["versions"] if v["id"] == version_id), None)
        if not entry or not _TS.match(ts):
            raise HTTPException(404, f"no such snapshot: {version_id}")
        try:
            # the file name comes from index.json, which is on disk and editable: keep it inside the snapshot folder
            return safe_join(_dir(pid, path), str(entry.get("file") or "")).read_text(encoding="utf-8")
        except (OSError, HTTPException):
            raise HTTPException(404, f"snapshot file is missing: {version_id}")
    if version_id.startswith("git-"):
        sha = version_id[4:].lower()
        if not _SHA.match(sha):
            raise HTTPException(400, "bad commit id")
        # The path as of that commit (the file may have been renamed since), else the current one.
        at = next((c["path"] for c in _git_history(root, path) if c["sha"].startswith(sha) and c["path"]), None)
        specs = [f"{sha}:{at}"] if at else []
        specs.append(f"{sha}:./{path}")
        for spec in specs:
            try:
                r = _git(root, "show", spec)
            except (OSError, subprocess.SubprocessError):
                continue
            if r.returncode == 0:
                if len(r.stdout) > MAX_FILE_BYTES:
                    raise HTTPException(413, "version too large")
                return r.stdout
        raise HTTPException(404, f"{path} is not in commit {sha[:12]}")
    raise HTTPException(404, f"unknown version: {version_id}")
