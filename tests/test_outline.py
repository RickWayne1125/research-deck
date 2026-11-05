"""The outline: sections and numbered items on the map, outline ops, forks, tasks and their states, phases, templates."""
import json

import pytest

from research_deck import config


def human(client):
    assert client.get("/api/session").status_code == 200


def base(pid):
    return f"/api/projects/{pid}"


def outline(client, pid):
    r = client.get(f"{base(pid)}/outline")
    assert r.status_code == 200, r.text
    return r.json()


def ops(client, pid, *items, status=200):
    r = client.post(f"{base(pid)}/outline/ops", json={"ops": list(items), "lang": "en"})
    assert r.status_code == status, r.text
    return r.json()


def flat(o):
    """num -> item over the whole outline (directions included, keyed num/d<k>)."""
    out = {}
    def walk(steps):
        for step in steps:
            for it in step["items"]:
                out[it["num"] if not it.get("direction") else f"{it['num']}/d{it['direction']}"] = it
                walk(it["children"])
                for d in (it.get("fork") or {}).get("directions") or []:
                    out[f"{d['num']}/d{d['direction']}"] = d
                    walk(d["children"])
    for s in o["sections"]:
        walk(s["items"])
    return out


STRUCTURE = {"sections": [
    {"key": "intro", "items": [{"text": "Experts wait for transfers."}]},
    {"key": "motivation", "items": [
        {"text": "On-demand loading waits 58% of the time."},
        [{"text": "Layer-wise prediction hits 61%."}, {"text": "Adjacent tokens share experts."}],
        {"text": "So the queue tells which experts come next."}], "notes": {"1": "two measurements"}},
    {"key": "design", "items": [
        {"text": "The predictor reads the router scores of the queued tokens.",
         "children": [{"text": "Scores are known when a token enters the queue."}, {"text": "k = 4-8 covers 90%."}]},
        {"text": "Prefetch during compute."}]},
]}


@pytest.fixture
def made(client, project):
    human(client)
    pid, root = project
    r = client.post(f"{base(pid)}/outline/init", json={"template": "systems", "lang": "en", "structure": STRUCTURE})
    assert r.status_code == 200, r.text
    return pid, root


def test_init_from_a_template_with_a_draft(client, made):
    pid, root = made
    o = outline(client, pid)
    assert o["has_outline"] and o["template"] == "systems"
    assert [(s["num"], s["id"], s["phase"]) for s in o["sections"]][:3] == [("1", "sec.intro", "summary"),
                                                                            ("2", "sec.motivation", "insight"), ("3", "sec.design", "design")]
    assert len(o["sections"]) == 7
    f = flat(o)
    assert f["2.1"]["text"].startswith("On-demand") and f["2.2"]["text"].startswith("Layer-wise")
    assert f["2.3"]["text"].startswith("Adjacent") and f["2.4"]["text"].startswith("So the queue")
    motivation = o["sections"][1]["items"]
    assert [len(s["items"]) for s in motivation] == [1, 2, 1] and motivation[1]["note"] == "two measurements"
    assert f["3.1.1"]["text"].startswith("Scores") and f["3.1.2"]["text"].startswith("k = 4-8")
    assert all(it["state"] == "needs_tasks" for it in f.values())
    assert json.loads((root / ".research/outline/meta.json").read_text())["template"] == "systems"
    # one outline per project
    r = client.post(f"{base(pid)}/outline/init", json={"template": "ml"})
    assert r.status_code == 409


def test_items_move_indent_join_and_go(client, made):
    pid, _ = made
    f = flat(outline(client, pid))
    a, b, c = f["2.1"]["id"], f["2.2"]["id"], f["2.4"]["id"]
    r = ops(client, pid, {"op": "add_item", "parent": "sec.motivation", "text": "A new first item.", "at": {"first": True}})
    new = r["last"]
    f = flat(outline(client, pid))
    assert f["2.1"]["id"] == new and f["2.2"]["id"] == a
    ops(client, pid, {"op": "move_item", "item": new, "how": "down"})
    assert flat(outline(client, pid))["2.2"]["id"] == new
    ops(client, pid, {"op": "move_item", "item": new, "how": "indent"})
    f = flat(outline(client, pid))
    assert f["2.1.1"]["id"] == new and f["2.2"]["id"] == b
    ops(client, pid, {"op": "move_item", "item": new, "how": "outdent"})
    assert flat(outline(client, pid))["2.2"]["id"] == new
    ops(client, pid, {"op": "move_item", "item": c, "how": "join"})
    steps = outline(client, pid)["sections"][1]["items"]
    assert [i["id"] for i in steps[-1]["items"]][-1] == c and len(steps[-1]["items"]) == 3
    ops(client, pid, {"op": "move_item", "item": c, "how": "split"})
    assert outline(client, pid)["sections"][1]["items"][-1]["items"][0]["id"] == c
    ops(client, pid, {"op": "edit_item", "item": c, "text": "Therefore the queue predicts experts."})
    ops(client, pid, {"op": "remove_item", "item": new})
    o = outline(client, pid)
    assert new not in {it["id"] for it in flat(o).values()} and flat(o)["2.4"]["text"].startswith("Therefore")
    node = client.get(f"{base(pid)}/dag/nodes/{new}").json()
    assert node.get("node", node)["status"] == "abandoned"          # kept, with its history
    ops(client, pid, {"op": "move_item", "item": a, "how": "outdent"}, status=409)


def test_sections_add_edit_move_remove(client, made):
    pid, _ = made
    ops(client, pid, {"op": "add_section", "title": "Discussion", "phase": "evaluation", "after": "sec.evaluation", "key": "discussion"})
    o = outline(client, pid)
    ids = [s["id"] for s in o["sections"]]
    assert ids.index("sec.discussion") == ids.index("sec.evaluation") + 1
    ops(client, pid, {"op": "edit_section", "section": "sec.discussion", "title": "Limitations", "role": "What it cannot do", "phase": "summary"})
    ops(client, pid, {"op": "move_section", "section": "sec.discussion", "to": 0})
    s0 = outline(client, pid)["sections"][0]
    assert s0["id"] == "sec.discussion" and s0["title"]["en"] == "Limitations" and s0["phase"] == "summary" and s0["num"] == "1"
    ops(client, pid, {"op": "remove_section", "section": "sec.discussion"})
    assert "sec.discussion" not in [s["id"] for s in outline(client, pid)["sections"]]
    ops(client, pid, {"op": "add_section", "title": "X", "phase": "nonsense"}, status=400)


def test_forks_directions_and_the_choice(client, made):
    pid, _ = made
    f = flat(outline(client, pid))
    item = f["3.1"]["id"]
    t = client.post(f"{base(pid)}/tasks", json={"type": "code", "title": "Predictor", "items": [item]}).json()
    r = ops(client, pid, {"op": "fork", "item": item, "question": "How does the predictor pick experts?",
                          "directions": ["Router scores of queued tokens", "A small learned model"]})
    d1, d2 = r["created"]
    o = outline(client, pid)
    f = flat(o)
    assert f["3.1"]["text"].startswith("How does") and f["3.1"]["state"] == "choose"
    assert f["3.1/d1"]["id"] == d1 and f["3.1.1"]["text"].startswith("Scores")           # the sub-items moved to direction 1
    assert {p["kind"] for p in o["pending"]} >= {"fork"}
    assert client.get(f"{base(pid)}/tasks").json()[0]["items"] == [d1]                   # and so did the task
    ops(client, pid, {"op": "add_direction", "item": item, "text": "Layer-wise prediction with a cache"})
    ops(client, pid, {"op": "choose_direction", "item": item, "direction": d1})
    f = flat(outline(client, pid))
    assert f["3.1/d2"]["state"] == "abandoned" and f["3.1/d3"]["state"] == "abandoned"
    assert f["3.1"]["state"] == f["3.1/d1"]["state"] == "todo"
    client.patch(f"{base(pid)}/tasks/{t['id']}", json={"status": "done"})
    f = flat(outline(client, pid))
    assert f["3.1/d1"]["state"] == "doing"                                                 # its sub-items do not hold yet
    ops(client, pid, {"op": "choose_direction", "item": item, "direction": d2}, status=409)   # abandoned


def test_an_abandoned_direction_keeps_its_reason_and_note(client, made):
    pid, _ = made
    item = flat(outline(client, pid))["3.1"]["id"]
    d1, d2 = ops(client, pid, {"op": "fork", "item": item, "directions": ["Router scores", "A learned model"]})["created"]
    # abandoning one direction and choosing another in one batch abandons it once
    ops(client, pid, {"op": "abandon_direction", "item": item, "direction": d2, "reason": "infeasible", "note": "74% accurate, needs 90%"},
        {"op": "choose_direction", "item": item, "direction": d1})
    d = flat(outline(client, pid))["3.1/d2"]
    assert d["state"] == "abandoned" and d["why"] == "74% accurate, needs 90%" and d["why_kind"] == "infeasible" and d["ended_at"]


def test_task_states_roll_up(client, made):
    pid, _ = made
    f = flat(outline(client, pid))
    a, b = f["2.1"]["id"], f["2.2"]["id"]
    exp = client.post(f"{base(pid)}/tasks", json={"type": "exp", "title": "Baseline", "items": [a, b]}).json()
    lit = client.post(f"{base(pid)}/tasks", json={"type": "lit", "title": "Prior work", "items": [b]}).json()
    f = flat(outline(client, pid))
    assert f["2.1"]["state"] == "todo" and f["2.1"]["tasks"] == [exp["id"]]
    client.patch(f"{base(pid)}/tasks/{exp['id']}", json={"status": "doing"})
    client.patch(f"{base(pid)}/tasks/{lit['id']}", json={"status": "blocked", "note": "paywalled"})
    o = outline(client, pid)
    f = flat(o)
    assert f["2.1"]["state"] == "doing" and f["2.2"]["state"] == "blocked"
    assert o["counts"]["doing"] == 1 and o["counts"]["blocked"] == 1 and o["counts"]["total"] == 2
    assert any(p["kind"] == "blocked_task" and p["note"] == "paywalled" for p in o["pending"])
    for t in (exp, lit):
        client.patch(f"{base(pid)}/tasks/{t['id']}", json={"status": "done"})
    ops(client, pid, {"op": "edit_item", "item": f["2.3"]["id"], "derived": True})
    f = flat(outline(client, pid))
    assert f["2.1"]["state"] == f["2.2"]["state"] == f["2.3"]["state"] == "holds"
    group = next(g for g in outline(client, pid)["groups"] if g["phase"] == "insight")
    assert group["holds"] == 3 and group["missing"] == ["2.4"]
    # an agent suggests a task; it does not count until the researcher takes it
    from fastapi.testclient import TestClient
    from research_deck.app import create_app
    with TestClient(create_app(), headers={"X-RD-Request": "1"}) as agent:
        s = agent.post(f"{base(pid)}/tasks", json={"type": "exp", "title": "Queue lead time", "items": [f["2.4"]["id"]]}).json()
        assert s["status"] == "sugg"
        assert agent.patch(f"{base(pid)}/tasks/{s['id']}", json={"status": "done"}).status_code == 403
    o = outline(client, pid)
    assert o["counts"]["suggested"] == 1 and flat(o)["2.4"]["suggested"] == [s["id"]] and flat(o)["2.4"]["state"] == "needs_tasks"


def test_tasks_of_a_later_phase_wait(client, made):
    pid, _ = made
    config.SETTINGS_FILE.write_text(json.dumps({"dag_defaults": {"stages": {"mode": "strict"}}}))
    config._SETTINGS_CACHE = (-1.0, {})
    f = flat(outline(client, pid))
    t = client.post(f"{base(pid)}/tasks", json={"type": "code", "title": "Prefetcher", "items": [f["3.2"]["id"]]}).json()
    o = outline(client, pid)
    task = next(x for x in o["tasks"] if x["id"] == t["id"])
    assert task["phase"] == "design" and task["status"] == "locked" and flat(o)["3.2"]["state"] == "locked"
    client.patch(f"{base(pid)}/config", json={"stage": "design"})
    assert next(x for x in outline(client, pid)["tasks"] if x["id"] == t["id"])["status"] == "todo"
    # items and sections are the story: they can be written in any phase under the stage rules
    ops(client, pid, {"op": "add_item", "parent": "sec.evaluation", "text": "Two times faster end to end."})


def test_experiment_tasks_follow_their_runs(client, made):
    pid, root = made
    from research_deck.dag import seed
    s = seed.store(root)
    seed.add(s, "exp.base", "experiment", purpose="reproduce", title="Baseline",
             facets={"spec": {"type": "json", "value": {"command": "true", "platform": "workstation", "gpus": 1, "est_hours": 0.1}},
                     "outputs": {"type": "json", "value": {"wait": {"from": "out.csv.wait"}}}})
    f = flat(outline(client, pid))
    t = client.post(f"{base(pid)}/tasks", json={"type": "exp", "title": "Baseline", "items": [f["2.1"]["id"]],
                                                "links": {"node": "exp.base"}}).json()
    assert next(x for x in outline(client, pid)["tasks"] if x["id"] == t["id"])["status"] == "todo"
    seed.record(s, "exp.base", {}, reads=[], cfg_keys=[], outputs={"wait": 0.58}, gpu_hours=0.1)
    o = outline(client, pid)
    task = next(x for x in o["tasks"] if x["id"] == t["id"])
    assert task["status"] == "done" and task["reason"] is None and flat(o)["2.1"]["state"] == "holds"
    # what the task produces shows as the item's evidence (once, and not as an edge to remove)
    assert [(e["id"], e["rel"], e.get("task")) for e in flat(o)["2.1"]["evidence"]] == [("exp.base", "task", t["id"])]


def test_a_pdf_outline_is_read_for_the_box(client, project):
    import base64
    pid, _ = project
    human(client)
    url = f"{base(pid)}/outline/extract"
    assert client.post(url, json={"name": "outline.md", "content_base64": ""}).status_code == 400      # the page reads text itself
    bad = base64.b64encode(b"not a pdf").decode()
    assert client.post(url, json={"name": "outline.pdf", "content_base64": bad}).status_code == 400
    assert client.post(url, json={"name": "outline.pdf", "content_base64": "%%%"}).status_code == 400


def test_summary_items_follow_the_body(client, made):
    pid, _ = made
    f = flat(outline(client, pid))
    intro, body = f["1.1"]["id"], f["2.1"]["id"]
    ops(client, pid, {"op": "edit_item", "item": intro, "summary_of": [body]})
    assert flat(outline(client, pid))["1.1"]["state"] == "pending"
    ops(client, pid, {"op": "edit_item", "item": body, "derived": True})
    assert flat(outline(client, pid))["1.1"]["state"] == "holds"


def test_agents_propose_and_loose_results_show(client, made):
    pid, root = made
    from fastapi.testclient import TestClient
    from research_deck.app import create_app
    f = flat(outline(client, pid))
    with TestClient(create_app(), headers={"X-RD-Request": "1"}) as agent:
        r = agent.post(f"{base(pid)}/outline/ops", json={"ops": [{"op": "add_item", "parent": "sec.motivation", "text": "Tokens wait 4 steps."}]})
        assert r.status_code == 200, r.text
        new = r.json()["created"][0]
        r = agent.post(f"{base(pid)}/outline/ops", json={"ops": [{"op": "edit_item", "item": f["2.1"]["id"], "text": "Rewritten by an agent."}]})
        assert r.status_code == 200 and r.json()["applied"] is False and r.json()["proposal"]
        assert agent.post(f"{base(pid)}/outline/init", json={"template": "ml"}).status_code == 403
    o = outline(client, pid)
    assert flat(o)["2.5"]["id"] == new and flat(o)["2.5"]["state"] == "proposed"
    assert {p["kind"] for p in o["pending"]} >= {"proposed_item", "proposal"}
    assert flat(o)["2.1"]["proposals"]                                                # the open edit is shown on the item
    from research_deck.dag import seed
    s = seed.store(root)
    seed.add(s, "exp.extra", "experiment", purpose="profile", title="A sweep nobody cites",
             facets={"spec": {"type": "json", "value": {"command": "true", "platform": "workstation", "gpus": 1, "est_hours": 0.1}},
                     "outputs": {"type": "json", "value": {"x": {"from": "out.csv.x"}}}})
    assert outline(client, pid)["loose"] == []                                         # not run yet: not a result
    seed.record(s, "exp.extra", {}, reads=[], cfg_keys=[], outputs={"x": 1.0}, gpu_hours=0.1)
    assert [x["id"] for x in outline(client, pid)["loose"]] == ["exp.extra"]


def test_templates_and_the_structured_draft(client, project):
    human(client)
    pid, _ = project
    ids = [t["id"] for t in client.get("/api/outline/templates").json()]
    assert {"systems", "ml", "workshop"} <= set(ids)
    mine = {"name": "Mine", "phases": {"design": "Method"},
            "sections": [{"key": "intro", "title": "Intro", "phase": "summary"}, {"key": "method", "title": "Method", "phase": "design", "tasks": ["code", "bogus"]}]}
    r = client.put("/api/outline/templates/mine", json=mine)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["builtin"] is False and t["sections"][1]["tasks"] == ["code"] and t["phases"]["design"]["en"] == "Method"
    assert client.put("/api/outline/templates/bad", json={"sections": [{"key": "x", "title": "X", "phase": "nope"}]}).status_code == 400
    assert (config.LOCAL_DIR / "templates" / "mine.yaml").exists()
    text = "1 Introduction\n- Experts wait.\n2 Background and Motivation\n- 58% waiting\n  - measured on Mixtral\n"
    d = client.post(f"{base(pid)}/outline/structure", json={"text": text, "template": "systems", "agent": False}).json()
    assert d["by"] == "parse" and [s["key"] for s in d["sections"]] == ["intro", "motivation"]
    assert d["sections"][1]["items"][0]["children"][0]["text"] == "measured on Mixtral"
    d = client.post(f"{base(pid)}/outline/structure", json={"text": text, "template": "systems"}).json()
    assert d["by"] == "agent" and d["changes"]
    r = client.post(f"{base(pid)}/outline/init", json={"template": "mine", "structure": d})
    assert r.status_code == 200, r.text
    o = outline(client, pid)
    # a draft section the template does not have goes after the one before it in the draft
    assert [s["id"] for s in o["sections"]] == ["sec.intro", "sec.background-and-motivation", "sec.method"]
    assert o["phases"]["design"]["en"] == "Method" and flat(o)["2.1.1"]["text"] == "measured on Mixtral"
    r = client.post(f"{base(pid)}/outline/save-template", json={"id": "from-project", "name": "From the project"})
    assert r.status_code == 200 and [s["key"] for s in r.json()["sections"]] == ["intro", "background-and-motivation", "method"]
    assert client.delete("/api/outline/templates/systems").status_code == 404
    assert client.delete("/api/outline/templates/mine").json() == {"ok": True}


def test_paper_sync_sections_are_adopted(client, project):
    human(client)
    pid, root = project
    from research_deck.dag import seed
    s = seed.store(root)
    seed.add(s, "sec.motivation", "section", stage="W", title="motivation", facets={"file": {"type": "json", "value": "paper/main.tex"}})
    r = client.post(f"{base(pid)}/outline/init", json={"template": "systems"})
    assert r.status_code == 200, r.text
    ids = [s["id"] for s in outline(client, pid)["sections"]]
    assert "sec.motivation" in ids and "sec.motivation-2" not in ids
