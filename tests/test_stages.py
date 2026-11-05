"""Stage-by-stage progression (dag/stages.py, docs/DAG.md §1.1): a step is drafted once the project reaches it, on
confirmed nodes of the steps before; a failed node grows no new branch; G1/G2 split."""
import json

import pytest

from research_deck import config


def dag(pid):
    return f"/api/projects/{pid}/dag"


def human(client):
    assert client.get("/api/session").status_code == 200


def mode(m):
    config.SETTINGS_FILE.write_text(json.dumps({"dag_defaults": {"stages": {"mode": m}}}))
    config._SETTINGS_CACHE = (-1.0, {})


def ops(client, pid, *items):
    return client.post(f"{dag(pid)}/ops", json={"ops": list(items)})


def create(nid, kind, *, status="active", edges=(), **extra):
    return {"op": "create", "node": {"id": nid, "kind": kind, "status": status, "title": nid, "edges": list(edges), **extra}}


def status(nid, to, reason=None):
    return {"op": "set_status", "node": nid, "to": to, **({"reason": reason} if reason else {})}


def basis(nid, facet="statement"):
    return {"type": "basis", "to": f"node:{nid}#{facet}"}


def stage(client, pid, s):
    r = client.patch(f"/api/projects/{pid}/config", json={"stage": s})
    assert r.status_code == 200, r.text


def detail(r):
    d = r.json()["detail"]
    return d if isinstance(d, dict) else {"message": d}


def test_strict_drafts_one_step_at_a_time(client, project):
    mode("strict")
    human(client)
    pid, _ = project
    prob = create("prob.p", "problem", facets={"statement": "The problem."})
    assert ops(client, pid, prob, create("ref.r", "reference")).status_code == 200
    # a finding belongs to Motivation & insight, which has not started
    r = ops(client, pid, create("find.f", "finding", edges=[basis("prob.p")]))
    assert r.status_code == 409 and detail(r)["reason"] == "stage_locked" and detail(r)["step"] == "insight"
    stage(client, pid, "motivation")
    # the step has started, but the problem it rests on is not confirmed yet
    r = ops(client, pid, create("find.f", "finding", edges=[basis("prob.p")]))
    assert r.status_code == 409 and detail(r)["reason"] == "unconfirmed_parent" and detail(r)["node"] == "prob.p"
    assert ops(client, pid, status("prob.p", "confirmed", "framed")).status_code == 200
    assert ops(client, pid, create("find.f", "finding", edges=[basis("prob.p")])).status_code == 200
    # concurrent nodes in the same step need no confirmation of each other
    assert ops(client, pid, create("gap.g", "gap", edges=[basis("find.f"), basis("prob.p")])).status_code == 200
    # editing a node into a later step is refused the same way
    r = ops(client, pid, {"op": "edit", "node": "gap.g", "stage": "S5"})
    assert r.status_code == 409 and detail(r)["reason"] == "stage_locked"


def test_a_failed_node_grows_no_branch(client, project):
    mode("strict")
    human(client)
    pid, _ = project
    assert ops(client, pid, create("prob.p", "problem", facets={"statement": "x"}),
               status("prob.p", "confirmed", "ok")).status_code == 200
    stage(client, pid, "motivation")
    assert ops(client, pid, create("find.a", "finding", edges=[basis("prob.p")]),
               create("find.b", "finding", edges=[basis("prob.p")])).status_code == 200
    assert ops(client, pid, status("find.a", "abandoned", "no_headroom")).status_code == 200
    for edge in (basis("find.a"), {"type": "cites", "to": "node:find.a"}):
        r = ops(client, pid, create("gap.g", "gap", edges=[edge]))
        assert r.status_code == 409 and detail(r)["reason"] == "dead_parent" and detail(r)["node"] == "find.a"
    r = ops(client, pid, {"op": "link", "node": "find.b", "edge": basis("find.a")})
    assert r.status_code == 409 and detail(r)["reason"] == "dead_parent"
    # its concurrent sibling goes on
    assert ops(client, pid, create("gap.g", "gap", edges=[basis("find.b")])).status_code == 200


def test_ahead_drafts_later_steps_but_keeps_them_waiting(client, project):
    mode("ahead")
    human(client)
    pid, _ = project
    assert ops(client, pid, create("prob.p", "problem", facets={"statement": "x"})).status_code == 200
    # a later-step draft is allowed, as a proposal, even on an unconfirmed parent …
    assert ops(client, pid, create("design.d", "design", status="proposed", edges=[basis("prob.p")])).status_code == 200
    # … but it cannot take effect before its step starts
    r = ops(client, pid, status("design.d", "active"))
    assert r.status_code == 409 and detail(r)["reason"] == "stage_locked" and detail(r)["step"] == "design"
    stage(client, pid, "design")
    r = ops(client, pid, status("design.d", "active"))
    assert r.status_code == 409 and detail(r)["reason"] == "unconfirmed_parent"
    assert ops(client, pid, status("prob.p", "confirmed", "ok"), status("design.d", "active")).status_code == 200
    # a dead parent is refused in this mode too
    assert ops(client, pid, status("design.d", "abandoned", "cost")).status_code == 200
    r = ops(client, pid, create("mod.m", "module", status="proposed", edges=[basis("design.d", "interface")]))
    assert r.status_code == 409 and detail(r)["reason"] == "dead_parent"


def test_free_mode_has_no_stage_rules(client, project):
    mode("free")
    human(client)
    pid, _ = project
    assert ops(client, pid, create("prob.p", "problem", facets={"statement": "x"}),
               create("design.d", "design", edges=[basis("prob.p")]),
               status("prob.p", "abandoned", "cost"),
               create("mod.m", "module", edges=[basis("prob.p")])).status_code == 200


def test_the_project_config_overrides_the_user_default(client, project):
    mode("strict")
    human(client)
    pid, root = project
    from research_deck.dag.service import store_for
    store_for(pid).ensure()
    (root / ".research/dag/config.yaml").write_text("stages: {mode: free}\n")
    assert ops(client, pid, create("design.d", "design")).status_code == 200


@pytest.mark.parametrize("s, step", [("idea", 0), ("motivation", 1), ("insight", 1), ("design", 2), ("evaluation", 3),
                                     ("writing", 3), ("nonsense", 0)])
def test_project_steps(client, project, s, step):
    from research_deck.dag import stages
    from research_deck.dag.service import store_for
    pid, _ = project
    stage(client, pid, s)
    assert stages.project_step(store_for(pid)) == step


def test_g1_is_the_survey_and_g2_holds_the_baselines(client, project):
    mode("free")
    human(client)
    pid, _ = project
    gates = {g["gate"]: g for g in client.get(f"{dag(pid)}/gates").json()}
    assert [c["key"] for c in gates["G1"]["checks"]] == ["problem_confirmed", "references", "competitors"]
    assert [c["key"] for c in gates["G2"]["checks"]][0] == "baselines_reproduced"
