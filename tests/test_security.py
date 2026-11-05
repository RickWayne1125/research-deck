"""Regression tests for the backend security review (2026-11-02): each test is one attack that used to work."""
import os
import subprocess

from conftest import git
from research_deck import util
from research_deck.agents import runner


def dag(pid):
    return f"/api/projects/{pid}/dag"


# ------------------------------------------------------------------ browser boundary

def test_rebound_host_is_refused(client, project):
    pid, _ = project
    r = client.get(f"/api/projects/{pid}/tree", headers={"Host": "attacker.example:8765"})
    assert r.status_code == 400


def test_mutation_needs_the_request_header(client, project):
    pid, _ = project
    r = client.put(f"/api/projects/{pid}/file", json={"path": "a.txt", "content": "x"}, headers={"X-RD-Request": ""})
    assert r.status_code == 403


def test_cross_site_reads_are_refused(client, project):
    pid, _ = project
    assert client.get(f"/api/projects/{pid}/tree", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_human_cookie_only_for_the_page(client):
    assert client.get("/api/session", headers={"Sec-Fetch-Site": ""}).status_code == 403
    assert client.get("/api/session").status_code == 200          # the page's own same-origin fetch


# ------------------------------------------------------------------ agents and the DAG

def test_agent_cannot_confirm_inside_one_batch(client, project):
    pid, _ = project
    # a problem node has no extra confirmation precondition, so only the permission rule can stop this
    ops = [{"op": "create", "node": {"id": "prob.a", "kind": "problem", "title": "A", "facets": {"statement": "s"}}},
           {"op": "set_status", "node": "prob.a", "to": "active"},
           {"op": "set_status", "node": "prob.a", "to": "confirmed", "reason": "self-approved"}]
    r = client.post(f"{dag(pid)}/ops", json={"ops": ops})        # no session cookie: agent:unknown
    assert r.status_code == 202 and r.json()["applied"] is False, r.text   # the whole batch became a proposal
    assert not any(n["id"] == "prob.a" for n in client.get(f"{dag(pid)}/graph").json()["nodes"])
    # the same batch from the researcher applies
    assert client.get("/api/session").status_code == 200
    r = client.post(f"{dag(pid)}/ops", json={"ops": ops})
    assert r.status_code == 200 and r.json()["applied"] is True, r.text


def test_config_edit_never_writes_code_or_dot_folders(client, project):
    pid, root = project
    for target in ("matplotlib.py", ".claude/settings.yaml", ".github/workflows/x.yml", "notes.txt"):
        r = client.post(f"{dag(pid)}/ops", json={"ops": [{"op": "config_edit", "file": target, "key": "x", "value": 1}]})
        assert r.status_code in (202, 400), (target, r.status_code)
        assert not (root / target).exists(), target


def test_agent_config_edit_of_unbound_yaml_is_a_proposal(client, project):
    pid, root = project
    r = client.post(f"{dag(pid)}/ops", json={"ops": [{"op": "config_edit", "file": "configs/new.yaml", "key": "a.b", "value": 1}]})
    assert r.status_code == 202 and not (root / "configs/new.yaml").exists()


def test_agents_cannot_record_runs(client, project):
    pid, _ = project
    r = client.post(f"{dag(pid)}/runs", json={"node": "exp.x", "cell": "_", "by": "system", "outputs": {}})
    assert r.status_code == 403


def test_snapshots_cannot_be_overwritten_or_named_like_gates(client, project):
    pid, _ = project
    assert client.post(f"{dag(pid)}/snapshots", json={"name": "gate-G5"}).status_code == 400
    assert client.post(f"{dag(pid)}/snapshots", json={"name": "milestone"}).status_code == 200
    assert client.post(f"{dag(pid)}/snapshots", json={"name": "milestone"}).status_code == 409


# ------------------------------------------------------------------ CLI arguments and processes

def test_session_ids_cannot_be_cli_options(client, project):
    pid, _ = project
    r = client.put(f"/api/projects/{pid}/sessions/project", json={"provider": "claude", "session_id": "--dangerously-skip-permissions"})
    assert r.status_code == 400
    spec = runner.RunSpec(project_id=pid, panel="project", provider="claude", model="claude-opus-5-5", effort="low",
                          fast=False, prompt="x", cwd=".", session_id="--add-dir=/")
    try:
        runner.build_command(spec, "/tmp")
        raise AssertionError("an option-like session id reached argv")
    except RuntimeError:
        pass


def test_claude_runs_are_restricted_and_codex_ignores_user_config():
    spec = runner.RunSpec(project_id="p", panel="project", provider="claude", model="claude-opus-5-5", effort="low",
                          fast=False, prompt="x", cwd=".", mcp=False)
    cmd = runner.build_command(spec, "/tmp")
    assert "--restricted" in cmd and "--strict-mcp-config" in cmd and "Bash" in ",".join(cmd)
    spec.provider, spec.model, spec.tools, spec.permission = "codex", "gpt-6-astra", False, "write"
    cmd = runner.build_command(spec, "/tmp")
    assert "--ignore-user-config" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"


def test_atomic_writes_keep_the_file_mode(tmp_path):
    f = tmp_path / "run.sh"
    f.write_text("#!/bin/sh\n")
    os.chmod(f, 0o755)
    util.write_text_atomic(f, "#!/bin/sh\necho hi\n")
    assert oct(f.stat().st_mode & 0o777) == "0o755"


def test_yaml_aliases_are_refused(tmp_path):
    f = tmp_path / "bomb.yaml"
    f.write_text("a: &a [1, 2]\nb: [*a, *a]\n")
    try:
        util.read_yaml(f)
        raise AssertionError("an alias was expanded")
    except Exception as e:      # noqa: BLE001
        assert "alias" in str(e).lower()


def test_git_filter_drivers_never_run(client, project):
    pid, root = project
    marker = root.parent / "PWNED"
    git(root, "init", "-q")
    (root / ".gitattributes").write_text("*.txt filter=evil\n")
    (root / "a.txt").write_text("a\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    subprocess.run(["git", "-C", str(root), "config", "filter.evil.clean", f"touch {marker}; cat"], check=True)
    (root / "a.txt").write_text("b\n")
    assert client.get(f"/api/projects/{pid}/git/status").status_code == 200
    assert client.get(f"/api/projects/{pid}/git/diff").status_code == 200
    assert not marker.exists()


def test_symlink_loops_do_not_hang_listings(client, project):
    pid, root = project
    (root / "figures").mkdir()
    (root / "figures" / "loop").symlink_to("..")
    (root / "outside").symlink_to("/")
    assert client.get(f"/api/projects/{pid}/tree").status_code == 200
    assert client.get(f"/api/projects/{pid}/figures/discover").status_code == 200
    assert client.get(f"/api/projects/{pid}/writing/docs").status_code == 200


def test_tailnet_requests_need_an_owner_identity(client, project, monkeypatch):
    from research_deck import config
    monkeypatch.setattr(config, "TAILNET_HOST", "box.example.ts.net")
    monkeypatch.setattr(config, "TAILNET_OWNERS", {"owner@example.com"})
    monkeypatch.setattr(config, "ALLOWED_HOSTS", [*config.ALLOWED_HOSTS, "box.example.ts.net"])
    from research_deck.app import create_app
    from fastapi.testclient import TestClient
    c = TestClient(create_app(), base_url="https://box.example.ts.net:8765")
    assert c.get("/api/system/health").status_code == 403                                   # no identity (tagged device)
    assert c.get("/api/system/health", headers={"Tailscale-User-Login": "other@example.com"}).status_code == 403
    r = c.get("/api/system/health", headers={"Tailscale-User-Login": "Owner@example.com"})
    assert r.status_code == 200 and r.json()["request"] == {"via": "tailnet", "login": "Owner@example.com"}
    # a forwarded request is treated as coming through Serve even when it names the loopback host
    assert client.get("/api/system/health", headers={"X-Forwarded-For": "100.64.0.9"}).status_code == 403
    assert client.get("/api/system/health").json()["request"]["via"] == "local"
