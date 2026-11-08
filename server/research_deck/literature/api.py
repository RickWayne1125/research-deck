"""Literature routes (docs/API.md § Literature): this computer's Zotero connection, and a project's backend.

Everything here that reaches Zotero or changes a setting is the researcher's: agents get 403 (they read the project's
backend only).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import actors, projects
from . import backend, zotero

router = APIRouter(tags=["literature"])


def _human(request: Request) -> None:
    if not actors.is_human(actors.actor_of(request)):
        raise HTTPException(403, "only the researcher connects Zotero or changes where literature is kept")


def _zotero_call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except zotero.ZoteroError as e:
        raise HTTPException(502 if e.status is None or e.status >= 500 else 409, str(e)) from e


@router.get("/api/settings/zotero")
def get_zotero():
    return zotero.status()


@router.patch("/api/settings/zotero")
def patch_zotero(body: dict, request: Request):
    _human(request)
    try:
        return zotero.update(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/settings/zotero/connect")
def connect_zotero(request: Request):
    """The app: start its authorization dialog (poll GET /api/settings/zotero); zotero.org: check the key."""
    _human(request)
    return zotero.connect()


@router.post("/api/settings/zotero/check")
def check_zotero(request: Request):
    _human(request)
    zotero.check_now()
    return zotero.status()


@router.delete("/api/settings/zotero/key")
def forget_zotero_key(request: Request):
    _human(request)
    zotero.forget_local_key()
    return zotero.status()


@router.get("/api/zotero/collections")
def zotero_collections(request: Request):
    _human(request)
    return {"collections": _zotero_call(lambda: zotero.client().collections())}


@router.get("/api/projects/{pid}/literature")
def get_literature(pid: str):
    projects.project_root(pid)
    return backend.view(pid)


class LiteratureBody(BaseModel):
    backend: str
    collection: str | None = None          # an existing collection's key
    create: bool = False                   # or a new collection named after the project


@router.put("/api/projects/{pid}/literature")
def put_literature(pid: str, body: LiteratureBody, request: Request):
    _human(request)
    if body.backend not in backend.BACKENDS:
        raise HTTPException(400, "backend is files or zotero")
    if body.backend == "files":
        backend.set_config(pid, backend="files")
        return backend.view(pid)
    if body.collection:
        cols = {c["key"]: c["name"] for c in _zotero_call(lambda: zotero.client().collections())}
        if body.collection not in cols:
            raise HTTPException(404, "no such collection in the Zotero library")
        backend.set_config(pid, backend="zotero", collection=body.collection, collection_name=cols[body.collection])
    else:
        backend.set_config(pid, backend="zotero")
        if body.create:
            backend.set_config(pid, collection=None, collection_name=None)
            _zotero_call(lambda: backend.ensure_collection(pid, zotero.client()))
    return backend.view(pid)


@router.post("/api/projects/{pid}/literature/export")
def export_literature(pid: str, request: Request):
    _human(request)
    return _zotero_call(backend.export_bib, pid)
