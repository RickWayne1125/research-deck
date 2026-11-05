"""User-level defaults, run queueing for agents, blocking gates and autocommit."""
import json
import time

from conftest import git
from research_deck import config


def dag(pid):
    return f"/api/projects/{pid}/dag"


def human(client):
    assert client.get("/api/session").status_code == 200


def set_settings(data):
    data = {**data, "dag_defaults": {"stages": {"mode": "free"}, **(data.get("dag_defaults") or {})}}
    config.SETTINGS_FILE.write_text(json.dumps(data))
    config._SETTINGS_CACHE = (-1.0, {})


EXP = {"op": "create", "node": {"id": "exp.bench", "kind": "experiment", "status": "active", "title": "Bench",
                                "facets": {"spec": {"command": "python bench.py", "platform": "workstation", "gpus": 1,
                                                    "est_hours": 0.5}, "outputs": {}}}}


def test_user_defaults_sit_between_the_repo_and_the_project(client, project):
    pid, root = project
    set_settings({"dag_defaults": {"gates": {"blocking": True}, "policy": {"agent_auto_run": {"max_gpu_hours_per_day": 3}}}})
    from research_deck.dag.service import store_for
    cfg = store_for(pid).config()
    assert cfg["gates"]["blocking"] is True and cfg["policy"]["agent_auto_run"]["max_gpu_hours_per_day"] == 3
    assert cfg["autocommit"]["enabled"] is False                       # repository default kept
    store_for(pid).ensure()
    (root / ".research/dag/config.yaml").write_text("gates: {blocking: false}\n")
    assert store_for(pid).config()["gates"]["blocking"] is False      # the project's own config wins


def test_queue_needs_confirmation_from_the_researcher(client, project):
    pid, _ = project
    human(client)
    assert client.post(f"{dag(pid)}/ops", json={"ops": [EXP]}).status_code == 200
    r = client.post(f"{dag(pid)}/runs/queue", json={"cells": [{"node": "exp.bench", "cell": "_"}]})
    assert r.status_code == 409
    r = client.post(f"{dag(pid)}/runs/queue", json={"cells": [{"node": "exp.bench", "cell": "_"}], "confirm": True})
    assert r.status_code == 200, r.text
    eid = r.json()["experiments"][0]
    rec = client.get(f"/api/projects/{pid}/experiments/{eid}").json()
    assert rec["status"] == "queued" and rec["node_id"] == "exp.bench"


def test_agents_queue_only_within_the_policy(client, project, tmp_path):
    pid, _ = project
    human(client)
    assert client.post(f"{dag(pid)}/ops", json={"ops": [EXP]}).status_code == 200
    from fastapi.testclient import TestClient

    from research_deck.app import create_app
    agent = TestClient(create_app(), headers={"X-RD-Request": "1"})      # no cookie: agent permissions
    cells = [{"node": "exp.bench", "cell": "_"}]
    assert agent.post(f"{dag(pid)}/runs/queue", json={"cells": cells, "platform": "workstation"}).status_code == 403  # budget 0
    set_settings({"dag_defaults": {"policy": {"agent_auto_run": {"max_gpu_hours_per_day": 8, "platforms": ["workstation"]}}}})
    r = agent.post(f"{dag(pid)}/runs/queue", json={"cells": cells, "platform": "cloud-a100"})
    assert r.status_code == 403 and "only on" in r.text
    r = agent.post(f"{dag(pid)}/runs/queue", json={"cells": cells, "platform": "workstation"})
    assert r.status_code == 200, r.text
    set_settings({"dag_defaults": {"policy": {"agent_auto_run": {"max_gpu_hours_per_day": 0.1, "platforms": ["workstation"]}}}})
    r = agent.post(f"{dag(pid)}/runs/queue", json={"cells": cells, "platform": "workstation"})
    assert r.status_code == 403 and "budget" in r.text


def test_blocking_gates_hold_the_stage(client, project):
    pid, _ = project
    human(client)
    base = f"/api/projects/{pid}/config"
    set_settings({"dag_defaults": {"gates": {"blocking": True}}})
    r = client.patch(base, json={"stage": "motivation"})
    assert r.status_code == 409 and "G1" in r.text
    set_settings({})
    assert client.patch(base, json={"stage": "motivation"}).status_code == 200
    set_settings({"dag_defaults": {"gates": {"blocking": True}}})
    assert client.patch(base, json={"stage": "idea"}).status_code == 200      # moving back is always allowed


def test_autocommit_commits_only_the_dag(client, project):
    pid, root = project
    git(root, "init", "-q", "-b", "main")
    (root / "code.py").write_text("x = 1\n")
    git(root, "add", "code.py")
    git(root, "commit", "-qm", "init")
    (root / "code.py").write_text("x = 2\n")                                 # never committed by the dashboard
    set_settings({"dag_defaults": {"autocommit": {"enabled": True, "debounce_s": 0.2}}})
    human(client)
    assert client.post(f"{dag(pid)}/ops", json={"ops": [EXP]}).status_code == 200
    for _ in range(50):
        log = git(root, "log", "--format=%s", "-n", "5")
        if "dag:" in log:
            break
        time.sleep(0.1)
    assert "dag:" in log
    files = git(root, "show", "--name-only", "--format=", "HEAD").split()
    assert files and all(f.startswith(".research/dag") or f.startswith("paper/generated") for f in files)
    assert "code.py" in git(root, "status", "--porcelain")
