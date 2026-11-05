"""Core: projects, files, safety and the agent runner's plumbing (fake agent)."""
import time


def test_project_files_roundtrip(client, project):
    pid, root = project
    r = client.put(f"/api/projects/{pid}/file", json={"path": "notes/a.md", "content": "hello"})
    assert r.status_code == 200
    sha = r.json()["sha"]
    assert client.get(f"/api/projects/{pid}/file", params={"path": "notes/a.md"}).json()["content"] == "hello"
    # a stale base_sha is a conflict, not an overwrite
    (root / "notes/a.md").write_text("changed elsewhere")
    r = client.put(f"/api/projects/{pid}/file", json={"path": "notes/a.md", "content": "mine", "base_sha": sha})
    assert r.status_code == 409


def test_path_escape_refused(client, project):
    pid, _ = project
    assert client.get(f"/api/projects/{pid}/file", params={"path": "../../etc/passwd"}).status_code == 400
    assert client.put(f"/api/projects/{pid}/file", json={"path": "../x", "content": ""}).status_code == 400


def test_foreign_origin_refused(client, project):
    pid, _ = project
    r = client.put(f"/api/projects/{pid}/file", json={"path": "a", "content": ""}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_sessions_and_fake_run(client, project):
    pid, _ = project
    doc = client.get(f"/api/projects/{pid}/sessions").json()
    assert set(doc["panels"]) == {"project"}      # one conversation per project
    r = client.put(f"/api/projects/{pid}/sessions/writing", json={"provider": "codex", "effort": "high", "fast": True})
    assert r.status_code == 200 and r.json()["active"] == "codex"
    run = client.post(f"/api/projects/{pid}/agent/run", json={"panel": "writing", "prompt": "hi"}).json()
    assert run["provider"] == "fake"
    for _ in range(100):
        got = client.get(f"/api/agent/runs/{run['run_id']}").json()
        if got["status"] != "running":
            break
        time.sleep(0.02)
    assert got["status"] == "done" and "fake" in got["text"]
    with client.stream("GET", f"/api/agent/runs/{run['run_id']}/stream") as s:
        body = "".join(s.iter_text())
    assert "event: agent" in body and '"type": "done"' in body
