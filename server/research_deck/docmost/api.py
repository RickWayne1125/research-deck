"""Docmost routes (docs/API.md § Docmost): this computer's site and sign-in, a project's bound page and its notes.

Reading the state is open to the dashboard and agents; signing in, binding, syncing and resolving are the researcher's.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .. import actors, projects
from . import client as dm
from . import session, sync

router = APIRouter(tags=["docmost"])


def _human(request: Request) -> None:
    if not actors.is_human(actors.actor_of(request)):
        raise HTTPException(403, "only the researcher signs in to Docmost or changes what syncs there")


def _call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except dm.SignInNeeded as e:
        raise HTTPException(401, {"message": str(e), "sign_in": True}) from e
    except dm.DocmostError as e:
        raise HTTPException(404 if e.status == 404 else 502, str(e)) from e


class SiteBody(BaseModel):
    url: str | None = None


class BindBody(BaseModel):
    link: str


class ResolveBody(BaseModel):
    path: str
    action: str


@router.get("/api/settings/docmost")
def get_site():
    return session.status()


@router.patch("/api/settings/docmost")
def patch_site(body: SiteBody, request: Request):
    _human(request)
    _call(dm.set_site, body.url)
    return session.status()


@router.post("/api/settings/docmost/login")
def login(request: Request):
    """Open the sign-in window on this computer; poll GET /api/settings/docmost for its outcome."""
    _human(request)
    return _call(session.start_login)


@router.post("/api/settings/docmost/logout")
def logout(request: Request):
    _human(request)
    return session.sign_out()


@router.post("/api/settings/docmost/browser")
def install_browser(request: Request):
    _human(request)
    return _call(session.install_browser)


@router.get("/api/projects/{pid}/docmost")
def get_project(pid: str):
    projects.project_root(pid)
    return sync.status(pid)


@router.put("/api/projects/{pid}/docmost")
def bind(pid: str, body: BindBody, request: Request):
    _human(request)
    _call(sync.bind, pid, body.link)
    return _call(sync.sync, pid)


@router.delete("/api/projects/{pid}/docmost")
def unbind(pid: str, request: Request):
    _human(request)
    return sync.unbind(pid)


@router.post("/api/projects/{pid}/docmost/sync")
def sync_now(pid: str, request: Request):
    _human(request)
    return _call(sync.sync, pid)


@router.get("/api/projects/{pid}/docmost/conflict")
def conflict(pid: str, path: str = Query(...)):
    return _call(sync.conflict_view, pid, path)


@router.post("/api/projects/{pid}/docmost/resolve")
def resolve(pid: str, body: ResolveBody, request: Request):
    _human(request)
    return _call(sync.resolve, pid, body.path, body.action)
