"""Agent routes: catalog, panel bindings, runs and their event streams, plus context sharing between the backends:
existing-session discovery, the panel transcript, handoffs, the project brief and the MCP registration snippets."""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
import sys

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import actors, config
from ..projects import project_root, research_dir
from . import brief, catalog, context, discover, handoff, runner, sessions, transcript

log = logging.getLogger("research_deck.agents")
router = APIRouter(tags=["agents"])
brief.watch()       # BRIEF.md follows DAG changes (debounced); see brief.py


@router.get("/api/agents/catalog")
def get_catalog():
    return catalog.catalog()


@router.get("/api/projects/{pid}/sessions")
def get_sessions(pid: str):
    return sessions.load(pid)


class BindingChange(BaseModel):
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    fast: bool | None = None
    permission: str | None = None
    session_id: str | None = None      # "" or null with new_session=true starts a new session
    new_session: bool = False
    title: str | None = None


@router.put("/api/projects/{pid}/sessions/{panel}")
def put_binding(pid: str, panel: str, body: BindingChange):
    if panel not in sessions.ORIGINS:
        raise HTTPException(404, f"unknown panel: {panel}")
    changes = body.model_dump(exclude_none=True)
    if body.new_session:
        changes["session_id"] = None
    changes.pop("new_session", None)
    try:
        return sessions.update_binding(pid, panel, changes)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RunBody(BaseModel):
    panel: str = "project"
    prompt: str
    purpose: str = "chat"
    context: dict | None = None
    ephemeral: bool = False
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    fast: bool | None = None
    permission: str | None = None


def spec_for(pid: str, body: RunBody, *, system: str | None = None, tools: bool = True, prompt: str | None = None) -> runner.RunSpec:
    """Resolve the panel's binding, apply per-run overrides and build the RunSpec. Other packages call this too."""
    if not body.ephemeral:
        try:
            brief.flush(pid)        # the agent may read BRIEF.md; make sure it reflects the DAG as it is now
        except Exception:  # noqa: BLE001 — a stale brief must not block a run
            log.exception("brief refresh before a run failed")
    b = sessions.get_binding(pid, body.panel)
    provider = body.provider or b["provider"]
    same_backend = provider == b["provider"]
    model, effort, fast = catalog.normalize(provider, body.model or (b["model"] if same_backend else None),
                                            body.effort or (b["effort"] if same_backend else None),
                                            body.fast if body.fast is not None else (b["fast"] if same_backend else False))
    session_id = None if body.ephemeral or not same_backend else b["session_id"]
    text = prompt if prompt is not None else body.prompt
    full = text if body.ephemeral else context.compose_prompt(pid, b["panel"], provider, text, body.context)
    return runner.RunSpec(
        project_id=pid, panel=b["panel"], provider=provider, model=model, effort=effort, fast=fast, prompt=full,
        cwd=context.project_cwd(pid), session_id=session_id, ephemeral=body.ephemeral,
        permission=body.permission or b["permission"], purpose=body.purpose, tools=tools,
        system=system if system is not None else context.system_note(pid, body.panel, body.purpose),
        user_text=body.prompt,
    )


@router.post("/api/projects/{pid}/agent/run")
def start_run(pid: str, body: RunBody):
    run = runner.start(spec_for(pid, body))
    transcript.record_run_meta(pid, run)
    s = run.spec
    return {"run_id": run.id, "provider": s.provider, "model": s.model, "effort": s.effort, "fast": s.fast, "session_id": s.session_id}


@router.get("/api/agent/runs")
def list_runs(project: str | None = None):
    runs = [r for r in runner.all_runs() if not project or r.spec.project_id == project]
    return [r.summary() for r in sorted(runs, key=lambda r: -r.started)]


@router.get("/api/agent/runs/{run_id}")
def get_run(run_id: str):
    run = runner.get(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    return {**run.summary(), "text": run.text}


@router.post("/api/agent/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    return {"ok": runner.cancel(run_id)}


@router.get("/api/agent/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    run = runner.get(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    # EventSource reconnects with Last-Event-ID; continue after it instead of replaying the text twice.
    try:
        index = int(request.headers.get("last-event-id", "-1")) + 1
    except ValueError:
        index = 0

    async def gen():
        nonlocal index
        while True:
            if await request.is_disconnected():
                return
            batch = await asyncio.to_thread(run.events_from, index, 15.0)
            if not batch:
                yield ": keep-alive\n\n"
                continue
            for event in batch:
                yield f"id: {index}\nevent: agent\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                index += 1
                if event.get("type") == "done":
                    return

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ context sharing (docs/API.md § Agents)

@router.get("/api/projects/{pid}/sessions/discover")
def discover_sessions(pid: str, provider: str | None = None):
    """Existing Claude Code / Codex sessions whose working folder is the project root, with the panel bound to each."""
    if provider not in (None, "", *sessions.PROVIDERS):
        raise HTTPException(400, f"unknown provider: {provider}")
    found = discover.discover(str(project_root(pid)), provider or None)
    doc = sessions.load(pid)
    bound = {(prov, entry[prov]["session_id"]): panel
             for panel, entry in doc["panels"].items() for prov in sessions.PROVIDERS if entry[prov].get("session_id")}
    for s in found:
        s["bound_to"] = bound.get((s["provider"], s["session_id"]))
    return found


@router.get("/api/projects/{pid}/transcript/{panel}")
def get_transcript(pid: str, panel: str, limit: int = Query(100, ge=1, le=1000),
                   include_imported: bool = Query(False, alias="import")):
    """The conversation's dashboard transcript with handoff lines; import=1 adds the tail of the bound session's own log."""
    if panel not in sessions.ORIGINS:
        raise HTTPException(404, f"unknown panel: {panel}")
    return transcript.entries(pid, panel, limit=limit, include_imported=include_imported)


class HandoffBody(BaseModel):
    panel: str
    to: str
    smart: bool = False


@router.post("/api/projects/{pid}/handoff")
def post_handoff(pid: str, body: HandoffBody):
    """Switch the conversation's backend, writing a handoff note that the new backend receives with its next prompt."""
    try:
        return handoff.handoff(pid, body.panel, body.to, smart=body.smart)
    except ValueError as e:
        raise HTTPException(400, str(e))


class NoteBody(BaseModel):
    panel: str = "project"
    text: str
    to: str | None = None       # default: the other backend than the calling agent's


@router.post("/api/projects/{pid}/handoff/note")
def post_handoff_note(pid: str, body: NoteBody, request: Request):
    """A note one agent leaves for the other backend of a panel (MCP rd_handoff_note)."""
    try:
        return handoff.leave_note(pid, body.panel, body.text, actor=actors.actor_of(request), to=body.to)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/projects/{pid}/handoffs")
def get_handoffs(pid: str, limit: int = Query(20, ge=1, le=200)):
    """Recent handoff notes and the ones still waiting to be delivered (Settings)."""
    return {"recent": handoff.recent_handoffs(pid, limit), "pending": handoff.pending_notes(pid)}


@router.get("/api/projects/{pid}/brief")
def get_brief(pid: str):
    """Regenerate .research/context/BRIEF.md (rewritten only when its content changed) and return it."""
    result = brief.generate(pid)
    return {"markdown": result["markdown"], "generated_at": result["generated_at"], "path": ".research/context/BRIEF.md"}


def mcp_registration(pid: str) -> dict:
    """How the researcher can add the research-deck MCP server to their own Claude Code / Codex (Settings shows it)."""
    root = project_root(pid)            # 404 for an unknown project
    python = sys.executable
    args = ["-m", "research_deck.mcp_server", "--project", pid]
    env = {"PYTHONPATH": str(config.APP_ROOT / "server"), "RD_URL": f"http://{config.HOST}:{config.PORT}",
           "RD_LOCAL_DIR": str(config.LOCAL_DIR)}
    claude_env = {**env, "RD_ACTOR": "agent:claude:terminal"}
    codex_env = {**env, "RD_ACTOR": "agent:codex:terminal"}
    q = shlex.quote

    def flags(flag: str, values: dict) -> list[str]:
        return [part for k, v in values.items() for part in (flag, q(f"{k}={v}"))]

    toml = "\n".join([
        "[mcp_servers.research-deck]",
        f"command = {json.dumps(python)}",
        f"args = {json.dumps(args)}",
        "env = { " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in codex_env.items()) + " }",
    ])
    tail = ["--", q(python), *map(q, args)]
    return {
        "claude": {"mcpServers": {"research-deck": {"command": python, "args": args, "env": claude_env}}},
        "codex": toml,
        "commands": {
            "claude": " ".join(["claude", "mcp", "add", "research-deck", "-s", "user", *flags("-e", claude_env), *tail]),
            "codex": " ".join(["codex", "mcp", "add", "research-deck", *flags("--env", codex_env), *tail]),
        },
        "remove": {"claude": "claude mcp remove research-deck -s user", "codex": "codex mcp remove research-deck"},
        "env": env,
        "paths": {"app_root": str(config.APP_ROOT), "local_dir": str(config.LOCAL_DIR), "project_root": str(root),
                  "research_dir": str(research_dir(pid)), "docs": str(config.APP_ROOT / "docs")},
    }


@router.get("/api/mcp/config")
def get_mcp_config(project: str = Query(...)):
    """Registration snippets for Settings. Nothing is registered here; that changes the user's CLI config."""
    return mcp_registration(project)
