"""DAG routes: graph shape (web/src/dag-types.ts), permissions per actor (§2.7), proposals, locks, runs, snapshots,
gates, paper sync. Agents are requests without the browser cookie (agent:unknown) or with the MCP token."""
from __future__ import annotations

import pytest

from conftest import git
from research_deck import actors
from test_dag_engine import FILES, OURS_CFG, OURS_READS, build_world, commit, write

NODE_KEYS = {"id", "kind", "stage", "title", "status", "head", "facets", "edges"}
EVAL_KEYS = {"level", "archived", "reasons", "flags", "shaky"}
CELL_KEYS = {"level", "run", "reused", "why"}


@pytest.fixture
def dag(client, project):
    pid, root = project
    build_world(root)
    return client, pid, root, f"/api/projects/{pid}/dag"


def as_human(client):
    assert client.get("/api/session").status_code == 200


def agent_headers(session: str = "46e445") -> dict:
    return {"X-RD-Actor": f"agent:claude:{session}", "X-RD-Agent-Token": actors.agent_token()}


def test_graph_shape_matches_the_frontend_contract(dag):
    client, pid, _, base = dag
    g = client.get(f"{base}/graph").json()
    assert set(g) >= {"nodes", "eval", "lenses", "digest"} and g["digest"].startswith("d:")
    for n in g["nodes"]:
        assert NODE_KEYS <= set(n) and {"rev", "vid", "fp"} <= set(n["head"])
        ev = g["eval"][n["id"]]
        assert EVAL_KEYS <= set(ev) and ev["level"] == "fresh"
    cells = g["eval"]["exp.e2e"]["cells"]
    assert set(cells) == {"rate=4,system=ours", "rate=4,system=vllm", "rate=8,system=ours", "rate=8,system=vllm"}
    assert all(CELL_KEYS <= set(c) for c in cells.values())
    assert set(g["lenses"]) == {"tried", "confirmed", "revise", "rerun"}
    assert set(g["lenses"]["rerun"]) >= {"count", "gpu_h", "blocked", "conditional", "reused_cells", "reused_gpu_h", "items"}
    detail = client.get(f"{base}/nodes/exp.e2e").json()
    assert set(detail["runs"]) == set(cells) and detail["runs"]["rate=8,system=ours"][0]["footprint"] == sorted(
        ["bench/e2e.py", "src/lookahead/kv/cache.py", "src/lookahead/sched/budget.py", "src/lookahead/sched/policy.py"])
    assert {"id": "claim.ttft-2x", "edge": "evidence"} in detail["dependents"]
    assert client.get(f"{base}/nodes/design.sched/history").json()[0]["rev"] == 2
    assert client.get(f"{base}/nodes/nope").status_code == 404
    assert client.get(f"{base}/lenses").json()["confirmed"]["count"] == 2


def test_agent_cannot_lock_or_approve(dag):
    client, _, _, base = dag
    r = client.post(f"{base}/nodes/design.sched/lock", json={"reason": "freeze"})
    assert r.status_code == 403 and r.json()["detail"]["message"] == "open a proposal"
    r = client.post(f"{base}/ops", json={"ops": [{"op": "lock", "node": "design.sched", "reason": "x"}]}, headers=agent_headers())
    assert r.status_code == 403 and r.json()["detail"]["message"] == "open a proposal"
    r = client.post(f"{base}/ops", json={"ops": [{"op": "select_run", "node": "exp.e2e", "cell": "_", "run": "x"}]})
    assert r.status_code == 403
    prop = client.post(f"{base}/proposals", json={"title": "t", "ops": [{"op": "edit", "node": "mod.kv", "set": {"notes": "x"}}]}).json()
    assert client.post(f"{base}/proposals/{prop['id']}/approve", json={}).status_code == 403
    assert client.post(f"{base}/proposals/{prop['id']}/reject", json={"reason": "no"}).status_code == 403
    assert client.post(f"{base}/gates/G1/pass", json={}).status_code == 403
    assert client.post(f"{base}/runs/queue", json={"cells": [], "platform": "workstation", "confirm": True}).status_code == 400


def test_agent_direct_ops_and_proposals(dag):
    client, _, _, base = dag
    # an agent's own proposed node, and edits of active nodes, apply directly (the safe rule)
    r = client.post(f"{base}/ops", headers=agent_headers(), json={"ops": [
        {"op": "create", "node": {"id": "find.stall", "kind": "finding", "title": "Prefill stalls decode",
                                  "facets": {"statement": "Decode TPOT p99 rises when a long prefill is co-scheduled."}}}]})
    assert r.status_code == 200 and r.json()["applied"] is True
    g = client.get(f"{base}/graph").json()
    created = next(n for n in g["nodes"] if n["id"] == "find.stall")
    assert created["status"] == "proposed" and created["created"]["by"] == "agent:claude:46e445"
    r = client.post(f"{base}/ops", headers=agent_headers(), json={"ops": [{"op": "set_status", "node": "find.stall", "to": "active"}]})
    assert r.status_code == 200
    r = client.post(f"{base}/ops", json={"ops": [{"op": "edit", "node": "mod.kv", "set": {"globs": ["src/lookahead/kv/**", "src/x/**"]}}]})
    assert r.status_code == 200 and r.json()["applied"]
    # an agent edit of a confirmed node becomes one proposal (202)
    r = client.post(f"{base}/ops", headers=agent_headers(), json={"ops": [
        {"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt decode-starved requests."}}], "rationale": "cut p99"})
    assert r.status_code == 202
    prop = r.json()["proposal"]
    assert prop["state"] == "open" and prop["requires"] == [] and prop["impact"]["summary"]["rerun"] == 2
    assert client.get(f"{base}/graph").json()["nodes"][0]  # nothing applied
    design = next(n for n in client.get(f"{base}/graph").json()["nodes"] if n["id"] == "design.sched")
    assert design["facets"]["preemption"]["value"].startswith("None.")
    # agents may not confirm: a status change of anything but their own proposed node is a proposal
    r = client.post(f"{base}/ops", headers=agent_headers(), json={"ops": [{"op": "set_status", "node": "exp.kv-micro", "to": "confirmed"}]})
    assert r.status_code == 202
    # an op that cannot apply at all is refused with the reducer's reason
    r = client.post(f"{base}/ops", headers=agent_headers(), json={"ops": [{"op": "set_status", "node": "find.stall", "to": "confirmed"}]})
    assert r.status_code == 409 and "supports evidence" in r.json()["detail"]["message"]
    assert len(client.get(f"{base}/proposals", params={"state": "open"}).json()) == 2


def test_locked_edit_requires_unlock_and_approval_applies(dag):
    client, _, _, base = dag
    as_human(client)
    r = client.post(f"{base}/nodes/design.sched/lock", json={"reason": "design freeze"})
    assert r.status_code == 200 and r.json()["status"] == "locked" and r.json()["lock"]["by"].startswith("human:")
    tags = git(dag[2], "tag", "-l", "rd/lock/*")
    assert "rd/lock/design.sched/r3" in tags
    edit = {"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt decode-starved requests."}}
    r = client.post(f"{base}/ops", json={"ops": [edit]})
    assert r.status_code == 409 and r.json()["detail"]["requires"] == ["unlock:design.sched"]
    r = client.post(f"{base}/ops", headers=agent_headers(), json={"ops": [edit]})
    assert r.status_code == 202
    prop = r.json()["proposal"]
    assert prop["requires"] == ["unlock:design.sched"]
    assert prop["impact"]["lock"][0]["kind"] == "edit_locked"
    assert prop["impact"]["requires_human"]["value"] is True
    r = client.post(f"{base}/proposals/{prop['id']}/approve", json={})
    assert r.status_code == 200, r.text
    g = client.get(f"{base}/graph").json()
    design = next(n for n in g["nodes"] if n["id"] == "design.sched")
    assert design["status"] == "active" and design["facets"]["preemption"]["value"].startswith("Preempt")
    assert g["eval"]["mod.sched"]["level"] == "review"
    assert g["lenses"]["rerun"]["blocked"] == 2            # implement first
    ops = [h["op"] for h in client.get(f"{base}/nodes/design.sched/history").json()]
    assert ops[0] == "unlock+edit"
    decisions = [e for e in client.get(f"{base}/timeline").json() if e["op"] == "decision"]
    assert {d["kind"] for d in decisions} >= {"lock", "unlock"} and decisions[-1]["proposer"] == "agent:claude:46e445"
    assert client.get(f"{base}/proposals").json()[0]["state"] == "applied"


def test_stale_base_digest_needs_rebase(dag):
    client, _, root, base = dag
    as_human(client)
    prop = client.post(f"{base}/proposals", headers=agent_headers(), json={
        "title": "preempt", "ops": [{"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt."}}]}).json()
    assert prop["impact"]["summary"]["rerun"] == 2
    write(root, "bench/e2e.py", FILES["bench/e2e.py"] + "print('harness v2')\n")    # every e2e cell is now stale anyway
    commit(root, "harness")
    r = client.post(f"{base}/proposals/{prop['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["detail"]["message"] == "needs_rebase"
    assert r.json()["detail"]["impact"]["summary"]["rerun"] == 0
    assert client.get(f"{base}/proposals").json()[0]["state"] == "needs_rebase"
    r = client.post(f"{base}/proposals/{prop['id']}/approve", json={})             # approved against the new impact
    assert r.status_code == 200 and r.json()["proposal"]["state"] == "applied"
    # a stale digest on /ops is a conflict too
    r = client.post(f"{base}/ops", json={"ops": [{"op": "edit", "node": "mod.kv", "set": {"notes": "x"}}], "base_digest": "d:000000000000"})
    assert r.status_code == 409
    # base_vid mismatch
    r = client.post(f"{base}/ops", json={"ops": [{"op": "edit", "node": "mod.kv", "base_vid": "v-deadbeef", "set": {"globs": []}}]})
    assert r.status_code == 409


def test_reject_and_transitions(dag):
    client, _, _, base = dag
    as_human(client)
    prop = client.post(f"{base}/proposals", headers=agent_headers(), json={"title": "x", "ops": [
        {"op": "set_status", "node": "mod.kv", "to": "abandoned", "reason": "cost"}]}).json()
    r = client.post(f"{base}/proposals/{prop['id']}/reject", json={"reason": "we still need kv"})
    assert r.status_code == 200 and r.json()["state"] == "rejected" and r.json()["decided"]["reason"] == "we still need kv"
    # transition rules
    bad = client.post(f"{base}/ops", json={"ops": [{"op": "set_status", "node": "mod.kv", "to": "locked"}]})
    assert bad.status_code == 400
    r = client.post(f"{base}/ops", json={"ops": [{"op": "set_status", "node": "mod.kv", "to": "refuted"}]})
    assert r.status_code == 400                                     # refute needs a reason
    r = client.post(f"{base}/ops", json={"ops": [{"op": "set_status", "node": "exp.e2e", "to": "confirmed"}]})
    assert r.status_code == 200                                     # every cell fresh
    r = client.post(f"{base}/nodes/mod.kv/lock", json={"reason": "x"})
    assert r.status_code == 409                                     # only confirmed nodes lock
    r = client.post(f"{base}/ops", json={"ops": [{"op": "set_status", "node": "mod.kv", "to": "abandoned", "reason": "dominated"}]})
    assert r.status_code == 200
    g = client.get(f"{base}/graph").json()
    assert g["eval"]["mod.kv"]["archived"] is True and g["eval"]["mod.kv"]["level"] is None
    assert g["lenses"]["tried"]["dead"] == 1
    r = client.post(f"{base}/ops", json={"ops": [{"op": "set_status", "node": "mod.kv", "to": "active", "reason": "back"}]})
    assert r.status_code == 200


def test_runs_select_exclude_and_explain(dag):
    client, pid, root, base = dag
    as_human(client)
    rec = {"node": "exp.kv-micro", "cell": "_", "outputs": {"lat_us": {"value": 3.25}}, "gpu_hours": 0.2, "platform": "workstation",
           "trace": {"code:bench/micro_kv.py": client.get(f"{base}/runs", params={"node": "exp.kv-micro"}).json() and
                     {"fp": __import__("research_deck.dag.fp", fromlist=["fp_file"]).fp_file("bench/micro_kv.py", (root / "bench/micro_kv.py").read_bytes())}}}
    r = client.post(f"{base}/runs", json=rec)
    assert r.status_code == 200 and r.json()["cutoff"] == {"lat_us": True}
    runs = client.get(f"{base}/runs", params={"node": "exp.kv-micro"}).json()
    assert len(runs) == 2 and runs[0]["id"] == r.json()["run_id"]
    old = runs[1]["id"]
    c = client.post(f"{base}/cells/select", json={"node": "exp.kv-micro", "cell": "_", "run_id": old}).json()
    assert c["run"] == old and c["reused"] is True
    r = client.post(f"{base}/runs/{old}/exclude", json={"reason": "GPU throttled at 83C"})
    assert r.status_code == 200 and r.json()["excluded"]["reason"].startswith("GPU")
    g = client.get(f"{base}/graph").json()
    assert g["eval"]["exp.kv-micro"]["cells"]["_"]["run"] == runs[0]["id"]
    write(root, "src/lookahead/sched/policy.py", "def admit(slack):\n    return slack > 3\n")
    chains = client.get(f"{base}/nodes/exp.e2e/explain").json()
    ours = next(c for c in chains if c["cell"] == "rate=8,system=ours")
    assert ours["level"] == "stale" and "code:src/lookahead/sched/policy.py" in ours["text"] and "working tree" in ours["text"]
    plan = client.post(f"{base}/runs/plan", json={}).json()
    assert {(i["node"], i["cell"]) for w in plan["waves"] for i in w} == {("exp.e2e", "rate=4,system=ours"), ("exp.e2e", "rate=8,system=ours")}
    assert plan["gpu_h"] == pytest.approx(0.8) and plan["usd"] == pytest.approx(0.4)


def test_snapshots_gates_check_and_paper_sync(dag):
    client, _, root, base = dag
    as_human(client)
    snap = client.post(f"{base}/snapshots", json={"name": "milestone-1", "note": "before preemption"}).json()
    assert snap["nodes"]["design.sched"].startswith("v-") and snap["runs"]["exp.e2e/rate=8,system=ours"].startswith("r-")
    client.post(f"{base}/ops", json={"ops": [{"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt."}}]})
    past = client.get(f"{base}/graph", params={"at": "snap:milestone-1"}).json()
    design = next(n for n in past["nodes"] if n["id"] == "design.sched")
    assert past["at"] == "snap:milestone-1" and design["facets"]["preemption"]["value"].startswith("None.")
    assert past["eval"]["mod.sched"]["level"] == "fresh"
    prop = client.post(f"{base}/snapshots/milestone-1/restore").json()
    assert prop["ops"] == [{"op": "restore_snapshot", "name": "milestone-1"}]
    assert client.post(f"{base}/proposals/{prop['id']}/approve", json={}).status_code == 200
    g = client.get(f"{base}/graph").json()
    assert g["eval"]["mod.sched"]["level"] == "fresh"
    gates = client.get(f"{base}/gates").json()
    assert [x["gate"] for x in gates] == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert all({"label", "ok"} <= set(c) for x in gates for c in x["checks"])
    snap = client.post(f"{base}/gates/G6/pass", json={"note": "claims hold"}).json()
    assert snap["name"] == "gate-G6"
    g6 = next(x for x in client.get(f"{base}/gates").json() if x["gate"] == "G6")
    assert g6["passed"]["by"].startswith("human:")
    check = client.get(f"{base}/check").json()
    assert check["schema"] == [] and check["cycles"] == [] and check["dangling"] == [] and check["unsealed"] == []
    r = client.post(f"{base}/paper/sync").json()
    assert "sec.design" in r["sections"] and r["macros"] == 1
    macros = (root / "paper/generated/rdvalues.tex").read_text()
    assert "\\newcommand{\\rdTtftSpeedupMax}{2.2x}" in macros
    assert "sec.design → node:claim.ttft-2x" in r["edges_added"]
    claims = client.get(f"{base}/graph").json()["eval"]["sec.design"]
    assert claims["level"] == "fresh"
    from research_deck.dag import service
    pid = base.split("/")[3]
    docs = service.claims_for_doc(pid, "paper/design.tex")
    assert {d["id"] for d in docs} == {"sec.design", "claim.ttft-2x"}
    claim = next(d for d in docs if d["id"] == "claim.ttft-2x")
    assert claim["line"] == 3 and claim["freshness"] == "fresh" and claim["evidence"] == ["exp.e2e"]


def test_agent_attest_and_editorial(dag):
    client, _, _, base = dag
    as_human(client)
    client.post(f"{base}/ops", json={"ops": [{"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt."}}]})
    assert client.get(f"{base}/graph").json()["eval"]["mod.sched"]["level"] == "review"
    r = client.post(f"{base}/ops", headers=agent_headers(), json={"ops": [{"op": "attest", "node": "mod.sched"}]})
    assert r.status_code == 200 and r.json()["applied"]
    g = client.get(f"{base}/graph").json()
    assert g["eval"]["mod.sched"]["level"] == "fresh" and g["eval"]["sec.design"]["level"] == "review"
    # editorial: rewording auto-attests direct soft dependents, never demotes
    client.post(f"{base}/ops", json={"ops": [{"op": "set_status", "node": "design.sched", "to": "confirmed"}]})
    r = client.post(f"{base}/ops", json={"ops": [{"op": "edit", "node": "design.sched", "editorial": True,
                                                  "set": {"preemption": "Preempt decode when slack is negative."}}]})
    assert r.status_code == 200
    g = client.get(f"{base}/graph").json()
    design = next(n for n in g["nodes"] if n["id"] == "design.sched")
    assert design["status"] == "confirmed"
    assert g["eval"]["mod.sched"]["level"] == "fresh" and g["eval"]["fig.arch"]["level"] == "fresh"


def test_record_run_from_a_traced_cell_keeps_cells_fresh(dag):
    client, pid, root, base = dag
    from research_deck.dag import seed, service
    s = service.store_for(pid)
    out = service.record_run(pid, {"node": "exp.e2e", "cell": {"system": "ours", "rate": 4},
                                   "trace": seed.trace_for(s, "exp.e2e", {"system": "ours", "rate": 4}, reads=OURS_READS, cfg_keys=OURS_CFG),
                                   "outputs": {"ttft_p99": 119.0}, "experiment": "e-0031"})
    assert out["cutoff"]["ttft_p99"] is True
    f = service.experiment_freshness(pid, "exp.e2e", run_id=out["run_id"])
    assert f["freshness"] == "fresh" and f["cell"] == "rate=4,system=ours" and "bench/e2e.py" in f["footprint"]
    older = client.get(f"{base}/runs", params={"node": "exp.e2e", "cell": "rate=4,system=ours"}).json()[1]["id"]
    assert service.experiment_freshness(pid, "exp.e2e", run_id=older)["freshness"] == "reusable"
    write(root, "src/lookahead/sched/budget.py", "def budget(slack_ms):\n    return 0\n")
    assert service.experiment_freshness(pid, "exp.e2e", run_id=out["run_id"])["freshness"] == "stale"
    assert service.experiment_freshness(pid, "exp.e2e")["freshness"] == "stale"
