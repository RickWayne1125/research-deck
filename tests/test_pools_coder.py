"""Coder workspaces as pool machines (pools/coder.py): a read that fails because the Coder CLI is signed out says so,
the sign-in goes to the folder ssh reads, the token only ever reaches the CLI's prompt, and no read starts a stopped
workspace. The CLI is a stand-in (tests/fake_coder.py) that behaves as Coder v2.35's does with --global-config."""
import json
import stat
import sys
from pathlib import Path

import pytest

from research_deck.pools import coder

HERE = Path(__file__).resolve().parent
FAKE = str(HERE / "fake_coder.py")
SSH_G = """user someone
hostname main.ws.me.coder
proxycommand /usr/local/bin/coder --global-config "/Users/someone/Library/Application Support/coderv2" ssh --stdio --hostname-suffix coder %h
"""
SSH_G_VSCODE = """proxycommand "/Users/someone/Library/Application Support/Code/User/globalStorage/coder.coder-remote/dep/bin/coder-darwin-arm64" --global-config "/Users/someone/Library/Application Support/Code/User/globalStorage/coder.coder-remote/dep" ssh --stdio %h
"""


def human(client):
    assert client.get("/api/session").status_code == 200


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """The stand-in CLI and a fresh folder of its own, as this computer's Coder setup. The CLI is one executable that
    needs no PATH (the real one is a single binary; the login empties PATH so no browser opens)."""
    folder = tmp_path / "coderv2"
    folder.mkdir()
    (folder / "url").write_text("https://coder.example.invalid/")
    exe = tmp_path / "coder"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    exe.chmod(0o755)
    monkeypatch.setattr(coder, "cli", lambda: str(exe))
    monkeypatch.setattr(coder, "default_folder", lambda: folder)
    return folder


def calls(folder: Path) -> list[dict]:
    return [json.loads(line) for line in (folder / "calls.jsonl").read_text().splitlines()]


def test_the_folder_ssh_reads_comes_from_its_proxy_command():
    binary, folder = coder.proxy_of(SSH_G)
    assert binary == "/usr/local/bin/coder" and folder == Path("/Users/someone/Library/Application Support/coderv2")
    assert coder.proxy_of("user someone\nhostname plain-box\n") is None
    assert coder.proxy_of(SSH_G_VSCODE)[1].name == "dep"
    assert coder.host_in(["python3", "rd_pool_ssh.py", "main.ws.me.coder"]) == "main.ws.me.coder"
    assert coder.host_in(["ssh", "me@coder.ws", "nvidia-smi"]) == "coder.ws"
    assert coder.host_in(["ssh", "gpu-box", "nvidia-smi"]) is None


def test_signing_in_goes_through_the_prompt_and_writes_the_folder_ssh_reads(client, cli, monkeypatch):
    human(client)
    s = client.get("/api/pools/coder/status").json()
    assert s["installed"] and not s["signed_in"] and s["error"] is None and s["url"] == "https://coder.example.invalid/"
    monkeypatch.setenv("CODER_SESSION_TOKEN", "from-the-server-env")         # never handed to the CLI: login refuses it
    r = client.post("/api/pools/coder/login", json={"url": "https://coder.example.invalid/", "token": "good-token"})
    assert r.status_code == 200, r.text
    assert r.json()["signed_in"] and r.json()["user"] == "tester"
    session = cli / "session"
    assert session.read_text() == "good-token" and stat.S_IMODE(session.stat().st_mode) == 0o600
    login = next(c for c in calls(cli) if "login" in c["argv"])
    assert "good-token" not in json.dumps(login["argv"])                      # never on a command line
    assert login["argv"][:2] == ["--global-config", str(cli)] and login["path"] == coder.NO_OPENER   # no browser opens


def test_a_token_coder_refuses_says_where_to_get_one(client, cli):
    human(client)
    r = client.post("/api/pools/coder/login", json={"url": "https://coder.example.invalid", "token": "wrong"})
    assert r.status_code == 400 and "did not accept the token" in r.json()["detail"]
    assert "https://coder.example.invalid/cli-auth" in r.json()["detail"] and not (cli / "session").exists()
    for body in ({"url": "coder.example.invalid", "token": "good-token"}, {"url": "https://c.example", "token": "a b"},
                 {"url": "https://c.example", "token": "x", "host": "gpu-box"}):
        assert client.post("/api/pools/coder/login", json=body).status_code == 400


def test_only_the_researcher_signs_coder_in(cli):
    from fastapi.testclient import TestClient

    from research_deck.app import create_app
    agent = TestClient(create_app(), headers={"X-RD-Request": "1"})
    assert agent.get("/api/pools/coder/status").status_code == 403
    assert agent.post("/api/pools/coder/login", json={"url": "https://c.example", "token": "good-token"}).status_code == 403


def test_a_host_the_vscode_extension_manages_is_left_to_it(monkeypatch, cli):
    monkeypatch.setattr(coder, "locate", lambda host=None: {"cli": coder.cli(), "folder": Path("/x/coder.coder-remote/dep"), "managed": "vscode"})
    with pytest.raises(ValueError, match="VS Code"):
        coder.login("https://coder.example.invalid", "good-token", "main.ws.me.coder")


def test_a_read_that_fails_because_coder_is_signed_out_says_so_and_never_starts_a_workspace(client, cli, tmp_path):
    human(client)
    # A pool command that goes through `coder ssh` (as ssh's ProxyCommand would) and reports the autostart switch.
    script = tmp_path / "read.py"
    script.write_text(
        "import os, subprocess, sys\n"
        f"p = subprocess.run([{FAKE!r}, '--global-config', {str(cli)!r}, 'ssh', '--stdio', sys.argv[1]], capture_output=True, text=True)\n"
        "sys.stderr.write(f'autostart off: {os.environ.get(\"CODER_SSH_DISABLE_AUTOSTART\")}\\n' + p.stderr)\n"
        "if p.returncode: sys.exit(1)\n"
        "print('{\"protocol\": \"rd-pool/1\", \"nodes\": [{\"id\": \"w\", \"gpus\": []}]}')\n")
    body = {"id": "ws", "label": "Workspace", "kind": "lab",
            "source": {"type": "command", "run": [sys.executable, str(script), "main.ws.me.coder"], "every": 600}}
    t = client.post("/api/pools/test", json=body).json()
    assert t["ok"] is False and t["needs"] == {"kind": "coder-login", "host": "main.ws.me.coder"}
    assert "autostart off: true" in t["error"]
    p = client.put("/api/pools/ws", json=body).json()["platform"]["pool"]
    assert p["state"] == "failed" and p["needs"]["kind"] == "coder-login"
    assert client.post("/api/pools/coder/login", json={"url": "https://coder.example.invalid", "token": "good-token"}).status_code == 200
    p = client.post("/api/pools/ws/refresh").json()["platform"]["pool"]
    assert p["state"] == "ok" and p["needs"] is None and p["error"] is None


def test_the_ssh_adapter_never_starts_a_workspace_either(monkeypatch, capsys):
    import importlib.util
    import subprocess
    spec = importlib.util.spec_from_file_location("rd_pool_ssh", HERE.parent / "scripts" / "pools" / "rd_pool_ssh.py")
    ssh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ssh)
    seen = {}

    def run(cmd, **kw):
        seen.update(kw.get("env") or {})
        return subprocess.CompletedProcess(cmd, 255, "", "error: You are signed out or your session has expired.")

    monkeypatch.setattr(ssh.subprocess, "run", run)
    monkeypatch.delenv("CODER_SSH_DISABLE_AUTOSTART", raising=False)
    assert ssh.main(["main.ws.me.coder"]) == 1 and seen["CODER_SSH_DISABLE_AUTOSTART"] == "true"
    assert coder.signed_out(capsys.readouterr().err)            # the reason reaches Research Deck, which offers the sign-in
