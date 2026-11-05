"""Agents slice: session discovery, the panel transcript (with an imported session tail), handoffs, the brief and
the MCP registration snippets. Everything runs on the fake agent; no real CLI is touched."""
from __future__ import annotations

import json
import time

import pytest

from research_deck import config
from research_deck.agents import brief, discover, handoff, runner


def wait_run(client, run_id: str) -> dict:
    for _ in range(300):
        got = client.get(f"/api/agent/runs/{run_id}").json()
        if got["status"] != "running":
            return got
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def chat(client, pid: str, panel: str, prompt: str) -> dict:
    r = client.post(f"/api/projects/{pid}/agent/run", json={"panel": panel, "prompt": prompt})
    assert r.status_code == 200, r.text
    return wait_run(client, r.json()["run_id"])


@pytest.fixture
def homes(tmp_path, monkeypatch):
    """Empty CLAUDE_HOME / CODEX_HOME so discovery and imports read only what a test writes."""
    claude_home, codex_home = tmp_path / "claude-home", tmp_path / "codex-home"
    claude_home.mkdir()
    codex_home.mkdir()
    monkeypatch.setattr(config, "CLAUDE_HOME", claude_home)
    monkeypatch.setattr(config, "CODEX_HOME", codex_home)
    return claude_home, codex_home


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


CLAUDE_SID = "6f1c2d3e-0000-4000-8000-000000000001"
CODEX_SID = "019a3f00-1111-7222-8333-444455556666"


def make_claude_session(claude_home, root, messages):
    lines = []
    for i, (role, text) in enumerate(messages):
        ts = f"2026-11-01T10:00:{i:02d}.000Z"
        if role == "user":
            lines.append({"type": "user", "sessionId": CLAUDE_SID, "cwd": str(root), "timestamp": ts, "isSidechain": False,
                          "message": {"role": "user", "content": text}})
        else:
            lines.append({"type": "assistant", "sessionId": CLAUDE_SID, "cwd": str(root), "timestamp": ts, "isSidechain": False,
                          "message": {"id": f"msg_{i}", "role": "assistant", "content": [{"type": "text", "text": text}]}})
    write_jsonl(claude_home / "projects" / discover.claude_slug(str(root)) / f"{CLAUDE_SID}.jsonl", lines)


def make_codex_session(codex_home, root, messages):
    lines = [{"timestamp": "2026-11-01T09:00:00.000Z", "type": "session_meta",
              "payload": {"id": CODEX_SID, "cwd": str(root), "thread_source": "user"}},
             {"timestamp": "2026-11-01T09:00:01.000Z", "type": "response_item",
              "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>cwd</environment_context>"}]}}]
    for i, (role, text) in enumerate(messages):
        kind = "input_text" if role == "user" else "output_text"
        lines.append({"timestamp": f"2026-11-01T09:01:{i:02d}.000Z", "type": "response_item",
                      "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}})
    write_jsonl(codex_home / "sessions" / "2026" / "11" / "01" / f"rollout-2026-11-01T09-00-00-{CODEX_SID}.jsonl", lines)


# ------------------------------------------------------------------ discovery

def test_discover_route_fills_bound_to(client, project, homes):
    pid, root = project
    claude_home, codex_home = homes
    make_claude_session(claude_home, root, [("user", "Profile the prefetcher on LongBench"), ("assistant", "Done.")])
    make_codex_session(codex_home, root, [("user", "Review the scheduler diff"), ("assistant", "Looks fine.")])
    r = client.put(f"/api/projects/{pid}/sessions/coding", json={"provider": "codex", "session_id": CODEX_SID})
    assert r.status_code == 200

    found = client.get(f"/api/projects/{pid}/sessions/discover").json()
    by_id = {s["session_id"]: s for s in found}
    assert set(by_id) == {CLAUDE_SID, CODEX_SID}
    assert by_id[CLAUDE_SID]["provider"] == "claude" and by_id[CLAUDE_SID]["title"].startswith("Profile the prefetcher")
    assert by_id[CLAUDE_SID]["bound_to"] is None
    assert by_id[CODEX_SID]["bound_to"] == "project" and by_id[CODEX_SID]["turns"] == 1

    only_codex = client.get(f"/api/projects/{pid}/sessions/discover", params={"provider": "codex"}).json()
    assert [s["session_id"] for s in only_codex] == [CODEX_SID]
    assert client.get(f"/api/projects/{pid}/sessions/discover", params={"provider": "gpt"}).status_code == 400


# ------------------------------------------------------------------ transcript

def test_transcript_records_runs_and_imports_the_session_tail(client, project, homes):
    pid, root = project
    claude_home, _ = homes
    got = chat(client, pid, "project", "What is the stage of the project?")
    assert got["status"] == "done"
    entries = client.get(f"/api/projects/{pid}/transcript/project").json()
    assert [e["role"] for e in entries] == ["user", "assistant"]
    assert entries[0]["text"] == "What is the stage of the project?"
    assert entries[1]["model"] and entries[1]["effort"]          # which model answered

    # The researcher also talked to the bound Claude session in a terminal; the dashboard's own prompt shows up there
    # too (wrapped in injected blocks) and must not appear twice.
    make_claude_session(claude_home, root, [
        ("user", "<context>\nFile in focus: x\n</context>\n\nWhat is the stage of the project?"),
        ("user", "Also check paper/main.tex for the TTFT claim"),
        ("assistant", "The TTFT claim cites exp.e2e-sharegpt."),
    ])
    client.put(f"/api/projects/{pid}/sessions/project", json={"provider": "claude", "session_id": CLAUDE_SID})
    plain = client.get(f"/api/projects/{pid}/transcript/project").json()
    assert not any(e.get("imported") for e in plain)
    merged = client.get(f"/api/projects/{pid}/transcript/project", params={"import": 1}).json()
    imported = [e for e in merged if e.get("imported")]
    assert [e["text"] for e in imported] == ["Also check paper/main.tex for the TTFT claim", "The TTFT claim cites exp.e2e-sharegpt."]
    assert len(client.get(f"/api/projects/{pid}/transcript/project", params={"import": 1, "limit": 2}).json()) == 2
    assert client.get(f"/api/projects/{pid}/transcript/nope").status_code == 404


def test_transcript_imports_codex_rollout(client, project, homes):
    pid, root = project
    _, codex_home = homes
    make_codex_session(codex_home, root, [("user", "Explain the eviction policy"), ("assistant", "It is LRU per tier.")])
    client.put(f"/api/projects/{pid}/sessions/coding", json={"provider": "codex", "session_id": CODEX_SID})
    merged = client.get(f"/api/projects/{pid}/transcript/coding", params={"import": "1"}).json()
    assert [(e["role"], e["text"]) for e in merged] == [("user", "Explain the eviction policy"), ("assistant", "It is LRU per tier.")]
    assert all(e["imported"] and e["provider"] == "codex" for e in merged)


# ------------------------------------------------------------------ handoff

def test_handoff_writes_note_queues_it_and_switches(client, project, monkeypatch):
    pid, root = project
    (root / "src").mkdir()
    (root / "src" / "prefetch.py").write_text("x = 1\n")
    chat(client, pid, "writing", "We decided to use the LongBench numbers in src/prefetch.py. Is the 2x claim still safe?")

    r = client.post(f"/api/projects/{pid}/handoff", json={"panel": "writing", "to": "codex", "smart": False})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["pending"] is True and out["from"] == "claude" and out["to"] == "codex" and out["smart"] is False
    note = (root / out["file"]).read_text()
    assert out["file"].startswith(".research/context/handoffs/") and out["file"].endswith("-project-claude-to-codex.md")
    assert "src/prefetch.py" in note and "We decided" in note and "Is the 2x claim still safe?" in note
    assert "## Project brief (excerpt)" in note
    pending = root / ".research/context/pending/project-codex.md"
    assert pending.read_text().strip() == note.strip()

    doc = client.get(f"/api/projects/{pid}/sessions").json()
    assert doc["panels"]["project"]["active"] == "codex"
    entries = client.get(f"/api/projects/{pid}/transcript/writing").json()
    assert entries[-1]["role"] == "handoff" and entries[-1]["from"] == "claude" and entries[-1]["to"] == "codex"

    # The next run to Codex in this panel carries the note exactly once; the one after does not.
    prompts: list[str] = []
    monkeypatch.setitem(runner.FAKE_RESPONDERS, "chat", lambda spec: prompts.append(spec.prompt) or "ok")
    chat(client, pid, "writing", "Continue")
    chat(client, pid, "writing", "And then?")
    assert prompts[0].count("<handoff>") == 1 and prompts[0].count("</handoff>") == 1
    assert "We decided" in prompts[0] and prompts[0].rstrip().endswith("Continue")
    assert "<handoff>" not in prompts[1]
    assert not pending.exists()

    # Switching back only summarizes what happened since this handoff.
    back = client.post(f"/api/projects/{pid}/handoff", json={"panel": "writing", "to": "claude"}).json()
    back_note = (root / back["file"]).read_text()
    assert "Messages since the last handoff: 4" in back_note and "We decided to use" not in back_note.split("## Last exchanges")[0]


def test_smart_handoff_uses_the_outgoing_agent(client, project):
    pid, root = project
    chat(client, pid, "coding", "Refactor the tier allocator into its own module")
    out = client.post(f"/api/projects/{pid}/handoff", json={"panel": "coding", "to": "codex", "smart": True}).json()
    assert out["smart"] is True and out["error"] is None
    assert "(fake summary of 2 messages) Refactor the tier allocator" in out["summary"]
    note = (root / out["file"]).read_text()
    assert "written by Claude Code (claude-sonnet-5-5, low effort)" in note
    assert "<handoff>" not in note
    # the summary run was ephemeral: it is not part of the panel's transcript
    roles = [e["role"] for e in client.get(f"/api/projects/{pid}/transcript/coding").json()]
    assert roles == ["user", "assistant", "handoff"]


def test_every_view_hands_off_the_one_conversation(client, project):
    pid, root = project
    chat(client, pid, "experiments", "Plan the e7 sweep")
    out = client.post(f"/api/projects/{pid}/handoff", json={"panel": "experiments", "to": "codex"}).json()
    assert out["panel"] == "project"
    assert (root / ".research/context/pending/project-codex.md").exists()
    doc = client.get(f"/api/projects/{pid}/sessions").json()
    assert doc["panels"]["project"]["active"] == "codex"
    same = client.post(f"/api/projects/{pid}/handoff", json={"panel": "project", "to": "codex"}).json()
    assert same.get("unchanged") is True and same["file"] is None
    assert client.post(f"/api/projects/{pid}/handoff", json={"panel": "project", "to": "gemini"}).status_code == 400


def test_agent_note_goes_to_the_other_backend(client, project):
    pid, root = project
    from research_deck import actors
    token = actors.agent_token()
    r = client.post(f"/api/projects/{pid}/handoff/note", json={"panel": "visualization", "text": "Fig 3 uses the r3 data"},
                    headers={"X-RD-Actor": "agent:codex:019a3f", "X-RD-Agent-Token": token})
    assert r.status_code == 200, r.text
    assert r.json()["from"] == "codex" and r.json()["to"] == "claude"
    assert "Fig 3 uses the r3 data" in (root / ".research/context/pending/project-claude.md").read_text()
    listed = client.get(f"/api/projects/{pid}/handoffs").json()
    assert listed["pending"][0]["panel"] == "project" and listed["recent"][0]["kind"] == "note"
    # a note does not count as a switch: the next handoff still covers the whole conversation
    assert client.post(f"/api/projects/{pid}/handoff/note", json={"panel": "project", "text": "  "}).status_code == 400


def test_extract_finds_decisions_questions_and_files(project):
    pid, root = project
    (root / "paper").mkdir()
    (root / "paper" / "main.tex").write_text("")
    x = handoff.extract(pid, [
        {"role": "user", "text": "Let's go with chunked prefill.\n```\nnot/a/file.py?\n```"},
        {"role": "assistant", "text": "I edited paper/main.tex and ghost/missing.py. Should claim.ttft-2x cite exp.e2e?"},
    ])
    assert x["decisions"] == ["Let's go with chunked prefill."]
    assert x["files"] == ["paper/main.tex"]
    assert x["questions"] == ["I edited paper/main.tex and ghost/missing.py. Should claim.ttft-2x cite exp.e2e?"]
    assert "claim.ttft-2x" in x["nodes"]


# ------------------------------------------------------------------ brief

def test_brief_without_a_dag(client, project, monkeypatch):
    pid, root = project
    monkeypatch.setattr(brief, "dag_data", lambda pid: None)
    r = client.get(f"/api/projects/{pid}/brief")
    assert r.status_code == 200
    out = r.json()
    md = out["markdown"]
    assert md.startswith("# Project brief: Test Project")
    assert "No research DAG yet" in md and "## Where things live" in md and "## Agents on this project" in md
    assert (root / ".research/context/BRIEF.md").read_text() == md
    # unchanged content keeps the file (and its timestamp) as it was
    again = client.get(f"/api/projects/{pid}/brief").json()
    assert again["generated_at"] == out["generated_at"]


def test_brief_formats_dag_data(client, project, monkeypatch):
    pid, _ = project
    monkeypatch.setattr(brief, "dag_data", lambda pid: {
        "stage": "S4",
        "lenses": {"tried": 9, "confirmed": {"count": 3, "ids": ["a", "b", "c"]}, "revise": 2, "rerun": 4},
        "revise": [{"id": "mod.sched", "title": {"en": "Scheduler module"}, "level": "review",
                    "reason": "implements:node:design.sched#preemption changed"}],
        "rerun": [{"node": "exp.e2e-sharegpt", "cells": ["rate=8,system=ours"], "est_gpu_h": 1.2}],
        "confirmed": [{"id": "find.prefill-stall", "title": {"en": "Prefill stalls decode", "zh": "预填充阻塞解码"}},
                      {"id": "gap.interference", "kind": "gap", "title": "Interference headroom", "text": "1.8x headroom over vLLM"}],
        "attempts": [{"alt_group": "gap.interference", "tried": 4, "chosen": "sol.chunk-budget",
                      "dead": [{"id": "sol.mlfq", "status": "refuted", "reason": "TPOT p99 1.21x"}]}],
        "open_proposals": [{"id": "p-0012", "title": "Relink claim", "ops": [{}, {}], "by": "agent:codex:019a3f"}],
        "gates": [{"gate": "G4", "status": "open", "checks": [{"ok": True}, {"ok": False}]}],
    })
    md = client.get(f"/api/projects/{pid}/brief").json()["markdown"]
    assert "Lenses: tried 9 · confirmed 3 · revise 2 · rerun 4" in md
    assert "`mod.sched` Scheduler module — review: implements:node:design.sched#preemption changed" in md
    assert "`exp.e2e-sharegpt` [rate=8,system=ours] — ~1.2 GPU-h" in md
    assert "Prefill stalls decode (预填充阻塞解码)" in md
    assert "`gap.interference` (gap) Interference headroom — 1.8x headroom over vLLM" in md
    assert "`gap.interference`: 4 tried, chosen `sol.chunk-budget`, ruled out: `sol.mlfq` refuted (TPOT p99 1.21x)" in md
    assert "`p-0012` Relink claim (2 ops), by agent:codex:019a3f" in md
    assert "G4: open, 1/2 checks green" in md


def test_brief_follows_dag_events(client, project, monkeypatch):
    pid, root = project
    from research_deck.events import hub
    monkeypatch.setattr(brief, "dag_data", lambda pid: None)
    path = root / ".research/context/BRIEF.md"
    assert not path.exists()
    hub.publish(pid, "dag", {"digest": "d:1", "changed": []})
    assert pid in brief._timers                 # debounced refresh scheduled
    brief.flush(pid)                            # a run about to start does not wait for the timer
    assert path.exists() and pid not in brief._timers


# ------------------------------------------------------------------ MCP registration snippets

def test_mcp_config_route(client, project):
    pid, _ = project
    r = client.get("/api/mcp/config", params={"project": pid})
    assert r.status_code == 200
    cfg = r.json()
    server = cfg["claude"]["mcpServers"]["research-deck"]
    assert server["args"] == ["-m", "research_deck.mcp_server", "--project", pid]
    assert server["env"]["RD_ACTOR"].startswith("agent:claude:") and server["env"]["PYTHONPATH"].endswith("server")
    assert cfg["commands"]["claude"].startswith("claude mcp add research-deck -s user ")
    assert cfg["commands"]["claude"].endswith(f"-m research_deck.mcp_server --project {pid}")
    assert cfg["commands"]["codex"].startswith("codex mcp add research-deck --env ")
    assert "[mcp_servers.research-deck]" in cfg["codex"] and f'"--project", "{pid}"' in cfg["codex"]
    assert set(cfg["env"]) == {"PYTHONPATH", "RD_URL", "RD_LOCAL_DIR"}
    assert client.get("/api/mcp/config", params={"project": "nope"}).status_code == 404
