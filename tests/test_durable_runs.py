"""Durable agent runs: each CLI run has a supervisor of its own and is followed from its folder, so a reload or a
server restart does not end it; stop and resume; steering a message into a running turn; the conversation's queue.
The CLIs are stand-ins (tests/fake_claude.py, tests/fake_codex.py); the supervisor and the server code are real."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from research_deck import config
from research_deck.agents import queue, runner, sessions

HERE = Path(__file__).resolve().parent


@pytest.fixture
def clis(monkeypatch):
    """Real runs (not the in-process fake agent) against the stand-in CLIs. Afterwards every run this test started
    (a queued follow-up included) is stopped and seen to end, so none outlives the test into the next one."""
    monkeypatch.setattr(config, "FAKE_AGENT", False)
    monkeypatch.setattr(config, "CLAUDE_CLI", str(HERE / "fake_claude.py"))
    monkeypatch.setattr(config, "CODEX_CLI", str(HERE / "fake_codex.py"))
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.05")
    monkeypatch.setenv("RD_FAKE_CODEX_STEP", "0.05")
    yield
    for _ in range(3):                      # a stopped run may start a queued "now" message: stop that too
        running = [r for r in runner.all_runs() if r.status == "running"]
        for r in running:
            runner.cancel(r.id)
        for r in running:
            r.wait(30)
        time.sleep(0.3)


def human(client):
    assert client.get("/api/session").status_code == 200


def wait_status(run_id: str, *, timeout: float = 30.0) -> runner.Run:
    run = runner.get(run_id)
    assert run is not None
    assert run.wait(timeout), f"run {run_id} did not end"
    return run


def wait_for(cond, timeout: float = 20.0, what: str = "a condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = cond()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def transcript(root: Path) -> list[dict]:
    path = root / ".research" / "context" / "transcripts" / "project.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def chat(client, pid: str, prompt: str, provider: str = "claude") -> str:
    client.put(f"/api/projects/{pid}/sessions/project", json={"provider": provider})
    r = client.post(f"/api/projects/{pid}/agent/run", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def test_a_claude_run_has_a_supervisor_and_a_folder(client, project, clis):
    pid, root = project
    run_id = chat(client, pid, "What is in the notes?")
    run = wait_status(run_id)
    assert run.status == "done", run.error
    assert "piece 1" in run.text and any(e["type"] == "tool" for e in run.events)
    d = runner.run_dir(run_id)
    assert (d / "out.jsonl").stat().st_size > 0 and json.loads((d / "exit.json").read_text())["code"] == 0
    assert json.loads((d / "meta.json").read_text())["finalized"] is True
    assert json.loads((d / "spec.json").read_text())["input"] == "stream-json"
    roles = [(e["role"], e["text"][:8]) for e in transcript(root)]
    assert roles[-2:] == [("user", "What is "), ("assistant", "piece 1 ")]
    assert sessions.get_binding(pid, "project")["session_id"] == run.session_id


def test_one_answer_at_a_time_per_conversation(client, project, clis, monkeypatch):
    pid, _ = project
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.3")
    first = chat(client, pid, "a slow question")
    r = client.post(f"/api/projects/{pid}/agent/run", json={"prompt": "another"})
    assert r.status_code == 409 and r.json()["detail"]["run_id"] == first
    runner.cancel(first)
    wait_status(first)


def test_a_steered_message_reaches_the_running_turn(client, project, clis, monkeypatch):
    pid, root = project
    human(client)
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.25")
    run_id = chat(client, pid, "Summarize the idea")
    wait_for(lambda: any(e["type"] == "text" for e in runner.get(run_id).events), what="the first words")
    r = client.post(f"/api/agent/runs/{run_id}/steer", json={"text": "focus on the risks"})
    assert r.status_code == 200 and r.json()["mode"] == "steered"
    msg_id = r.json()["id"]
    run = wait_status(run_id)
    assert run.status == "done" and "(read: focus on the risks)" in run.text
    kinds = [(e["type"], e.get("id")) for e in run.events if e["type"] in ("steer", "user")]
    assert kinds == [("steer", msg_id), ("user", msg_id)]                    # handed over, then read: once each
    log = transcript(root)
    assert [(e["role"], e.get("steer", False)) for e in log[-3:]] == [("user", False), ("user", True), ("assistant", False)]
    assert log[-2]["text"] == "focus on the risks"
    assert not list((runner.run_dir(run_id) / "inbox").glob("*.json"))


def test_stop_then_resume_continues_the_same_session(client, project, clis, monkeypatch):
    pid, root = project
    human(client)
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.3")
    run_id = chat(client, pid, "a long task")
    wait_for(lambda: runner.get(run_id).session_id, what="the session id")
    assert client.post(f"/api/agent/runs/{run_id}/cancel").json()["ok"]
    run = wait_status(run_id)
    assert run.status == "cancelled" and run.error is None
    last = transcript(root)[-1]
    assert last["role"] == "assistant" and last["status"] == "cancelled"
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.01")
    resumed = wait_status(chat(client, pid, "Continue where you left off."))
    assert resumed.status == "done" and resumed.session_id == run.session_id      # the same session, resumed
    spec = json.loads((runner.run_dir(resumed.id) / "spec.json").read_text())
    assert spec["cmd"][spec["cmd"].index("--resume") + 1] == run.session_id


def test_a_queued_message_starts_when_the_answer_ends(client, project, clis, monkeypatch):
    pid, root = project
    human(client)
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.15")
    first = chat(client, pid, "first question")
    r = client.post(f"/api/projects/{pid}/agent/queue", json={"text": "second question"})
    assert r.status_code == 200 and [i["text"] for i in r.json()["items"]] == ["second question"]
    assert r.json()["started"] is None
    wait_status(first)
    nxt = wait_for(lambda: next((x for x in runner.all_runs() if x.id != first and x.spec.purpose == "chat"), None),
                   what="the queued message to start")
    assert nxt.spec.user_text == "second question"
    assert client.get(f"/api/projects/{pid}/agent/queue").json()["items"] == []
    assert wait_status(nxt.id).status == "done"
    # with nothing running, queuing starts the message at once
    r = client.post(f"/api/projects/{pid}/agent/queue", json={"text": "third"})
    assert r.json()["started"]["run_id"]
    wait_status(r.json()["started"]["run_id"])


def test_a_stopped_answer_leaves_the_queue_waiting_and_send_now_steers(client, project, clis, monkeypatch):
    pid, _ = project
    human(client)
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.25")
    first = chat(client, pid, "first")
    item = client.post(f"/api/projects/{pid}/agent/queue", json={"text": "later"}).json()["items"][0]
    item2 = client.post(f"/api/projects/{pid}/agent/queue", json={"text": "now please"}).json()["items"][1]
    r = client.post(f"/api/projects/{pid}/agent/queue/{item2['id']}/send")
    assert r.json()["mode"] == "steered" and [i["id"] for i in r.json()["items"]] == [item["id"]]
    wait_for(lambda: any(e["type"] == "user" and e["text"] == "now please" for e in runner.get(first).events),
             what="Claude to read it")
    runner.cancel(first)
    assert wait_status(first).status == "cancelled"
    time.sleep(0.5)
    assert [x.id for x in runner.all_runs() if x.status == "running"] == []           # stopped: nothing starts
    assert [i["text"] for i in queue.items(pid, "project")] == ["later"]


def _ended_run(pid: str, *, stopped: bool) -> runner.Run:
    from research_deck.agents.api import RunBody, spec_for
    run = runner.Run(spec=spec_for(pid, RunBody(prompt="x")))
    run.dir = runner.run_dir(run.id)
    run.cancel_requested = stopped
    (run.dir / "inbox").mkdir(parents=True)
    # read; handed over but not read; never handed over (the CLI had stopped reading)
    run.events += [{"type": "steer", "id": "1-a", "text": "read"}, {"type": "user", "id": "1-a", "text": "read"},
                   {"type": "steer", "id": "2-b", "text": "dropped by the stop"}]
    (run.dir / "inbox" / "3-c.json").write_text(json.dumps({"id": "3-c", "text": "never handed over"}))
    return run


def test_messages_claude_never_read_go_first_in_the_queue(project):
    pid, _ = project
    queue.add(pid, "project", "already waiting")
    run = _ended_run(pid, stopped=True)
    runner._requeue_unread(run)
    items = queue.items(pid, "project")
    assert [i["text"] for i in items] == ["dropped by the stop", "never handed over", "already waiting"]
    assert not any(i["now"] for i in items)                   # a stopped run: they wait for the researcher
    assert not list((run.dir / "inbox").glob("*.json"))


def test_a_finished_run_read_what_it_was_handed(project):
    pid, _ = project
    runner._requeue_unread(_ended_run(pid, stopped=False))   # Claude answers every message it has before it ends
    assert [i["text"] for i in queue.items(pid, "project")] == ["never handed over"]


def test_codex_cannot_take_a_message_mid_turn_so_steering_restarts_the_session(client, project, clis, monkeypatch):
    pid, root = project
    human(client)
    monkeypatch.setenv("RD_FAKE_CODEX_STEP", "0.3")
    monkeypatch.setenv("RD_FAKE_CODEX_PIECES", "20")
    first = chat(client, pid, "codex, a long task", provider="codex")
    wait_for(lambda: runner.get(first).session_id, what="the thread id")
    r = client.post(f"/api/agent/runs/{first}/steer", json={"text": "change of plan"})
    assert r.json()["mode"] == "restart"
    run = wait_status(first)
    assert run.status == "cancelled"
    monkeypatch.setenv("RD_FAKE_CODEX_PIECES", "1")
    nxt = wait_for(lambda: next((x for x in runner.all_runs() if x.id != first), None), what="the continuation")
    assert nxt.spec.user_text == "change of plan"
    assert wait_status(nxt.id).status == "done" and nxt.session_id == run.session_id
    assert "change of plan" in nxt.text


def test_a_run_outlives_the_server_that_started_it(client, project, clis, monkeypatch):
    """A previous server spawned the supervisor and went away; this one picks the run up and sees it end."""
    pid, root = project
    monkeypatch.setenv("RD_FAKE_CLAUDE_STEP", "0.2")
    from research_deck.agents.api import RunBody, spec_for
    spec = spec_for(pid, RunBody(prompt="started by the old server"))
    spec.provider = "claude"
    old = runner.Run(spec=spec)
    old.dir = runner.run_dir(old.id)
    runner._spawn(old)                     # the supervisor, as the old server left it: nobody follows it here
    wait_for(lambda: (old.dir / "out.jsonl").exists() and (old.dir / "out.jsonl").stat().st_size > 0, what="output")
    assert runner.get(old.id) is None
    assert runner.recover() == 1
    run = wait_status(old.id)
    assert run.status == "done" and run.text.startswith("piece 1")
    assert runner.recover() == 0                                                     # finalized: not picked up twice
    # a browser that reconnects with an id from the old server is told to start over
    with client.stream("GET", f"/api/agent/runs/{old.id}/stream", headers={"Last-Event-ID": "0ldb00t:7"}) as r:
        first = next(line for line in r.iter_lines() if line.startswith("data:"))
    assert json.loads(first[5:]) == {"type": "reset"}


def test_steering_and_the_queue_are_the_researchers(client, project):
    pid, _ = project
    assert client.post("/api/agent/runs/nope/steer", json={"text": "x"}).status_code == 403
    assert client.post(f"/api/projects/{pid}/agent/queue", json={"text": "x"}).status_code == 403
