"""Shared fixtures: an isolated registry, the fake agent, a registered temporary project and a test client.

    def test_something(client, project):      # project = (pid, root)
        pid, root = project
        r = client.get(f"/api/projects/{pid}")
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from research_deck import config
from research_deck.dag import resolve


@pytest.fixture(autouse=True)
def isolated(tmp_path_factory, monkeypatch):
    """Every test gets its own machine-local dir and the fake agent; no test may reach a real CLI."""
    local = tmp_path_factory.mktemp("local")
    monkeypatch.setattr(config, "LOCAL_DIR", local)
    monkeypatch.setattr(config, "REGISTRY_FILE", local / "projects.json")
    monkeypatch.setattr(config, "SETTINGS_FILE", local / "settings.json")   # never the user's own defaults
    monkeypatch.setattr(config, "_SETTINGS_CACHE", (-1.0, {}))
    # Most tests build graphs across every stage in a project still at "idea": they run without the stage rules
    # (tests/test_stages.py covers those); a test that writes its own settings keeps this unless it says otherwise.
    (local / "settings.json").write_text('{"dag_defaults": {"stages": {"mode": "free"}}}')
    monkeypatch.setattr(config, "DEMO_ENABLED", False)      # only tests/test_demo.py materializes the demo
    monkeypatch.setattr(config, "FAKE_AGENT", True)
    # The map commits and tags with the user's git identity: tests bring their own (and never read ~/.gitconfig), so a
    # machine or CI runner without one runs them too. An explicit `git -c user.name=…` (the demo's) still wins.
    gitconfig = local / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Test\n\temail = test@example.invalid\n[commit]\n\tgpgsign = false\n[tag]\n\tgpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setitem(resolve.GIT_ENV, "GIT_CONFIG_GLOBAL", str(gitconfig))   # the map's git calls copy the env at import
    yield


@pytest.fixture
def client():
    from research_deck.app import create_app
    # The headers the dashboard page sends (app.py refuses mutations without X-RD-Request; actors.py issues the
    # human cookie only to a same-origin fetch).
    with TestClient(create_app(), headers={"X-RD-Request": "1", "Sec-Fetch-Site": "same-origin"}) as c:
        yield c


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(client, tmp_path):
    """A registered project folder with .research/ (not a git repo; call git(root, 'init') if a test needs one)."""
    root = tmp_path / "proj"
    root.mkdir()
    r = client.post("/api/projects", json={"root": str(root), "name": "Test Project"})
    assert r.status_code == 200, r.text
    return r.json()["id"], root
