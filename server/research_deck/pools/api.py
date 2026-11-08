"""Resource pool routes (docs/API.md § Resource pools).

GET    /api/pools?project=                 every pool (definition + platform view), the project's selection, the
                                           platform names no pool answers to, pool files that do not validate, names
                                           two pool files both claim, and where the example adapters are
GET    /api/pools/{id}?project=            one pool, with its file as written
PUT    /api/pools/{id}?project=            create or replace (the researcher only; 409 when its id or one of its
                                           names is already another pool's)
DELETE /api/pools/{id}                     move the file to pools/.trash/ (the researcher only; credentials stay)
POST   /api/pools/{id}/refresh?project=    read now (the researcher only)
POST   /api/pools/test                     read an unsaved definition once (the researcher only)
POST   /api/pools/parse                    a definition from YAML text, for importing a pool file (the researcher only)
GET    /api/pools/coder/status?host=       the Coder CLI's sign-in, in the folder ssh to that host reads (coder.py)
POST   /api/pools/coder/login              {url, token, host?}: sign the Coder CLI in there (the researcher only; the
                                           token goes to the CLI, which keeps it; nothing is stored here)
PUT    /api/projects/{pid}/pools           which pools this project uses: {"pools": [ids] | null = all}
GET    /api/resources?project=             the Experiments › Resources snapshot (experiments/api.py serves it)

Agents read pools (and MCP rd_pools); every change, test and read-now is the researcher's, since a pool's source runs
a command or calls an address with the researcher's credentials.
"""
from __future__ import annotations

import sys
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import actors, config
from . import coder, service, store

router = APIRouter(tags=["pools"])


def _human(request: Request) -> None:
    if not actors.is_human(actors.actor_of(request)):
        raise HTTPException(403, "only the researcher changes, tests or refreshes resource pools; agents may only look at them")


@router.get("/api/pools")
def list_pools(project: str | None = None):
    errors: list[dict] = []
    clashes: list[dict] = []
    pools = store.load_all(errors, clashes)
    service.refresh_due(pools)
    sel = service.selection(project) if project else None
    usage = service.agent_usage_today(project) if project else {}
    return {"pools": [service.view(p, project, sel=sel, usage=usage) for p in pools], "selection": sel,
            "unmatched": service.unmatched(project, pools) if project else [], "broken": errors, "clashes": clashes,
            "dir": str(store.pools_dir()),
            # for the wizard's presets: the example adapters (scripts/pools) and a Python that can run them
            "adapters": str(config.APP_ROOT / "scripts" / "pools"), "python": sys.executable}


@router.get("/api/pools/{pid}")
def get_pool(pid: str, project: str | None = None):
    pool = store.get(pid)
    return {**service.view(pool, project), "yaml": store.text(pid)}


@router.put("/api/pools/{pid}")
def put_pool(pid: str, body: dict[str, Any], request: Request, project: str | None = None):
    _human(request)
    if str(body.get("id") or "") != pid:
        raise HTTPException(400, "the id in the body must match the address")
    pool = store.save(body)
    service.refresh_due([pool])
    return service.view(pool, project)


@router.delete("/api/pools/{pid}")
def delete_pool(pid: str, request: Request):
    _human(request)
    return {"trashed": str(store.remove(pid))}


@router.post("/api/pools/{pid}/refresh")
def refresh_pool(pid: str, request: Request, project: str | None = None):
    _human(request)
    pool = store.get(pid)
    service.refresh(pool)
    return service.view(pool, project)


@router.post("/api/pools/test")
def test_pool(body: dict[str, Any], request: Request):
    _human(request)
    try:
        return service.test(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/pools/coder/status")
def coder_status(request: Request, host: str | None = None):
    _human(request)
    if host and not coder.host_in([host]):
        raise HTTPException(400, "not a Coder workspace host (<agent>.<workspace>.<owner>.coder or coder.<workspace>)")
    return coder.status(host)


@router.post("/api/pools/coder/login")
def coder_login(body: dict[str, Any], request: Request):
    _human(request)
    host = body.get("host") or None
    if host and not coder.host_in([str(host)]):
        raise HTTPException(400, "not a Coder workspace host (<agent>.<workspace>.<owner>.coder or coder.<workspace>)")
    try:
        return coder.login(str(body.get("url") or ""), str(body.get("token") or ""), host)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/pools/parse")
def parse_pool(body: dict[str, Any], request: Request):
    _human(request)
    try:
        pool = store.parse(str(body.get("text") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"def": pool, "exists": store.exists(pool["id"])}


@router.put("/api/projects/{pid}/pools")
def set_project_pools(pid: str, body: dict[str, Any], request: Request):
    _human(request)
    ids = body.get("pools")
    if ids is not None and (not isinstance(ids, list) or len(ids) > 500 or not all(isinstance(x, str) for x in ids)):
        raise HTTPException(400, "pools: a list of pool ids, or null for all of them")
    return {"selection": service.set_selection(pid, ids)}
