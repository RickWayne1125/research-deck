"""Two projects over one workspace folder: each keeps its own state folder, config, DAG and kind."""


def test_two_projects_share_a_folder_with_separate_state(client, tmp_path):
    ws = tmp_path / "workspace"
    (ws / "repo").mkdir(parents=True)
    a = client.post("/api/projects", json={"root": str(ws), "name": "Integration PR", "kind": "engineering"}).json()
    b = client.post("/api/projects", json={"root": str(ws), "name": "Routing research", "state": ".research-routing"}).json()
    assert a["id"] != b["id"] and a["state"] == ".research" and b["state"] == ".research-routing"
    assert a["kind"] == "engineering" and b["kind"] == "research"
    assert (ws / ".research" / "project.yaml").exists() and (ws / ".research-routing" / "project.yaml").exists()
    # the same folder and state again is the same project
    again = client.post("/api/projects", json={"root": str(ws), "state": ".research-routing"}).json()
    assert again["id"] == b["id"]

    assert client.get("/api/session").status_code == 200
    op = {"op": "create", "node": {"id": "prob.routing", "kind": "problem", "status": "active", "title": "Routing",
                                   "facets": {"statement": "s"}}}
    assert client.post(f"/api/projects/{b['id']}/dag/ops", json={"ops": [op]}).status_code == 200
    ids = lambda pid: [n["id"] for n in client.get(f"/api/projects/{pid}/dag/graph").json()["nodes"]]
    assert ids(b["id"]) == ["prob.routing"] and ids(a["id"]) == []
    assert (ws / ".research-routing" / "dag" / "nodes" / "prob.routing.yaml").exists()
    assert not (ws / ".research" / "dag" / "nodes" / "prob.routing.yaml").exists()

    # config and kind are per project
    assert client.get(f"/api/projects/{a['id']}").json()["config"]["kind"] == "engineering"
    assert client.get(f"/api/projects/{b['id']}").json()["config"]["name"] == "Routing research"


def test_bad_state_and_kind_are_refused(client, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert client.post("/api/projects", json={"root": str(ws), "state": "../elsewhere"}).status_code == 400
    assert client.post("/api/projects", json={"root": str(ws), "state": ".git"}).status_code == 400
    assert client.post("/api/projects", json={"root": str(ws), "kind": "hobby"}).status_code == 400


def test_one_projects_state_is_never_another_projects_code(client, tmp_path):
    """A research project's DAG must not fingerprint the other project's state folder as code (non-git walk)."""
    ws = tmp_path / "ws2"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "a.py").write_text("x = 1\n")
    client.post("/api/projects", json={"root": str(ws), "name": "Eng", "kind": "engineering"})
    b = client.post("/api/projects", json={"root": str(ws), "name": "Res", "state": ".research-res"}).json()
    from research_deck.dag.resolve import Resolver  # noqa: F401 — the walk lives there
    from research_deck.dag.service import store_for
    from research_deck.dag.evaluate import current
    st = current(store_for(b["id"]))
    assert st is not None
    (ws / ".research" / "notes.txt").write_text("changes in the other project's state")
    assert current(store_for(b["id"])).digest == st.digest
