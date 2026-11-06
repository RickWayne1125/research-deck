"""Resource pools (research_deck/pools): rd-pool/1, definitions, sources, prices, budgets, routes and the adapters."""
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from research_deck.pools import protocol, service, sources, store
from research_deck.pools.__main__ import main as pools_cli

ROOT = Path(__file__).resolve().parents[1]


def human(client):
    assert client.get("/api/session").status_code == 200


def agent_client():
    from research_deck.app import create_app
    return TestClient(create_app(), headers={"X-RD-Request": "1"})      # no cookie: agent permissions


def doc(**kw):
    return {"protocol": "rd-pool/1", "as_of": sources.now_iso(), **kw}


MANUAL_HOME = {"id": "box", "label": "Box", "kind": "home",
               "source": {"type": "manual", "inventory": {"nodes": [{"id": "box", "gpus": [{"model": "RTX 5090"}]}]}}}
MANUAL_CLOUD = {"id": "js2", "label": "Jetstream2", "kind": "cloud",
                "source": {"type": "manual", "inventory": {"nodes": [
                    {"id": "g1", "flavor": "g3.large", "status": "online", "gpus": [{"model": "A100-40GB"}]}]}},
                "prices": [{"item": "node_hour", "match": {"flavor": "g3.large"}, "amount": 64, "unit": "SU"}]}


# ------------------------------------------------------------------ the protocol and definitions

def test_the_protocol_keeps_unknown_unknown_and_says_what_was_wrong():
    d, warnings = protocol.normalize(doc(
        nodes=[{"id": "a", "gpus": [{"model": "X", "util": 93, "count": 2}], "cpu": float("nan"), "later": 1}],
        quota=[{"name": "SU", "used": 5, "unit": "SU"}], spend={"amount": 3}, future_field=True))
    n = d["nodes"][0]
    assert n["gpus"][0]["util"] == pytest.approx(0.93) and n["gpus"][0]["count"] == 2
    assert n["cpu"] is None and n["status"] == "unknown" and "later" not in n
    assert d["quota"][0]["limit"] is None and d["spend"] is None
    assert any("percentage" in w for w in warnings) and any("limit unknown" in w for w in warnings)
    assert any("spend has no unit" in w for w in warnings)
    assert d["capabilities"] == ["inventory", "telemetry", "quota"]
    with pytest.raises(ValueError, match="rd-pool/1"):
        protocol.normalize({"protocol": "rd-pool/2"})


@pytest.mark.parametrize("bad, why", [
    ({"id": "Bad Id", "source": {"type": "manual"}}, "id"),
    ({"id": "../x", "source": {"type": "local"}}, "id"),
    ({"id": "x", "source": {"type": "shell", "run": "ls"}}, "source.type"),
    ({"id": "x", "source": {"type": "command", "run": "rd-pool --all"}}, "source.run"),
    ({"id": "x", "source": {"type": "http", "url": "http://example.org/pool"}}, "https"),
    ({"id": "x", "source": {"type": "local"}, "credential": "hunter2"}, "credential"),
    ({"id": "x", "source": {"type": "local"}, "prices": [{"item": "gpu_hour", "amount": 1}]}, "unit"),
    ({"id": "x", "source": {"type": "local", "every": 1}}, "every"),
    ({"id": "x", "source": {"type": "local"}, "budget": {"agent_gpu_hours_per_day": -1}}, "agent_gpu_hours_per_day"),
])
def test_definitions_are_validated(bad, why):
    with pytest.raises(ValueError, match=why):
        store.validate(bad)


def test_a_definition_gets_defaults_and_plain_http_only_on_this_machine():
    p = store.validate({"id": "edeck", "source": {"type": "http", "url": "http://127.0.0.1:9000/pools/edeck"}})
    assert p["kind"] == "cluster" and p["source"]["every"] == 60 and p["source"]["timeout"] == 30 and p["label"] == "edeck"
    assert p["credential"] is None and p["prices"] == [] and p["budget"] == {}


# ------------------------------------------------------------------ routes

def test_only_the_researcher_changes_pools_and_a_removed_pool_goes_to_the_trash(client):
    agent = agent_client()
    assert agent.put("/api/pools/box", json=MANUAL_HOME).status_code == 403
    assert agent.post("/api/pools/test", json=MANUAL_HOME).status_code == 403
    human(client)
    r = client.put("/api/pools/box", json=MANUAL_HOME)
    assert r.status_code == 200, r.text
    assert agent.get("/api/pools").json()["pools"][0]["def"]["id"] == "box"          # agents read
    assert agent.post("/api/pools/box/refresh").status_code == 403
    assert agent.delete("/api/pools/box").status_code == 403
    assert client.put("/api/pools/other", json=MANUAL_HOME).status_code == 400          # the id must match
    assert "id: box" in client.get("/api/pools/box").json()["yaml"]
    trashed = Path(client.delete("/api/pools/box").json()["trashed"])
    assert trashed.parent.name == ".trash" and trashed.exists() and client.get("/api/pools").json()["pools"] == []
    assert client.get("/api/pools/box").status_code == 404


def test_a_pool_file_is_imported_after_review_and_a_broken_file_is_listed(client):
    human(client)
    r = client.post("/api/pools/parse", json={"text": "id: lab\nkind: lab\nsource: {type: command, run: [rd-pool-lab]}\n"})
    assert r.status_code == 200 and r.json()["def"]["source"]["run"] == ["rd-pool-lab"] and r.json()["exists"] is False
    assert not store.exists("lab")                                   # parsing saves nothing
    assert client.post("/api/pools/parse", json={"text": "id: [unclosed"}).status_code == 400
    store.pools_dir().mkdir(parents=True, exist_ok=True)
    (store.pools_dir() / "broken.yaml").write_text("id: broken\nsource: {type: teleport}\n")
    assert client.get("/api/pools").json()["broken"][0]["file"] == "broken.yaml"


def test_the_resources_snapshot_the_project_selection_and_unmatched_names(client, project):
    pid, _ = project
    human(client)
    assert client.put("/api/pools/box", json={**MANUAL_HOME, "budget": {"agent_gpu_hours_per_day": 8}}).status_code == 200
    assert client.put("/api/pools/js2", json=MANUAL_CLOUD).status_code == 200
    r = client.post(f"/api/projects/{pid}/experiments", json={"title": "t", "target": {"platform": "workstation"}})
    assert r.status_code == 200, r.text
    snap = client.get("/api/resources", params={"project": pid}).json()
    by = {p["id"]: p for p in snap["platforms"]}
    assert snap["source"] == "pools" and set(by) == {"box", "js2"}
    box, js2 = by["box"], by["js2"]
    assert box["pool"]["rate"]["state"] == "free" and box["nodes"][0]["inventory_only"] and box["nodes"][0]["gpus"][0]["util"] is None
    assert js2["pool"]["rate"]["amount"] == 64 and js2["pool"]["rate"]["unit"] == "SU" and js2["pool"]["rate"]["item"] == "node_hour"
    assert js2["nodes"][0]["price"]["rule_amount"] == 64 and js2["pool"]["billed"] is True
    assert box["pool"]["budget"]["agent_gpu_hours_per_day"] == 8 and box["pool"]["budget"]["agent_used_today"] == 0
    assert snap["unmatched"] == ["workstation"] and snap["selection"] is None and all(p["pool"]["here"] for p in snap["platforms"])
    assert client.put(f"/api/projects/{pid}/pools", json={"pools": ["box"]}).json()["selection"] == ["box"]
    here = {p["id"]: p["pool"]["here"] for p in client.get("/api/resources", params={"project": pid}).json()["platforms"]}
    assert here == {"box": True, "js2": False}
    assert agent_client().put(f"/api/projects/{pid}/pools", json={"pools": None}).status_code == 403
    assert client.put(f"/api/projects/{pid}/pools", json={"pools": None}).json()["selection"] is None


ADAPTER = '''
import json, os, sys
from datetime import datetime, timezone
mode = open(sys.argv[1]).read().strip()
if mode == "fail":
    print("401 token expired", file=sys.stderr)
    sys.exit(1)
seen = os.environ.get("RD_POOL_SECRET") == "s3cret" and os.environ.get("RD_POOL_ID") == "lab"
print(json.dumps({"protocol": "rd-pool/1", "as_of": datetime.now(timezone.utc).isoformat(),
                  "nodes": [{"id": "n1", "label": "secret seen" if seen else "no secret", "status": "online",
                             "gpus": [{"model": "A100", "count": 2, "util": 0.5}]}],
                  "quota": [{"name": "GPU SU", "used": 100, "limit": 150, "unit": "SU"}],
                  "prices": [{"item": "gpu_hour", "amount": 2, "unit": "SU"}],
                  "credential": {"expires_at": "2000-01-01T00:00:00Z"}}))
'''


def test_a_command_source_gets_the_secret_and_a_failed_read_keeps_the_last_one(client, monkeypatch, tmp_path):
    human(client)
    monkeypatch.setenv("RD_TEST_POOL_SECRET", "s3cret")
    script, mode = tmp_path / "adapter.py", tmp_path / "mode"
    script.write_text(textwrap.dedent(ADAPTER))
    mode.write_text("ok")
    body = {"id": "lab", "label": "Lab", "kind": "cluster", "credential": "env:RD_TEST_POOL_SECRET",
            "source": {"type": "command", "run": [sys.executable, str(script), str(mode)], "every": 600}}
    t = client.post("/api/pools/test", json=body).json()
    assert t["ok"] and t["platform"]["nodes"][0]["label"] == "secret seen" and len(t["platform"]["nodes"][0]["gpus"]) == 2
    assert not store.exists("lab") and not store.cache_path("lab").exists()          # a test saves nothing
    p = client.put("/api/pools/lab", json=body).json()["platform"]
    assert p["pool"]["state"] == "ok" and p["pool"]["credential"]["state"] == "expired"
    assert p["nodes"][0]["gpus"][0]["util"] == 50.0 and p["quota_items"][0]["limit"] == 150
    assert "s3cret" not in store.cache_path("lab").read_text()                       # the secret is never written
    mode.write_text("fail")
    p = client.post("/api/pools/lab/refresh").json()["platform"]
    assert p["pool"]["state"] == "failed" and "401 token expired" in p["pool"]["error"]
    assert p["nodes"][0]["id"] == "n1"                                               # the last good reading stays
    monkeypatch.delenv("RD_TEST_POOL_SECRET")
    p = client.post("/api/pools/lab/refresh").json()["platform"]
    assert "RD_TEST_POOL_SECRET is not set" in p["pool"]["error"]
    t = client.post("/api/pools/test", json={**body, "source": {**body["source"], "run": ["/nonexistent/rd-pool"]}, "credential": None}).json()
    assert t["ok"] is False and "no such program" in t["error"]


def test_this_machine_is_read_on_the_spot():
    d, _warnings, _raw = sources.read(store.validate({"id": "local", "source": {"type": "local"}}))
    assert len(d["nodes"]) == 1 and d["nodes"][0]["status"] == "online" and "telemetry" in d["capabilities"]
    assert sources.parse_nvidia_smi("0, RTX 5090, 32607, 20480, [N/A], 71, 410\n")[0]["util"] is None


# ------------------------------------------------------------------ prices, estimates and budgets

def test_prices_the_definition_first_unknown_is_never_zero_and_units_stay_apart():
    pool = store.validate({"id": "c", "kind": "cloud", "source": {"type": "manual"},
                           "prices": [{"item": "gpu_hour", "match": {"gpu": "H100"}, "amount": 2.0, "unit": "USD"}]})
    d = protocol.normalize(doc(nodes=[{"id": "a", "gpus": [{"model": "H100", "count": 8}]},
                                      {"id": "b", "flavor": "g3.large", "gpus": [{"model": "A100", "count": 2}]}],
                               prices=[{"item": "gpu_hour", "match": {"gpu": "H100"}, "amount": 2.49, "unit": "USD"},
                                       {"item": "node_hour", "match": {"flavor": "g3.large"}, "amount": 64, "unit": "SU"}]))[0]
    assert service.rate(pool, d, gpu="H100")["amount"] == 2.0                   # what the researcher wrote wins
    b = service.rate(pool, d, node="b")
    assert (b["amount"], b["unit"], b["item"], b["rule_amount"]) == (32.0, "SU", "node_hour", 64)   # per machine ÷ its GPUs
    assert service.rate(pool, d)["state"] == "varies"
    assert service.rate(pool, d, gpu="T4")["state"] == "unknown"                # a cloud with no price: unknown, not 0
    assert service.rate(store.validate({"id": "h", "kind": "home", "source": {"type": "manual"}}), None)["state"] == "free"
    pricer = service.Pricer()
    assert pricer.estimate("nowhere", 2, probe={"usd_per_gpu_hour": 0.5})["amount"] == 1.0        # the env probe, as before
    assert pricer.estimate("nowhere", 2)["state"] == "unknown" and pricer.estimate("nowhere", 2)["amount"] is None
    priced = [({"state": "known", "amount": 1.5, "unit": "USD"}, 1), ({"state": "known", "amount": 128, "unit": "SU"}, 2),
              ({"state": "unknown", "amount": None, "unit": None}, 3), ({"state": "free", "amount": 0.0, "unit": None}, 4)]
    assert service.totals(priced) == {"cost": {"SU": 128, "USD": 1.5}, "unpriced": {"cells": 1, "gpu_h": 3}}


EXP = {"op": "create", "node": {"id": "exp.bench", "kind": "experiment", "status": "active", "title": "Bench",
                                "facets": {"spec": {"command": "python bench.py", "platform": "box", "gpus": 1,
                                                    "est_hours": 0.5}, "outputs": {}}}}


def test_the_run_plan_prices_cells_and_agents_queue_only_within_a_pools_budget(client, project):
    pid, _ = project
    human(client)
    dag = f"/api/projects/{pid}/dag"
    assert client.post(f"{dag}/ops", json={"ops": [EXP]}).status_code == 200
    plan = client.post(f"{dag}/runs/plan", json={}).json()
    assert plan["waves"][0][0]["cost"]["state"] == "unknown" and plan["unpriced"]["cells"] == 1   # no pool yet
    cloud = {**MANUAL_HOME, "kind": "cloud", "prices": [{"item": "gpu_hour", "amount": 2, "unit": "USD"}],
             "budget": {"month": {"amount": 0.5, "unit": "USD"}}}
    assert client.put("/api/pools/box", json=cloud).status_code == 200
    plan = client.post(f"{dag}/runs/plan", json={}).json()
    assert plan["cost"] == {"USD": 1.0} and plan["usd"] == 1.0 and plan["unpriced"]["cells"] == 0
    assert plan["limits"][0]["what"] == "month" and plan["limits"][0]["need"] == 1.0

    agent, cells = agent_client(), [{"node": "exp.bench", "cell": "_"}]
    r = agent.post(f"{dag}/runs/queue", json={"cells": cells, "platform": "box"})
    assert r.status_code == 403 and "gives agents no GPU-hours" in r.text
    assert client.put("/api/pools/box", json={**cloud, "budget": {"agent_gpu_hours_per_day": 0.6}}).status_code == 200
    r = agent.post(f"{dag}/runs/queue", json={"cells": cells, "platform": "box"})
    assert r.status_code == 200, r.text
    snap = client.get("/api/resources", params={"project": pid}).json()
    assert snap["platforms"][0]["pool"]["budget"]["agent_used_today"] == pytest.approx(0.5)
    r = agent.post(f"{dag}/runs/queue", json={"cells": cells, "platform": "box"})
    assert r.status_code == 403 and "daily budget" in r.text                     # 0.5 + 0.5 > 0.6
    assert client.put(f"/api/projects/{pid}/pools", json={"pools": []}).status_code == 200
    r = agent.post(f"{dag}/runs/queue", json={"cells": cells, "platform": "box"})
    assert r.status_code == 403 and "does not use the resource pool box" in r.text


# ------------------------------------------------------------------ the check command and the adapters

def test_the_check_command(tmp_path, capsys):
    f = tmp_path / "out.json"
    f.write_text(json.dumps(doc(nodes=[{"id": "a", "gpus": [{"model": "X", "util": 50}]}])))
    assert pools_cli(["check", "--file", str(f)]) == 1
    assert "looks like a percentage" in capsys.readouterr().out
    f.write_text(json.dumps(doc(nodes=[{"id": "a", "gpus": [{"model": "X", "util": 0.5}]}])))
    assert pools_cli(["check", "--file", str(f)]) == 0
    f.write_text("{}")
    assert pools_cli(["check", "--file", str(f)]) == 2


def _adapter(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "pools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_example_adapters_print_valid_documents():
    ssh = _adapter("rd_pool_ssh")
    out = ("0, NVIDIA GeForce RTX 5090, 32607, 20480, 93, 71, 410.5\n@@\n3.10 2.9 2.5 1/900 1234\n@@\n10\n@@\n"
           "MemTotal:       65536000 kB\nMemAvailable:   27525120 kB\n@@\n/usr/bin/python3\n")
    d, warnings = protocol.normalize(ssh.parse(out, "gpu-box", "GPU box"))
    n = d["nodes"][0]
    assert not warnings and n["gpus"][0]["util"] == pytest.approx(0.93) and n["cpu"] == pytest.approx(0.31)
    assert n["ram"] == pytest.approx(0.58) and n["running"] == ["python3"]
    slurm = _adapter("rd_pool_slurm")
    assert slurm.hostnames("gpu[01-03,07],cpu5") == ["gpu01", "gpu02", "gpu03", "gpu07", "cpu5"]
    sinfo = ("gpu01|mixed|gpu:a100:4(S:0-1)|64|12.8|512000|200000|gpu*\ngpu01|mixed|gpu:a100:4(S:0-1)|64|12.8|512000|200000|long\n"
             "gpu02|down*|gpu:a100:4|64|N/A|512000|N/A|gpu*\n")
    d, warnings = protocol.normalize(slurm.parse(sinfo, "gpu01|train\ngpu[01-02]|eval\n"))
    a, b = d["nodes"]
    assert not warnings and (a["status"], a["flavor"], a["running"]) == ("online", "gpu", ["train", "eval"])
    assert a["gpus"][0]["model"] == "a100" and a["gpus"][0]["count"] == 4 and a["cpu"] == pytest.approx(0.2)
    assert (b["status"], b["state"], b["cpu"]) == ("offline", "down", None)
