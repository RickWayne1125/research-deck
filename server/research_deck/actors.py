"""Who is calling: the researcher in the browser, a Codex/Claude agent through the MCP server, or the system.

- The browser calls GET /api/session once; it sets an HttpOnly, SameSite=Strict cookie holding a token that lives only
  in this server process. Requests carrying it act as `human:<login>`.
- The MCP server (research_deck.mcp_server) sends `X-RD-Actor: agent:<claude|codex>:<session>` and
  `X-RD-Agent-Token` = the contents of .local/agent.token (created 0600 on first use).
- Anything else (curl, a page from elsewhere, an agent calling the API directly) is `agent:unknown`: it gets agent
  permissions, so human-only operations (lock, unlock, approve, gate pass, ...) need the browser.
This is tamper-evident, not tamper-proof (docs/DAG.md §7): every operation is logged with its actor.
"""
from __future__ import annotations

import getpass
import os
import secrets

from fastapi import APIRouter, HTTPException, Request, Response

from . import config

COOKIE = "rd_human"
_HUMAN_TOKEN = secrets.token_urlsafe(32)
router = APIRouter(tags=["session"])


def human_name() -> str:
    return os.environ.get("RD_HUMAN") or getpass.getuser() or "researcher"


def agent_token() -> str:
    path = config.LOCAL_DIR / "agent.token"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
        return token


def actor_of(request: Request) -> str:
    claimed = request.headers.get("x-rd-actor", "")
    if claimed.startswith("agent:") and secrets.compare_digest(request.headers.get("x-rd-agent-token", ""), agent_token()):
        return claimed[:80]
    if secrets.compare_digest(request.cookies.get(COOKIE, ""), _HUMAN_TOKEN):
        return f"human:{human_name()}"
    return "agent:unknown"


def is_human(actor: str) -> bool:
    return actor.startswith("human:")


@router.get("/api/session")
def session(request: Request, response: Response):
    # Browsers mark the page's own fetch as same-origin; a script or tool asking for the cookie gets nothing.
    # (Tamper-evident, not tamper-proof: a local process can forge headers. Agents have no tool that can.)
    if request.headers.get("sec-fetch-site") not in ("same-origin", "none"):
        raise HTTPException(403, "the session cookie is only issued to the dashboard page")
    response.set_cookie(COOKIE, _HUMAN_TOKEN, httponly=True, samesite="strict", secure=False, path="/")
    return {"actor": f"human:{human_name()}", "name": human_name()}
