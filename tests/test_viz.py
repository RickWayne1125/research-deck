"""Visualization: the built-in style tokens and project overrides, the figure registry, matplotlib rendering, previews,
AI edits (fake agent) and the native-app adapters. Never calls a real Claude/Codex CLI or a native app."""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from research_deck import config


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """The fake agent and no native apps."""
    monkeypatch.setenv("RD_FAKE_AGENT", "1")
    monkeypatch.setenv("RD_LOCAL_DIR", str(config.LOCAL_DIR))
    monkeypatch.setattr(config, "app_path", lambda name: None)
    monkeypatch.setattr(config, "DATAGRAPH_CLI", str(tmp_path / "missing-dgraph"))
    yield


def wait_run(client, run_id: str) -> dict:
    for _ in range(300):
        got = client.get(f"/api/agent/runs/{run_id}").json()
        if got["status"] != "running":
            return got
        time.sleep(0.02)
    raise AssertionError("run did not finish")


# ---------------------------------------------------------------- style tokens

def test_builtin_style(client):
    tok = client.get("/api/style").json()
    assert tok["font"]["family"] == "Helvetica" and tok["font"]["size_pt"] == 9
    assert tok["active_palette"] == "palette_charcoal_signal_red"
    assert [p["id"] for p in tok["palettes"]] == ["palette_charcoal_signal_red", "palette_cobalt_terracotta", "palette_mint_charcoal"]
    assert tok["series"] == ["#C83232", "#30343A", "#787B7F", "#CBCCCE"]
    assert tok["roles"]["process"] == {"fill": "#E6EEF7", "stroke": "#6D8FAC"}
    assert all(p["source"] == "built-in" for p in tok["palettes"])


def test_project_style_override(client, project):
    pid, root = project
    r = client.put(f"/api/projects/{pid}/style", json={"active_palette": "palette_cobalt_terracotta"})
    assert r.status_code == 200 and r.json()["active_palette"] == "palette_cobalt_terracotta"
    assert r.json()["series"][0] == "#C65F38"
    assert json.loads((root / ".research/style.json").read_text()) == {"active_palette": "palette_cobalt_terracotta"}
    assert client.get("/api/style", params={"project": pid}).json()["active_palette"] == "palette_cobalt_terracotta"
    r = client.put(f"/api/projects/{pid}/style", json={"series": ["#112233", "#445566"], "font": {"size_pt": 8}})
    assert r.json()["series"] == ["#112233", "#445566"] and r.json()["font"]["size_pt"] == 8
    assert client.put(f"/api/projects/{pid}/style", json={"active_palette": "nope"}).status_code == 400
    assert client.put(f"/api/projects/{pid}/style", json={"series": ["red"]}).status_code == 400
    r = client.put(f"/api/projects/{pid}/style", json={"active_palette": None, "series": None})
    assert r.json()["active_palette"] == "palette_charcoal_signal_red" and r.json()["series"][0] == "#C83232"


# ---------------------------------------------------------------- figures

def test_matplotlib_create_and_render(client, project):
    pid, root = project
    r = client.post(f"/api/projects/{pid}/figures", json={"kind": "matplotlib", "title": "Throughput vs batch", "node_id": "X7"})
    assert r.status_code == 200, r.text
    fig = r.json()
    assert fig["id"] == "throughput-vs-batch" and fig["kind"] == "matplotlib" and fig["status"] == "unrendered"
    assert fig["source"] == "figures/throughput-vs-batch.py" and fig["data"] == ["figures/data/throughput-vs-batch.csv"]
    assert (root / "figures/_rdstyle.py").read_text().startswith("# research-deck: generated style helper")
    assert "import _rdstyle as rd" in (root / fig["source"]).read_text()
    registry = json.loads((root / ".research/figures.json").read_text())
    assert registry["version"] == 1 and registry["figures"][0]["node_id"] == "X7"

    r = client.post(f"/api/projects/{pid}/figures/{fig['id']}/render", json={})
    res = r.json()
    assert r.status_code == 200 and res["ok"], res["log"]
    assert res["preview"].startswith(f"/api/projects/{pid}/figures/{fig['id']}/preview?v=")
    svg = root / ".research/figures/previews/throughput-vs-batch.svg"
    assert svg.read_text().lstrip().startswith(("<?xml", "<svg"))
    got = client.get(res["preview"])
    assert got.status_code == 200 and got.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in got.headers["content-security-policy"]
    assert client.get(f"/api/projects/{pid}/figures/{fig['id']}").json()["status"] == "ok"

    # Changing a data file makes the preview stale.
    data = root / "figures/data/throughput-vs-batch.csv"
    original = data.read_text()
    data.write_text(original + "32,Ours,2100,40\n")
    assert client.get(f"/api/projects/{pid}/figures/{fig['id']}").json()["status"] == "stale"
    data.write_text(original)
    assert client.get(f"/api/projects/{pid}/figures/{fig['id']}").json()["status"] == "ok"

    # So does a palette change: it regenerates the style helper the script imports.
    client.put(f"/api/projects/{pid}/style", json={"active_palette": "palette_mint_charcoal"})
    helper = (root / "figures/_rdstyle.py").read_text()
    assert "palette_mint_charcoal" in helper and '"#5EB783"' in helper
    assert client.get(f"/api/projects/{pid}/figures/{fig['id']}").json()["status"] == "stale"
    # A hand-edited helper (marker line removed) is never regenerated.
    (root / "figures/_rdstyle.py").write_text("# mine\n" + helper)
    client.put(f"/api/projects/{pid}/style", json={"active_palette": None})
    assert (root / "figures/_rdstyle.py").read_text().startswith("# mine")

    # A second figure with the same title gets its own id and files.
    again = client.post(f"/api/projects/{pid}/figures", json={"kind": "matplotlib", "title": "Throughput vs batch"}).json()
    assert again["id"] == "throughput-vs-batch-2"


def test_render_error_returns_traceback(client, project):
    pid, root = project
    fid = client.post(f"/api/projects/{pid}/figures", json={"kind": "matplotlib", "title": "Broken"}).json()["id"]
    assert client.post(f"/api/projects/{pid}/figures/{fid}/render", json={}).json()["ok"]
    before = (root / f".research/figures/previews/{fid}.svg").read_bytes()
    bad = "import _rdstyle as rd\nfig, ax = rd.figure()\nraise ValueError('no such column: latency')\n"
    res = client.post(f"/api/projects/{pid}/figures/{fid}/render", json={"source": bad}).json()
    assert res["ok"] is False and res["preview"] is None
    assert "Traceback" in res["log"] and "ValueError: no such column: latency" in res["log"]
    assert f"{fid}.py" in res["log"] and "rd-preview" not in res["log"]      # points at the edited file
    assert "<frozen runpy>" not in res["log"] and '"<string>"' not in res["log"]   # no bootstrap frames
    assert (root / f".research/figures/previews/{fid}.svg").read_bytes() == before   # last good preview kept
    assert not [p for p in (root / "figures").iterdir() if p.name.startswith(".")]   # hidden copy removed
    # The saved file still renders, so the figure is not marked as broken by an unsaved buffer.
    assert client.get(f"/api/projects/{pid}/figures/{fid}").json()["status"] == "ok"
    # Unsaved source renders relative to the original's folder (data/ next to it).
    src = (root / f"figures/{fid}.py").read_text().replace("Batch size", "Batch")
    assert client.post(f"/api/projects/{pid}/figures/{fid}/render", json={"source": src}).json()["ok"]
    assert client.get(f"/api/projects/{pid}/figures/{fid}").json()["status"] == "stale"   # preview != saved file


def test_drawio_template_and_client_preview(client, project):
    pid, root = project
    fig = client.post(f"/api/projects/{pid}/figures", json={"kind": "drawio", "title": "System overview"}).json()
    xml = (root / fig["source"]).read_text()
    tree = ET.fromstring(xml)
    assert tree.tag == "mxfile" and tree.find("diagram/mxGraphModel") is not None
    styles = [c.get("style") or "" for c in tree.iter("mxCell")]
    assert sum("fontFamily=Helvetica" in s for s in styles) == 5 and all("fontSize=12" in s for s in styles if s)
    assert "fillColor=#E6EEF7" in xml   # the process role
    assert client.post(f"/api/projects/{pid}/figures/{fig['id']}/render", json={}).status_code == 400

    import base64
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script><rect width="10" height="10"/></svg>'
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    r = client.put(f"/api/projects/{pid}/figures/{fig['id']}/preview", json={"svg": uri})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    stored = (root / f".research/figures/previews/{fig['id']}.svg").read_text()
    assert "<rect" in stored and "<script" not in stored
    # draw.io's light-dark() export is pinned to light, so previews keep the paper colors in dark mode.
    dark = '<svg xmlns="http://www.w3.org/2000/svg" style="color-scheme: light dark;"><rect/></svg>'
    client.put(f"/api/projects/{pid}/figures/{fig['id']}/preview", json={"svg": dark})
    assert "color-scheme: light;" in (root / f".research/figures/previews/{fig['id']}.svg").read_text()
    assert client.put(f"/api/projects/{pid}/figures/{fig['id']}/preview", json={"svg": "hello"}).status_code == 400
    (root / fig["source"]).write_text(xml.replace("Process", "Prefetch"))
    assert client.get(f"/api/projects/{pid}/figures/{fig['id']}").json()["status"] == "stale"


def test_path_traversal_refused(client, project):
    pid, root = project
    assert client.post(f"/api/projects/{pid}/figures", json={"kind": "drawio", "title": "x", "source": "../../etc/hosts"}).status_code == 400
    fid = client.post(f"/api/projects/{pid}/figures", json={"kind": "drawio", "title": "Flow"}).json()["id"]
    assert client.patch(f"/api/projects/{pid}/figures/{fid}", json={"data": ["../outside.csv"]}).status_code == 400
    assert client.patch(f"/api/projects/{pid}/figures/{fid}", json={"source": "/etc/hosts"}).status_code in (400, 404)
    assert client.get(f"/api/projects/{pid}/figures/..%2F..%2Fetc/preview").status_code == 404
    # A registry entry edited by hand to point outside the project is refused too.
    reg = json.loads((root / ".research/figures.json").read_text())
    reg["figures"][0]["source"] = "../../outside.py"
    reg["figures"][0]["kind"] = "matplotlib"
    (root / ".research/figures.json").write_text(json.dumps(reg))
    assert client.post(f"/api/projects/{pid}/figures/{fid}/render", json={"source": "print(1)"}).status_code == 400


def test_patch_and_remove(client, project):
    pid, root = project
    fid = client.post(f"/api/projects/{pid}/figures", json={"kind": "drawio", "title": "Flow"}).json()["id"]
    r = client.patch(f"/api/projects/{pid}/figures/{fid}", json={"title": "Data flow", "node_id": "D2", "caption": "c"})
    assert r.json()["title"] == "Data flow" and r.json()["node_id"] == "D2"
    assert client.patch(f"/api/projects/{pid}/figures/{fid}", json={"node_id": ""}).json()["node_id"] is None
    assert client.patch(f"/api/projects/{pid}/figures/{fid}", json={"title": " "}).status_code == 400
    assert client.delete(f"/api/projects/{pid}/figures/{fid}").json() == {"ok": True}
    assert (root / "figures/flow.drawio").exists()            # files stay
    assert client.get(f"/api/projects/{pid}/figures").json() == []
    assert {"path": "figures/flow.drawio", "kind": "drawio"} in client.get(f"/api/projects/{pid}/figures/discover").json()


def test_ai_edit_fake_agent(client, project):
    pid, _ = project
    fid = client.post(f"/api/projects/{pid}/figures", json={"kind": "matplotlib", "title": "Latency"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/figures/{fid}/ai-edit", json={"instruction": "把 legend 移到图外"})
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["run_id"] and started["provider"] == "fake"
    done = wait_run(client, started["run_id"])
    assert done["status"] == "done" and done["purpose"] == "figure" and done["panel"] == "project"
    assert done["text"].startswith("```python\n") and "# fake edit: 把 legend 移到图外" in done["text"]
    assert "import _rdstyle as rd" in done["text"]            # the complete source came back

    flow = client.post(f"/api/projects/{pid}/figures", json={"kind": "drawio", "title": "Flow"}).json()["id"]
    run = client.post(f"/api/projects/{pid}/figures/{flow}/ai-edit", json={"instruction": "add a cache -- node", "source": "<mxGraphModel><root/></mxGraphModel>"}).json()
    text = wait_run(client, run["run_id"])["text"]
    assert text.startswith("```xml\n") and "<!-- fake edit: add a cache — node -->" in text
    assert client.post(f"/api/projects/{pid}/figures/{flow}/ai-edit", json={"instruction": " "}).status_code == 400


def test_native_kinds_and_missing_apps(client, project):
    pid, root = project
    assert client.post(f"/api/projects/{pid}/figures", json={"kind": "omnigraffle", "title": "Arch"}).status_code == 400
    (root / "figures").mkdir(exist_ok=True)
    (root / "figures/arch.graffle").write_bytes(b"PK\x03\x04 not really")
    (root / "figures/bars.dgraph").mkdir()
    (root / "figures/bars.dgraph/Content.plist").write_text("<plist/>")
    found = client.get(f"/api/projects/{pid}/figures/discover").json()
    assert {"path": "figures/arch.graffle", "kind": "omnigraffle"} in found
    assert {"path": "figures/bars.dgraph", "kind": "datagraph"} in found
    assert client.post(f"/api/projects/{pid}/figures", json={"kind": "datagraph", "title": "x", "source": "figures/arch.graffle"}).status_code == 400

    og = client.post(f"/api/projects/{pid}/figures", json={"kind": "omnigraffle", "title": "", "source": "figures/arch.graffle"}).json()
    assert og["id"] == "arch" and og["native"] == {"app": "omnigraffle", "installed": False, "path": None}
    r = client.post(f"/api/projects/{pid}/figures/{og['id']}/open-native")
    assert r.status_code == 409 and "not installed" in r.json()["detail"]["message"]
    assert client.post(f"/api/projects/{pid}/figures/{og['id']}/export-native").status_code == 409

    dg = client.post(f"/api/projects/{pid}/figures", json={"kind": "datagraph", "title": "Bars", "source": "figures/bars.dgraph"}).json()
    r = client.post(f"/api/projects/{pid}/figures/{dg['id']}/export-native")
    assert r.status_code == 409 and "DataGraph" in r.json()["detail"]["message"]
    assert client.post(f"/api/projects/{pid}/figures", json={"kind": "datagraph", "title": "Bars", "source": "figures/bars.dgraph"}).status_code == 409
    assert client.post(f"/api/projects/{pid}/figures/{dg['id']}/ai-edit", json={"instruction": "x"}).status_code == 400


def test_matplotlib_export_pdf(client, project):
    pid, root = project
    fid = client.post(f"/api/projects/{pid}/figures", json={"kind": "matplotlib", "title": "Paper plot"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/figures/{fid}/export-native")
    assert r.status_code == 200, r.text
    assert r.json()["outputs"] == [f"figures/{fid}.pdf"]
    assert (root / f"figures/{fid}.pdf").read_bytes().startswith(b"%PDF")
