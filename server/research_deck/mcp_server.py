"""The research-deck MCP server: Codex and Claude Code read and change the research DAG through the dashboard's API.

    python -m research_deck.mcp_server --project <pid>        (stdio; the dashboard must be running)

Every dashboard-driven run gets it (agents/runner.py: Claude --mcp-config, Codex -c mcp_servers.research_deck.*);
Settings shows the commands for registering it with the researcher's own CLIs — never done silently.

Environment:
  RD_URL        the dashboard, default http://127.0.0.1:8765
  RD_LOCAL_DIR  research-deck/.local (holds agent.token)
  RD_ACTOR      agent:<claude|codex>:<session> — who the DAG log records as the author of each change
Every request sends X-RD-Actor and X-RD-Agent-Token (actors.py), so the server grants agent permissions under that
name. The tools proxy the HTTP routes of docs/DAG.md §7. Lock, unlock, approve, gate pass, select-run and
exclude-run are deliberately absent: those are the researcher's decisions. Without --project the project is the
registered one whose folder contains the current directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import anyio
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

DEFAULT_URL = "http://127.0.0.1:8765"
TIMEOUT_S = 30.0
Lens = Literal["tried", "confirmed", "revise", "rerun"]

INSTRUCTIONS = """\
Research Deck keeps this research project as a DAG (docs/DAG.md): action nodes (experiments, scripted figures) whose
runs are cached by the fingerprints of what they read, and belief nodes (findings, gaps, solutions, decisions, designs,
modules, claims, sections) whose edges record what they last saw. Status (proposed, active, confirmed, locked, refuted,
abandoned, superseded) is what was decided; freshness (fresh, review, orphaned, pending, unbuilt, stale, broken) is
whether that still holds, derived on every evaluation.

Four lenses answer the researcher's questions:
- tried: every attempt, dead ones included, with verdicts and reasons (what has been tried already);
- confirmed: confirmed or locked nodes that are fresh (what we can rely on);
- revise: live nodes in review, orphaned or broken (what to fix, attest or roll back);
- rerun: experiment cells that are stale or not yet run, in waves (what to rerun).

The paper outline is the project's main line (rd_outline): its sections in paper order, each a numbered chain of
items (claims) that argue what the section makes the reader accept; the phases group the sections; tasks (literature,
code, figure, experiment) hang on items, and what a task produces is the item's evidence. You may add items
(rd_outline_ops add_item; they come in proposed, dashed, until the researcher accepts them) and suggest tasks
(rd_suggest_task); rewording, moving, removing, forking and choosing a direction become a proposal. In the paper, put
the paragraph that argues an item under a line `% rd:describes <item id>` inside the section's `% rd:sec <section id>`
region.

Start with rd_brief or rd_lenses, then rd_graph / rd_node / rd_explain. Preview every change with rd_impact before
rd_apply. You create nodes as proposed and may edit proposed or active nodes directly; changes to confirmed or locked
nodes (and any batch that touches a lock) become a proposal for the researcher, and so do status changes beyond your
own proposed nodes. Locking, approving proposals and passing gates are the researcher's; ask instead of working
around them. Use full node ids (e.g. design.sched) and the exact addresses the tools return.

The map grows one step at a time (Idea → Motivation & insight → System design → Evaluation; the project's stage says
which step it is in). Draft nodes of the current step only, resting on confirmed nodes of the steps before; draft
the next step once the researcher has passed the current one's gate. Several directions within a step are fine, but
never extend a refuted, abandoned or superseded node: a failed branch ends there. A refusal with reason
stage_locked, unconfirmed_parent or dead_parent is one of these rules; say so to the researcher instead of
working around it.
"""


def _compact(data: Any) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _title(t: Any) -> str:
    if isinstance(t, dict):
        return t.get("en") or t.get("zh") or ""
    return str(t or "")


def compact_graph(g: dict) -> dict:
    """The graph without facet bodies: enough to navigate (rd_node has the rest)."""
    ev = g.get("eval") or {}
    nodes = []
    for n in g.get("nodes") or []:
        e = ev.get(n.get("id")) or {}
        item: dict[str, Any] = {"id": n.get("id"), "kind": n.get("kind"), "stage": n.get("stage"),
                                "title": _title(n.get("title")), "status": n.get("status"), "level": e.get("level")}
        for key in ("flags", "shaky"):
            if e.get(key):
                item[key] = e[key]
        if n.get("alt_group"):
            item["alt_group"] = n["alt_group"]
        if n.get("superseded_by"):
            item["superseded_by"] = n["superseded_by"]
        edges = [f"{x.get('type')}:{x.get('to')}" for x in n.get("edges") or [] if x.get("type") != "cites"]
        if edges:
            item["edges"] = edges
        if e.get("cells"):
            item["cells"] = {c: (v or {}).get("level") for c, v in e["cells"].items()}
        nodes.append(item)
    return {"digest": g.get("digest"), "lenses": g.get("lenses"), "nodes": nodes}


def compact_experiments(items: Any) -> Any:
    if not isinstance(items, list):
        return items
    keep = ("id", "node_id", "title", "status", "freshness", "stale_reasons", "metrics", "started_at", "finished_at")
    out = []
    for x in items:
        if not isinstance(x, dict):
            continue
        item = {k: x[k] for k in keep if x.get(k) not in (None, [], {})}
        target = x.get("target") or {}
        if target:
            item["target"] = "/".join(str(target[k]) for k in ("platform", "node") if target.get(k))
        out.append(item)
    return out


HINTS = {
    403: "This operation is the researcher's. Open a proposal with rd_propose (or rd_apply, which turns an unsafe "
         "batch into a proposal) and say why.",
    409: "The graph changed since you read it. Re-read the node (rd_node) and retry with the new base_vid.",
    404: "Not found. Check the id; if every DAG tool answers 404 the project may have no research DAG yet.",
}


class RdApi:
    """The dashboard's HTTP API as this agent: one place for the base URL, the identity headers and errors."""

    def __init__(self, project: str | None, http: httpx.Client, *, actor: str | None = None, local_dir: str | Path | None = None):
        self._project = project
        self.http = http
        self.actor = actor or os.environ.get("RD_ACTOR") or "agent:unknown:mcp"
        self._local_dir = local_dir

    def _token(self) -> str:
        if self._local_dir:
            folder = Path(self._local_dir)
        elif os.environ.get("RD_LOCAL_DIR"):
            folder = Path(os.environ["RD_LOCAL_DIR"])
        else:
            from . import config      # the dashboard's own default (research-deck/.local)
            folder = config.LOCAL_DIR
        try:
            return (folder / "agent.token").read_text(encoding="utf-8").strip()
        except OSError:
            return ""           # the server then treats us as agent:unknown (still agent permissions)

    def headers(self) -> dict[str, str]:
        return {"X-RD-Actor": self.actor, "X-RD-Agent-Token": self._token(), "X-RD-Request": "1"}

    @property
    def project(self) -> str:
        if not self._project:
            self._project = self._project_from_cwd()
        return self._project

    def _project_from_cwd(self) -> str:
        cwd = Path.cwd().resolve()
        projects = self.request("GET", "/api/projects")
        best = None
        for p in projects if isinstance(projects, list) else []:
            root = Path(p.get("root", "")).resolve()
            if (cwd == root or root in cwd.parents) and (best is None or len(str(root)) > len(best[1])):
                best = (p["id"], str(root))
        if not best:
            raise ToolError(f"No Research Deck project contains {cwd}; start the server with --project <id>.")
        return best[0]

    def request(self, method: str, path: str, *, json_body: Any = None, params: dict | None = None) -> Any:
        url = path if path.startswith("/api/") else f"/api/projects/{quote(self.project, safe='')}{path}"
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            r = self.http.request(method, url, json=json_body, params=params or None, headers=self.headers())
        except httpx.HTTPError as e:
            raise ToolError(f"Research Deck is not reachable ({e}). Is the dashboard running?") from e
        try:
            data = r.json() if r.content else None
        except ValueError:
            data = r.text
        if r.status_code >= 400:
            detail = data.get("detail", data) if isinstance(data, dict) else data
            hint = HINTS.get(r.status_code)
            raise ToolError(_compact({"status": r.status_code, "error": detail, **({"hint": hint} if hint else {})}))
        return data


def build_server(project: str | None = None, http: httpx.Client | None = None, *, actor: str | None = None,
                 local_dir: str | Path | None = None, base_url: str | None = None) -> FastMCP:
    """The MCP server over an HTTP client (tests pass a TestClient, which is an httpx.Client)."""
    if http is None:
        http = httpx.Client(base_url=base_url or os.environ.get("RD_URL") or DEFAULT_URL, timeout=TIMEOUT_S)
    api = RdApi(project, http, actor=actor, local_dir=local_dir)
    mcp = FastMCP("research-deck", instructions=INSTRUCTIONS)

    async def call(method: str, path: str, *, body: Any = None, params: dict | None = None) -> Any:
        # httpx is blocking here (a TestClient in tests); keep the stdio loop responsive meanwhile.
        return await anyio.to_thread.run_sync(lambda: api.request(method, path, json_body=body, params=params))

    @mcp.tool(structured_output=False, description=(
        "The project brief (Markdown): stage, lens counts, what needs revising or rerunning and why, confirmed facts, "
        "live attempts with their verdicts, open proposals, gates, the conversation's agent and where files live. "
        "Read it first for the big picture; it is also at .research/context/BRIEF.md."))
    async def rd_brief() -> str:
        data = await call("GET", "/brief")
        return data.get("markdown", "") if isinstance(data, dict) else _compact(data)

    @mcp.tool(structured_output=False, description=(
        "The paper outline as numbered lines: each section ([phase], id, what it makes the reader accept) and its "
        "items as `num [state] text (id; tasks)`, parallel items marked ‖, forks with their directions (chosen, given "
        "up and why). States: holds, doing, todo, blocked, locked (waits for its phase), needs_tasks, choose (a fork "
        "waits for a direction), pending (a summary item), proposed, abandoned. Ids are what rd_outline_ops takes."))
    async def rd_outline() -> str:
        from .outline.model import as_text
        data = await call("GET", "/outline", params={"lang": "en"})
        if not isinstance(data, dict) or not data.get("has_outline"):
            return "No outline yet: the researcher writes it on the outline page (or asks you to draft one as text)."
        c = data.get("counts") or {}
        head = (f"phase {data.get('project_phase')} · tasks {c.get('done', 0)} done, {c.get('doing', 0)} doing, "
                f"{c.get('todo', 0)} todo, {c.get('blocked', 0)} blocked")
        return "\n".join([head, *as_text(data, "en", limit=400)])

    @mcp.tool(structured_output=False, description=(
        "Change the outline with outline ops (server/research_deck/outline/ops.py), applied as one batch: "
        "{op:add_item, parent:<section or item id>, text, at?:{after:<id>}|{parallel:<id>}|{first:true}, derived?}, "
        "{op:edit_item, item, text?|derived?|condition?|summary_of?}, {op:move_item, item, how:up|down|indent|outdent|"
        "join|split}, {op:remove_item, item}, {op:set_note, parent, step, text}, {op:fork, item, question?, directions:"
        "[…]}, {op:add_direction, item, text}, {op:choose_direction|abandon_direction, item, direction, reason?}, "
        "{op:link, item, to:<node id>, type:basis|evidence|cites}. Items you add come in proposed; anything else you "
        "change becomes ONE proposal for the researcher (the answer says which)."))
    async def rd_outline_ops(ops: list[dict]) -> str:
        return _compact(await call("POST", "/outline/ops", body={"ops": ops, "lang": "en"}))

    @mcp.tool(structured_output=False, description=(
        "Suggest a task for outline items: type lit (literature) | code | fig (figure) | exp (experiment), a short "
        "title, the item ids it serves, and optionally links {node: <map node it produces or uses>}. It waits as a "
        "suggestion until the researcher takes it."))
    async def rd_suggest_task(type: Literal["lit", "code", "fig", "exp"], title: str, items: list[str], links: dict | None = None) -> str:
        return _compact(await call("POST", "/tasks", body={"type": type, "title": title, "items": items, "links": links or {}}))

    @mcp.tool(structured_output=False, description=(
        "Counts and item ids of the four lenses. tried: every attempt including dead ones (what was tried, with "
        "verdicts); confirmed: confirmed or locked and fresh (what we rely on); revise: live nodes in review, "
        "orphaned or broken (fix, attest or roll back); rerun: stale or unbuilt experiment cells (rerun in waves)."))
    async def rd_lenses() -> str:
        return _compact(await call("GET", "/dag/lenses"))

    @mcp.tool(structured_output=False, description=(
        "The research DAG without facet bodies: each node's id, kind, stage, title, status, freshness level, flags, "
        "edges (type:address) and per-cell levels for experiments. Optionally filter by lens (tried | confirmed | "
        "revise | rerun). Use rd_node for a node's facets, history and runs."))
    async def rd_graph(lens: Lens | None = None) -> str:
        data = await call("GET", "/dag/graph", params={"lens": lens})
        return _compact(compact_graph(data) if isinstance(data, dict) else data)

    @mcp.tool(structured_output=False, description=(
        "One node in full: facets, edges with what they last saw, its evaluation (level, reasons, flags, cells), "
        "recent history and the runs of each cell. Node ids look like design.sched or exp.e2e-sharegpt."))
    async def rd_node(id: str) -> str:
        return _compact(await call("GET", f"/dag/nodes/{quote(id, safe='')}"))

    @mcp.tool(structured_output=False, description=(
        "Why a node (or one experiment cell, e.g. cell='rate=8,system=ours') is not fresh: root-cause chains with "
        "the from -> to values of what changed (code, config, data, env, upstream facets)."))
    async def rd_explain(id: str, cell: str | None = None) -> str:
        return _compact(await call("GET", f"/dag/nodes/{quote(id, safe='')}/explain", params={"cell": cell}))

    @mcp.tool(structured_output=False, description=(
        "Preview what a change would do before applying it: which cells must rerun (GPU-h), which are reused and "
        "why, which beliefs go to review, orphaned or broken, lock hits and gate flips. ops are DAG ops "
        "(docs/DAG.md §2.7, e.g. {\"op\":\"edit\",\"node\":\"design.sched\",\"base_vid\":\"v-…\",\"set\":{…}}). "
        "code: {\"diff\": \"HEAD~1..HEAD\"} | {\"staged\": true} | {\"worktree\": true} | {\"branch\": \"…\"}, or a "
        "rev range string. touch_code: globs of code you are about to write (a prediction)."))
    async def rd_impact(ops: list[dict] | None = None, code: dict | str | None = None, touch_code: list[str] | None = None) -> str:
        body: dict[str, Any] = {"ops": ops or [], "explain": True}
        if code:
            body["code"] = {"diff": code} if isinstance(code, str) else code
        if touch_code:
            body["touch_code"] = touch_code
        return _compact(await call("POST", "/dag/impact", body=body))

    @mcp.tool(structured_output=False, description=(
        "Apply DAG ops atomically. A batch applies directly only when every op is yours to make (create as proposed; "
        "edit, link, unlink, attest or roll back proposed/active nodes; move your proposed node to active; refute or "
        "abandon your own proposed node), the preview hits no lock and no confirmed or locked node changes status. "
        "Otherwise the whole batch becomes ONE proposal for the researcher (the answer says which). Give a rationale."))
    async def rd_apply(ops: list[dict], rationale: str | None = None) -> str:
        return _compact(await call("POST", "/dag/ops", body={"ops": ops, "rationale": rationale}))

    @mcp.tool(structured_output=False, description=(
        "Open a proposal for the researcher: a titled batch of ops with your rationale; it carries a fresh impact "
        "preview and waits in the DAG inbox. Use it for edits to confirmed or locked nodes, status verdicts "
        "(confirm, refute, abandon, supersede, revive), unlocks (requires: [\"unlock:<id>\"]) and snapshot restores."))
    async def rd_propose(title: str, rationale: str, ops: list[dict]) -> str:
        return _compact(await call("POST", "/dag/proposals", body={"title": title, "rationale": rationale, "ops": ops}))

    @mcp.tool(structured_output=False, description=(
        "Attest soft edges of a node after checking that the upstream change does not affect it: copies the current "
        "fingerprint into the edge's 'seen' and clears 'review'. edges are 'type:address' strings, e.g. "
        "'implements:node:design.sched#preemption'. On confirmed or locked nodes this becomes a proposal."))
    async def rd_attest(id: str, edges: list[str]) -> str:
        return _compact(await call("POST", "/dag/ops", body={"ops": [{"op": "attest", "node": id, "edges": edges}],
                                                              "rationale": "attested by agent after review"}))

    @mcp.tool(structured_output=False, description=(
        "Plan reruns: the stale or unbuilt cells of live experiments in dependency waves, with estimated GPU-h, "
        "platform and blocked reasons (e.g. 'implement first'). targets: node ids to limit the plan. Planning "
        "queues nothing; the researcher queues runs from the dashboard."))
    async def rd_plan_runs(targets: list[str] | None = None) -> str:
        return _compact(await call("POST", "/dag/runs/plan", body={"targets": targets} if targets else {}))

    @mcp.tool(structured_output=False, description=(
        "Queue reruns of DAG action cells (from rd_plan_runs) as experiment records. Allowed for agents only on the "
        "platforms and within the daily GPU-hour budget of the project's policy (agent_auto_run), and never for cells "
        "blocked by 'implement first'; otherwise the answer says why and the researcher has to queue them. Pass cells "
        "as [{node, cell}] and the platform id."))
    async def rd_queue_runs(cells: list[dict], platform: str) -> str:
        return _compact(await call("POST", "/dag/runs/queue", body={"cells": cells, "platform": platform}))

    @mcp.tool(structured_output=False, description=(
        "The project's experiment records with their DAG freshness (fresh, reusable, stale, unknown), status, "
        "target platform and metrics."))
    async def rd_experiments() -> str:
        return _compact(compact_experiments(await call("GET", "/experiments")))

    @mcp.tool(structured_output=False, description=(
        "Leave a note for the OTHER backend of the project conversation (Claude Code <-> Codex): it is prepended once "
        "to that agent's next prompt. Use it for what the other agent must know: work in progress, a decision, a caveat."))
    async def rd_handoff_note(text: str, panel: str = "project") -> str:
        return _compact(await call("POST", "/handoff/note", body={"panel": panel, "text": text}))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m research_deck.mcp_server", description="Research Deck MCP server (stdio)")
    parser.add_argument("--project", help="project id (default: the registered project containing the current folder)")
    parser.add_argument("--url", default=None, help=f"dashboard URL (default: $RD_URL or {DEFAULT_URL})")
    args = parser.parse_args(argv)
    build_server(args.project, base_url=args.url).run("stdio")


if __name__ == "__main__":
    main()
