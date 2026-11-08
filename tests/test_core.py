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
    assert client.get(f"/api/projects/{pid}/raw", params={"path": "../../etc/passwd"}).status_code == 400


def test_raw_files_open_in_the_browser_and_never_run_as_pages(client, project):
    pid, root = project

    def raw(path):
        return client.get(f"/api/projects/{pid}/raw", params={"path": path})

    for folder in ("papers", "notes", "figures"):
        (root / folder).mkdir(exist_ok=True)
    (root / "papers/a paper.pdf").write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n%%EOF\n")
    r = raw("papers/a paper.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in r.headers           # Chrome's PDF viewer will not open in a sandbox
    # a page or a script shows as text, in a sandbox; a picture opens as itself, also in a sandbox
    (root / "notes/x.html").write_text("<script>alert(1)</script>")
    r = raw("notes/x.html")
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.headers["content-security-policy"].startswith("sandbox")
    (root / "figures/f.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    r = raw("figures/f.svg")
    assert r.headers["content-type"] == "image/svg+xml" and r.headers["content-security-policy"].startswith("sandbox")
    # text whose first 8 KiB end inside a character is still text; anything else downloads
    (root / "notes/long.txt").write_bytes(b"a" * 8191 + "é".encode() * 4)
    assert raw("notes/long.txt").headers["content-type"] == "text/plain; charset=utf-8"
    (root / "data.bin").write_bytes(b"\x00\x01\x02")
    r = raw("data.bin")
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")
    assert raw("papers/missing.pdf").status_code == 404
    assert raw("papers").status_code == 404


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
