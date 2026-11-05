"""The research-deck MCP server, in process: its tool list, the identity headers it sends, and calls through the
dashboard's own routes (a TestClient is an httpx.Client, so it serves as the server's HTTP layer)."""
from __future__ import annotations

import json

import anyio
import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from research_deck import actors, mcp_server

EXPECTED_TOOLS = {"rd_brief", "rd_lenses", "rd_graph", "rd_node", "rd_explain", "rd_impact", "rd_apply", "rd_propose",
                  "rd_attest", "rd_plan_runs", "rd_queue_runs", "rd_experiments", "rd_handoff_note"}


def call(server, name: str, args: dict | None = None) -> str:
    result = anyio.run(server.call_tool, name, args or {})
    content = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(block, "text", "") for block in content)


def test_tool_list_and_descriptions():
    server = mcp_server.build_server("p", httpx.Client(base_url="http://rd.invalid"))
    tools = {t.name: t for t in anyio.run(server.list_tools)}
    assert set(tools) == EXPECTED_TOOLS
    assert not any(word in name for name in tools for word in ("lock", "approve", "gate", "select", "exclude", "record_run"))
    lenses = tools["rd_lenses"].description
    assert all(lens in lenses for lens in ("tried", "confirmed", "revise", "rerun"))
    assert "proposal" in tools["rd_apply"].description
    assert tools["rd_graph"].inputSchema["properties"]["lens"]
    assert "four lenses" in server.instructions.lower() and "proposal" in server.instructions


def test_rd_lenses_sends_identity_and_returns_compact_json(tmp_path):
    (tmp_path / "agent.token").write_text("tok-123\n")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"tried": {"count": 9, "ids": ["sol.mlfq"]}, "confirmed": 3, "revise": 2, "rerun": 4})

    http = httpx.Client(base_url="http://rd.test", transport=httpx.MockTransport(handler))
    server = mcp_server.build_server("toycache", http, actor="agent:codex:019a3f", local_dir=tmp_path)
    text = call(server, "rd_lenses")
    assert json.loads(text)["rerun"] == 4 and " " not in text
    req = seen[0]
    assert req.method == "GET" and req.url.path == "/api/projects/toycache/dag/lenses"
    assert req.headers["x-rd-actor"] == "agent:codex:019a3f" and req.headers["x-rd-agent-token"] == "tok-123"


def test_errors_carry_a_hint():
    http = httpx.Client(base_url="http://rd.test", transport=httpx.MockTransport(
        lambda r: httpx.Response(403, json={"detail": {"message": "open a proposal"}})))
    server = mcp_server.build_server("toycache", http, actor="agent:claude:x")
    with pytest.raises(ToolError) as e:
        call(server, "rd_apply", {"ops": [{"op": "lock", "node": "design.sched"}]})
    assert "403" in str(e.value) and "rd_propose" in str(e.value)


def test_graph_is_compacted():
    graph = {"digest": "d:1", "lenses": {"rerun": 1},
             "nodes": [{"id": "exp.e7", "kind": "experiment", "stage": "S6", "title": {"en": "E7 main"}, "status": "active",
                        "head": {"rev": 2}, "facets": {"spec": {"type": "json", "value": {"big": "x" * 500}}},
                        "edges": [{"type": "input", "to": "node:data.lb"}, {"type": "cites", "to": "node:ref.x"}]}],
             "eval": {"exp.e7": {"level": "stale", "flags": ["impl_lag"], "shaky": [], "cells": {"_": {"level": "stale"}}}}}
    http = httpx.Client(base_url="http://rd.test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=graph)))
    out = json.loads(call(mcp_server.build_server("p", http), "rd_graph", {"lens": "rerun"}))
    assert out["nodes"] == [{"id": "exp.e7", "kind": "experiment", "stage": "S6", "title": "E7 main", "status": "active",
                             "level": "stale", "flags": ["impl_lag"], "edges": ["input:node:data.lb"], "cells": {"_": "stale"}}]


def test_tools_through_the_dashboard_routes(client, project):
    pid, root = project
    actors.agent_token()            # created by the server on first use; the MCP server reads the same file
    import research_deck.config as config
    server = mcp_server.build_server(pid, client, actor="agent:claude:46e445", local_dir=config.LOCAL_DIR)
    brief_md = call(server, "rd_brief")
    assert brief_md.startswith("# Project brief: Test Project")
    out = json.loads(call(server, "rd_handoff_note", {"text": "The allocator refactor is half done"}))
    assert out["from"] == "claude" and out["to"] == "codex"     # the token was accepted, so the actor counted
    note = (root / ".research/context/pending/project-codex.md").read_text()
    assert "The allocator refactor is half done" in note and "agent:claude:46e445" in note
