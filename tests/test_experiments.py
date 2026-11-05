"""Experiment records: create / list / get / patch, logs paging, freshness from the DAG service, demo resources.

Uses the shared fixtures (isolated registry, fake agent). The DAG service is replaced by a small fake through
records._dag_service, so these tests do not depend on the DAG slice.
"""
from __future__ import annotations

import json

import pytest

from research_deck.experiments import records


@pytest.fixture
def published(monkeypatch):
    events = []
    monkeypatch.setattr(records.hub, "publish", lambda pid, topic, payload=None: events.append((pid, topic, payload)))
    return events


def url(pid: str, rest: str = "") -> str:
    return f"/api/projects/{pid}/experiments{rest}"


def create(client, pid, **body):
    body = {"title": "E7 main", "node_id": "exp.e7", "config": {"lr": 0.001},
            "target": {"platform": "workstation", "node": "WORKSTATION", "gpus": 1, "gpu_type": "GPU-24GB"},
            "command": "python -m toycache.bench --config e7.yaml", **body}
    r = client.post(url(pid), json=body)
    assert r.status_code == 200, r.text
    return r.json()


class FakeDag:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls = []

    def experiment_freshness(self, pid, node_id, run_id=None, cell=None):
        self.calls.append((node_id, run_id, cell))
        return self.answers.get(node_id, {"freshness": "unknown", "reasons": [], "footprint": []})


# ------------------------------------------------------------------ records

def test_create_writes_a_planned_record_without_derived_fields(client, project, published):
    pid, root = project
    e = create(client, pid)
    assert e["status"] == "planned"
    assert e["id"].startswith("e7-main-")
    assert e["freshness"] == "unknown" and e["stale_reasons"] == []
    assert e["target"] == {"platform": "workstation", "node": "WORKSTATION", "gpus": 1, "gpu_type": "GPU-24GB"}
    assert e["created"]["by"] == "agent:unknown"          # no browser cookie in the test client
    on_disk = json.loads((root / ".research" / "experiments" / f"{e['id']}.json").read_text())
    assert list(on_disk)[:5] == ["id", "node_id", "cell", "title", "status"]
    assert not {"freshness", "stale_reasons", "logs_tail"} & set(on_disk)
    assert published == [(pid, "experiments", {"id": e["id"], "change": "created", "status": "planned"})]


def test_create_with_an_explicit_id_and_conflicts(client, project):
    pid, _ = project
    assert create(client, pid, id="e7-main")["id"] == "e7-main"
    r = client.post(url(pid), json={"title": "again", "id": "e7-main"})
    assert r.status_code == 409
    for bad in ("../escape", "a/b", ".hidden", ""):
        assert client.post(url(pid), json={"title": "x", "id": bad}).status_code == 422, bad
    assert client.post(url(pid), json={"title": "x", "freshness": "fresh"}).status_code == 422   # unknown field


def test_a_chinese_title_names_the_record_after_its_node(client, project):
    pid, _ = project
    assert create(client, pid, title="消融：关闭预取", node_id="exp.ablation-chunk")["id"].startswith("ablation-chunk-")
    assert create(client, pid, title="消融", node_id=None)["id"].startswith("exp-")


def test_list_is_newest_first_and_skips_broken_files(client, project):
    pid, root = project
    old = create(client, pid, title="old")
    client.patch(url(pid, f"/{old['id']}"), json={"started_at": "2026-10-01T10:00:00Z"})
    new = create(client, pid, title="new")
    client.patch(url(pid, f"/{new['id']}"), json={"started_at": "2026-11-01T10:00:00Z"})
    (root / ".research" / "experiments" / "broken.json").write_text("{not json")
    (root / ".research" / "experiments" / "hand.json").write_text(json.dumps({"title": "by hand", "status": "weird"}))
    items = client.get(url(pid)).json()
    assert [i["id"] for i in items][:2] == [new["id"], old["id"]]
    hand = next(i for i in items if i["id"] == "hand")
    assert hand["status"] == "unknown" and hand["target"]["gpus"] == 0 and hand["code"]["footprint"] == []
    assert client.get(url(pid, "/missing")).status_code == 404
    assert client.get(url(pid, "/..%2Fproject")).status_code == 404


def test_patch_merges_target_and_code_and_follows_status(client, project, published):
    pid, _ = project
    e = create(client, pid, code={"commit": "abc1234", "footprint": ["src/a.py"]})
    r = client.patch(url(pid, f"/{e['id']}"), json={"status": "running", "target": {"gpus": 2}, "progress": 0.25,
                                                     "freshness": "fresh", "stale_reasons": ["ignored"], "id": "ignored"})
    assert r.status_code == 200, r.text
    e2 = r.json()
    assert e2["id"] == e["id"] and e2["started_at"] and e2["finished_at"] is None
    assert e2["target"] == {"platform": "workstation", "node": "WORKSTATION", "gpus": 2, "gpu_type": "GPU-24GB"}
    assert e2["freshness"] == "unknown"                    # derived fields are never taken from a patch
    e3 = client.patch(url(pid, f"/{e['id']}"), json={"status": "succeeded", "metrics": {"throughput_tok_s": 1834, "note": "ok"},
                                                    "code": {"footprint": ["src/a.py", "src/b.py"]}}).json()
    assert e3["finished_at"] and e3["progress"] == 1.0
    assert e3["code"] == {"commit": "abc1234", "footprint": ["src/a.py", "src/b.py"]}
    assert e3["metrics"] == {"throughput_tok_s": 1834, "note": "ok"}
    assert e3["updated"]["by"] == "agent:unknown"
    assert published[-1][2]["change"] == "updated" and "metrics" in published[-1][2]["fields"]


@pytest.mark.parametrize("body", [{"status": "exploded"}, {"progress": 2}, {"started_at": "yesterday"}, {"bogus": 1},
                                  {"target": {"gpus": -1}}, {"metrics": {"x": [1, 2]}}])
def test_patch_rejects_invalid_input(client, project, body):
    pid, _ = project
    e = create(client, pid)
    assert client.patch(url(pid, f"/{e['id']}"), json=body).status_code == 422


def test_paths_from_requests_stay_inside_the_project(client, project):
    pid, _ = project
    e = create(client, pid)
    assert client.patch(url(pid, f"/{e['id']}"), json={"logs": "../../etc/passwd"}).status_code == 400
    assert client.patch(url(pid, f"/{e['id']}"), json={"logs": "/etc/passwd"}).json()["logs"] == "/etc/passwd"  # read as project-relative
    page = client.get(url(pid, f"/{e['id']}/logs")).json()
    assert page["lines"] == [] and page.get("missing") is True


# ------------------------------------------------------------------ freshness from the DAG

def test_freshness_comes_from_the_dag_service(client, project, monkeypatch):
    pid, _ = project
    fake = FakeDag({
        "exp.e7": {"freshness": "stale", "level": "stale", "cell": "rate=8,system=ours",
                   "reasons": ["code:src/toycache/prefetch.py changed p:41ac → p:d07e",
                               {"level": "stale", "addr": "cfg:sched.chunk.max", "from": "2048", "to": "4096"}],
                   "footprint": ["src/toycache/prefetch.py", "bench/e2e.py"]},
        "exp.kv": {"freshness": "fresh", "level": "fresh", "reasons": [], "footprint": []},
        "exp.bad": {"freshness": "sideways"},
    })
    monkeypatch.setattr(records, "_dag_service", lambda: fake)
    stale = create(client, pid, code={"commit": "abc", "footprint": ["src/declared.py"]})
    fresh = create(client, pid, title="kv", node_id="exp.kv", code={"commit": None, "footprint": ["src/kv.py"]})
    odd = create(client, pid, title="odd", node_id="exp.bad")
    none = create(client, pid, title="no node", node_id=None)
    client.patch(url(pid, f"/{stale['id']}"), json={"run_id": "r-1", "cell": "rate=8,system=ours"})
    by_id = {e["id"]: e for e in client.get(url(pid)).json()}
    s = by_id[stale["id"]]
    assert s["freshness"] == "stale" and s["dag_level"] == "stale"
    assert s["stale_reasons"] == ["code:src/toycache/prefetch.py changed p:41ac → p:d07e", "cfg:sched.chunk.max changed (2048 → 4096)"]
    assert s["code"]["footprint"] == ["src/toycache/prefetch.py", "bench/e2e.py"]
    assert s["code"]["footprint_source"] == "trace" and s["code"]["declared_footprint"] == ["src/declared.py"]
    assert ("exp.e7", "r-1", "rate=8,system=ours") in fake.calls
    assert by_id[fresh["id"]]["freshness"] == "fresh" and by_id[fresh["id"]]["code"]["footprint"] == ["src/kv.py"]
    assert by_id[odd["id"]]["freshness"] == "unknown"
    assert by_id[none["id"]]["freshness"] == "unknown"


def test_freshness_is_unknown_when_the_dag_fails(client, project, monkeypatch):
    pid, _ = project

    class Broken:
        def experiment_freshness(self, *a, **k):
            raise RuntimeError("evaluation failed")
    monkeypatch.setattr(records, "_dag_service", lambda: Broken())
    assert create(client, pid)["freshness"] == "unknown"
    monkeypatch.setattr(records, "_dag_service", lambda: None)
    assert client.get(url(pid)).json()[0]["freshness"] == "unknown"


# ------------------------------------------------------------------ logs

def test_logs_page_by_byte_offset_and_tail(client, project):
    pid, root = project
    e = create(client, pid)
    log = root / "experiments" / "logs" / "e7.log"
    log.parent.mkdir(parents=True)
    log.write_text("".join(f"step {i}\n" for i in range(5)))
    client.patch(url(pid, f"/{e['id']}"), json={"logs": "experiments/logs/e7.log", "status": "succeeded"})
    first = client.get(url(pid, f"/{e['id']}/logs")).json()
    assert first["lines"] == [f"step {i}" for i in range(5)] and first["eof"] and first["source"] == "file"
    assert first["next"] == log.stat().st_size
    with log.open("a") as f:
        f.write("step 5\n")
    more = client.get(url(pid, f"/{e['id']}/logs"), params={"offset": first["next"]}).json()
    assert more["lines"] == ["step 5"]
    tail = client.get(url(pid, f"/{e['id']}/logs"), params={"offset": -1}).json()
    assert tail["lines"][-1] == "step 5" and tail["truncated_before"] is False
    assert client.get(url(pid, f"/{e['id']}")).json()["logs_tail"][-2:] == ["step 4", "step 5"]
    # a truncated / rotated file starts over
    log.write_text("fresh\n")
    again = client.get(url(pid, f"/{e['id']}/logs"), params={"offset": more["next"]}).json()
    assert again["lines"] == ["fresh"] and again["reset"] is True


def test_logs_hold_back_a_partial_line_while_running(client, project):
    pid, root = project
    e = create(client, pid)
    log = root / "run.log"
    log.write_text("epoch 1\nepoch 2 loss=0.\r10% |##\r55% |#####\nepoch 3 lo")
    client.patch(url(pid, f"/{e['id']}"), json={"logs": "run.log", "status": "running"})
    page = client.get(url(pid, f"/{e['id']}/logs")).json()
    assert page["lines"] == ["epoch 1", "55% |#####"]          # carriage returns overwrite; "epoch 3 lo" is held back
    assert not page["eof"]
    with log.open("a") as f:
        f.write("ss=0.4\n")
    nxt = client.get(url(pid, f"/{e['id']}/logs"), params={"offset": page["next"]}).json()
    assert nxt["lines"] == ["epoch 3 loss=0.4"] and nxt["eof"]
    client.patch(url(pid, f"/{e['id']}"), json={"status": "failed"})
    with log.open("a") as f:
        f.write("Traceback (most")
    last = client.get(url(pid, f"/{e['id']}/logs"), params={"offset": nxt["next"]}).json()
    assert last["lines"] == ["Traceback (most"]                 # finished: the partial last line is shown


def test_large_log_tail_starts_on_a_line_boundary(client, project):
    pid, root = project
    e = create(client, pid)
    (root / "big.log").write_text("".join(f"line {i:06d} " + "x" * 80 + "\n" for i in range(3000)))
    client.patch(url(pid, f"/{e['id']}"), json={"logs": "big.log", "status": "succeeded"})
    tail = client.get(url(pid, f"/{e['id']}/logs"), params={"offset": -5}).json()
    assert tail["truncated_before"] is True
    assert tail["lines"][0].startswith("line ") and tail["lines"][-1].startswith("line 002999")
    page = client.get(url(pid, f"/{e['id']}/logs"), params={"offset": 0}).json()
    assert len("\n".join(page["lines"])) <= records.LOG_PAGE_BYTES and not page["eof"]


# ------------------------------------------------------------------ resources

def test_resources_are_labeled_demo_data(client):
    r = client.get("/api/resources").json()
    assert r["source"] == "demo" and r["demo"] is True
    assert [p["id"] for p in r["platforms"]] == ["workstation", "lab", "cloud"]
    assert all(p["demo"] for p in r["platforms"]) and all(n["demo"] for p in r["platforms"] for n in p["nodes"])
    lab = r["platforms"][1]["nodes"][0]
    assert lab["inventory_only"] and lab["gpus"][0]["util"] is None          # unknown stays unknown, never 0
