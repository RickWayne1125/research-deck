"""Coding routes (docs/API.md § Coding): git status / log / diff / show, the architecture graph, review and explain.

Everything here is read-only on the project: git is only queried, and the agent runs are started read-only.
A project that is not a git repository gets is_repo=false and empty lists, never an error page.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from . import architecture as arch
from . import assist, git, repos

router = APIRouter(prefix="/api/projects/{pid}", tags=["coding"])


def _node_index(pid: str) -> dict[str, list[str]]:
    """{sha prefix: [DAG node ids]} from the DAG engine, or {} when it is missing or fails."""
    try:
        from ..dag import service as dag
        mapping = dag.nodes_by_commit(pid) or {}
        return {str(k).lower(): [str(n) for n in v] for k, v in mapping.items() if k and len(str(k)) >= 4}
    except Exception:  # noqa: BLE001 — commits are still useful without their DAG links
        return {}


@router.get("/git/repos")
def git_repos(pid: str):
    """The repositories of a multi-repo workspace (code.repos), or just the project's own."""
    return repos.listing(pid)


@router.get("/git/status")
def git_status(pid: str, repo: str | None = Query(None)):
    folder, prefix = repos.resolve(pid, repo)
    return repos.prefix_status(git.status(folder), prefix)


@router.get("/git/log")
def git_log(pid: str, limit: int = Query(100, ge=1, le=500), path: str | None = Query(None), repo: str | None = Query(None)):
    folder, prefix = repos.resolve(pid, repo)
    commits = git.log(folder, limit, repos.strip(prefix, path or None))
    index = _node_index(pid) if commits else {}
    for c in commits:
        ids: list[str] = []
        for prefix, nodes in index.items():
            if c["sha"].startswith(prefix):
                ids.extend(n for n in nodes if n not in ids)
        c["node_ids"] = ids
    return commits


@router.get("/git/diff")
def git_diff(pid: str, frm: str | None = Query(None, alias="from"), to: str | None = Query(None),
             path: str | None = Query(None), repo: str | None = Query(None)):
    folder, prefix = repos.resolve(pid, repo)
    return repos.prefix_diff(git.diff(folder, frm or None, to or None, repos.strip(prefix, path or None)), prefix)


@router.get("/git/show")
def git_show(pid: str, path: str = Query(...), rev: str = Query("HEAD"), repo: str | None = Query(None)):
    folder, prefix = repos.resolve(pid, repo)
    return git.show(folder, rev, repos.strip(prefix, path))


@router.get("/architecture")
def get_architecture(pid: str):
    return arch.architecture(pid)


class ReviewFocus(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None


class ReviewBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    frm: str | None = Field(None, alias="from")
    to: str | None = None
    paths: list[str] | None = None
    focus: ReviewFocus | None = None        # "review selection": these lines, in the new version
    lang: str | None = None                 # the UI language the findings are written in (zh | en)
    repo: str | None = None                 # a multi-repo workspace: which repository (code.repos)


@router.post("/coding/review")
def review(pid: str, body: ReviewBody):
    return assist.start_review(pid, body.frm or None, body.to or None, body.paths or None,
                               body.focus.model_dump() if body.focus else None, body.lang, repo=body.repo)


class ExplainBody(BaseModel):
    path: str
    start_line: int = Field(1, ge=1)
    end_line: int | None = Field(None, ge=1)
    rev: str | None = None                  # explain the file as of this revision (e.g. deleted lines of a diff)
    lang: str | None = None
    repo: str | None = None


@router.post("/coding/explain")
def explain(pid: str, body: ExplainBody):
    return assist.start_explain(pid, body.path, body.start_line, body.end_line, body.rev or None, body.lang, repo=body.repo)
