"""The §11 service interface: never raises for a project without a DAG; cheap views for the other panels."""
from __future__ import annotations

from research_deck.dag import service
from test_dag_engine import build_world


def test_service_on_a_project_without_a_dag(project):
    pid, root = project
    assert service.graph(pid)["nodes"] == [] and service.graph(pid)["lenses"]["rerun"]["count"] == 0
    assert service.node(pid, "exp.x") is None and service.get_node(pid, "exp.x") is None
    assert service.lenses(pid)["confirmed"]["count"] == 0
    assert service.recent_events(pid) == []
    assert service.experiment_freshness(pid, "exp.x")["freshness"] == "unknown"
    assert service.nodes_by_commit(pid) == {} and service.design_components(pid) == []
    assert service.claims_for_doc(pid, "paper/main.tex") == []
    assert service.brief_data(pid)["revise"] == []
    assert service.graph("no-such-project")["nodes"] == []
    assert service.experiment_freshness("no-such-project", "exp.x")["freshness"] == "unknown"


def test_service_views(client, project):
    pid, root = project
    build_world(root)
    g = service.graph(pid)
    assert len(g["nodes"]) == 9 and g["digest"]
    comps = service.design_components(pid)
    assert {c["id"] for c in comps} == {"mod.sched", "mod.kv"}
    sched = next(c for c in comps if c["id"] == "mod.sched")
    assert sched["paths"] == ["src/lookahead/sched/**"] and sched["node_id"] == "mod.sched" and "design.sched#policy" in sched["description"]
    by_commit = service.nodes_by_commit(pid)
    assert any("exp.e2e" in ids for ids in by_commit.values()) and all(len(k) == 7 for k in by_commit)
    brief = service.brief_data(pid)
    assert brief["stage"] == "S6" and brief["lenses"]["confirmed"] == 2
    assert {c["id"] for c in brief["confirmed"]} == {"claim.ttft-2x"}
    assert [g["gate"] for g in brief["gates"]][:2] == ["G1", "G2"]
    assert service.get_node(pid, "claim.ttft-2x") == {"id": "claim.ttft-2x", "label": "claim.ttft-2x", "title": {"en": "claim.ttft-2x"},
                                                      "kind": "claim", "status": "confirmed", "freshness": "fresh"}
    events = service.recent_events(pid, limit=5)
    assert len(events) == 5 and events[0]["e"] > events[-1]["e"]
    detail = service.node(pid, "exp.e2e")
    assert detail["eval"]["cells"]["rate=4,system=vllm"]["level"] == "fresh"
    spec = __import__("research_deck.dag.seed", fromlist=["exec_spec"]).exec_spec(service.store_for(pid), "exp.e2e")
    assert spec["spec"]["sweep"] and spec["context"]["modules"]


def test_runs_without_a_result_are_unknown_not_stale(client, project):
    """Regression: a failed (or running) run whose trace still matches was reported `stale` with no reason, and a
    cell holding only a running run said "failed runs only"."""
    from research_deck.dag import seed
    pid, root = project
    s = build_world(root)
    failed = seed.record(s, "exp.kv-micro", "_", reads=["bench/micro_kv.py", "src/lookahead/kv/cache.py"],
                         cfg_keys=["kv.block"], outputs={"lat_us": 9.9}, state="failed")["run_id"]
    f = service.experiment_freshness(pid, "exp.kv-micro", run_id=failed)
    assert f["freshness"] == "unknown" and f["reasons"] == ["run failed"] and f["level"] == "fresh"
    assert service.experiment_freshness(pid, "exp.kv-micro")["freshness"] == "fresh"   # the cell's succeeded run
    seed.add(s, "exp.soak", "experiment", purpose="eval",
             facets={"spec": {"command": "python bench/e2e.py", "platform": "workstation", "gpus": 1}, "outputs": {"x": {}}})
    running = seed.record(s, "exp.soak", "_", reads=["bench/e2e.py"], cfg_keys=[], state="running")["run_id"]
    cell = service.node(pid, "exp.soak")["eval"]["cells"]["_"]
    assert cell["level"] == "unbuilt" and cell["why"][0]["note"] == "no succeeded run (1 running)"
    (root / "bench/e2e.py").write_text("import rd\n")                                    # its trace no longer matches
    f = service.experiment_freshness(pid, "exp.soak", run_id=running)
    assert f["freshness"] == "unknown" and f["reasons"] == ["run running", "code:bench/e2e.py: changed"]


def test_cli_check_and_eval(client, project, capsys):
    from research_deck.dag.__main__ import main
    pid, root = project
    build_world(root)
    assert main(["check", "--project", str(root)]) == 0
    assert main(["eval", "--project", str(root)]) == 0
    assert "confirmed 2" in capsys.readouterr().out
    (root / "src/lookahead/sched/policy.py").write_text("def admit(slack):\n    return slack > 5\n")
    (root / "src/lookahead/sched/__init__.py").write_text("")
    import subprocess
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    assert main(["preview", "--project", str(root), "--staged"]) == 0
    out = capsys.readouterr().out
    assert '"rerun": 2' in out
