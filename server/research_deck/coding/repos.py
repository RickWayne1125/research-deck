"""Which git repository the Coding panel looks at.

A project is usually one repository (its root, or a folder inside one). A research *workspace* can instead hold several
repositories side by side — a fork, its worktrees, an upstream checkout — listed in project.yaml:

    code:
      repos: [service-impl, service-pr, upstream]     # folders under the project root, each a git work tree

Routes take `?repo=<folder>`; without it the project root is used when it is in a repository, else the first listed
repo. Paths in responses stay relative to the project root (the repo folder is prefixed), so links, explanations and
the agents' file reads work the same for both layouts.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from ..projects import project_config, project_root
from ..util import safe_join
from . import git


def configured(pid: str) -> list[str]:
    repos = (project_config(pid).get("code") or {}).get("repos") or []
    return [str(r).strip("/") for r in repos if isinstance(r, str) and r.strip("/")]


def resolve(pid: str, repo: str | None) -> tuple[Path, str]:
    """(the folder to run git in, its path prefix relative to the project root: "" or "folder/")."""
    root = project_root(pid)
    repos = configured(pid)
    if repo:
        repo = repo.strip("/")
        if repo not in repos:
            raise HTTPException(400, f"not a repository of this project: {repo} (add it to code.repos in project.yaml)")
        return safe_join(root, repo), repo + "/"
    if repos and git.open_repo(root) is None:
        return safe_join(root, repos[0]), repos[0] + "/"
    return root, ""


def strip(prefix: str, path: str | None) -> str | None:
    """A project-relative path → relative to the repo folder (paths outside it are refused)."""
    if not path or not prefix:
        return path
    if not path.startswith(prefix):
        raise HTTPException(400, f"{path} is not inside {prefix.rstrip('/')}")
    return path[len(prefix):] or None


def prefix_status(st: dict, prefix: str) -> dict:
    if prefix:
        for d in st.get("dirty") or []:
            d["path"] = prefix + d["path"]
        st["repo"] = prefix.rstrip("/")
    return st


def prefix_diff(d: dict, prefix: str) -> dict:
    if prefix:
        for f in d.get("files") or []:
            f["path"] = prefix + f["path"]
            if f.get("old_path"):
                f["old_path"] = prefix + f["old_path"]
        d["repo"] = prefix.rstrip("/")
    return d


LISTING_TIMEOUT_S = 4.0


def _summary(rel: str, folder: Path, label: str) -> dict:
    try:
        st = git.status(folder)
        return {"repo": rel or None, "label": label, "is_repo": st.get("is_repo", False), "branch": st.get("branch"),
                "head": st.get("head"), "dirty": len(st.get("dirty") or [])}
    except Exception as e:  # noqa: BLE001 — one slow or broken repository must not hide the others
        return {"repo": rel or None, "label": label, "is_repo": True, "branch": None, "head": None, "dirty": None,
                "error": str(getattr(e, "detail", e))[:200]}


def listing(pid: str) -> list[dict]:
    """The project's repositories with their branch and state (the root first when it is one). The repositories are
    queried in parallel; one that does not answer within LISTING_TIMEOUT_S (a huge tree, or files a sync client has
    moved to the cloud) is listed with dirty=None instead of holding up the others."""
    from concurrent.futures import ThreadPoolExecutor, wait
    root = project_root(pid)
    candidates = ([""] if git.open_repo(root) is not None else []) + configured(pid)
    pool = ThreadPoolExecutor(max_workers=max(1, min(8, len(candidates))))
    futures = [pool.submit(_summary, rel, safe_join(root, rel) if rel else root, rel or root.name) for rel in candidates]
    wait(futures, timeout=LISTING_TIMEOUT_S)
    out = []
    for rel, f in zip(candidates, futures):
        out.append(f.result() if f.done() else {"repo": rel or None, "label": rel or root.name, "is_repo": True,
                                                "branch": None, "head": None, "dirty": None, "error": "slow to answer"})
    pool.shutdown(wait=False, cancel_futures=True)
    return out
