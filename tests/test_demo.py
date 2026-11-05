"""The demo project: materialized from demo/minimal into <LOCAL_DIR>/demo/toycache (research_deck/demo.py).

One build per module (about 1.5 s); every other test reuses it through the dashboard's own API. conftest.py switches
the demo off for every other test (config.DEMO_ENABLED).
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

import pytest

from research_deck import config, demo
from research_deck.dag import service
from research_deck.util import read_json

pytestmark = pytest.mark.skipif(not demo._git_works(), reason="git is not installed")

MESSAGES = [
    "Research Deck: research DAG, experiment records, figure registry",
    "lookahead: break ties in LRU order, as the design says",
    "Attempt B: lookahead eviction; results, paper draft, figures",
    "Attempt A: LFU eviction; baseline results",
    "Baseline: LRU block cache simulator, synthetic trace, experiment configs",
]


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def tree_digest(root: Path) -> dict[str, str]:
    """Every working-tree file's sha256, except the caches and previews Research Deck regenerates (git's own state
    is compared through its commits: `git status` may refresh the index)."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not rel.startswith((".git/", ".research/dag/.cache/", ".research/figures/")):
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    local = tmp_path_factory.mktemp("demo-local")
    source = tree_digest(demo.source_dir())
    t = time.monotonic()
    root = demo.ensure_demo(local / "demo" / demo.NAME)
    seconds = time.monotonic() - t
    assert root is not None and demo.is_complete(root)
    return {"local": local, "root": root, "seconds": seconds, "source": source}


@pytest.fixture
def deck(built, client, monkeypatch):
    """The demo registered in a fresh registry, as on a first start: (client, pid, root)."""
    monkeypatch.setattr(config, "LOCAL_DIR", built["local"])
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    projects = client.get("/api/projects").json()
    entry = next(p for p in projects if p["demo"])
    assert entry["id"] == demo.PROJECT_ID and Path(entry["root"]) == built["root"] and entry["is_git"]
    assert entry["name"] == "toycache (demo)" and "made up" in entry["summary"]
    return client, entry["id"], built["root"]


def test_source_is_small_and_holds_only_sources():
    src = demo.source_dir()
    files = [p for p in src.rglob("*") if p.is_file()]
    assert sum(p.stat().st_size for p in files) < 100 * 1024
    names = {p.relative_to(src).as_posix() for p in files}
    assert not any(n.startswith((".git/", ".research/dag/", ".research/figures/")) or "__pycache__" in n for n in names)
    assert "all numbers are made up" in (src / "README.md").read_text().lower()


def test_build_is_fast_local_and_leaves_the_source_alone(built):
    assert built["seconds"] < 10            # about 1.5 s; the budget is 5 s
    assert [p.name for p in built["local"].iterdir()] == ["demo"]
    assert [p.name for p in (built["local"] / "demo").iterdir()] == [demo.NAME]
    assert tree_digest(demo.source_dir()) == built["source"]


def test_history_and_the_uncommitted_change(built):
    root = built["root"]
    log = git(root, "log", "--format=%H|%an <%ae>|%aI|%cI|%s").splitlines()
    assert [line.split("|")[4] for line in log] == MESSAGES
    assert {line.split("|")[1] for line in log} == {"Research Deck Demo <demo@example.invalid>"}
    assert [line.split("|")[2][:10] for line in log] == ["2026-10-26", "2026-10-26", "2026-10-19", "2026-10-12", "2026-10-05"]
    marker = read_json(root / ".git" / demo.COMPLETE)
    assert [line.split("|")[0] for line in log] == [marker["commits"][c] for c in ("c5", "c4", "c3", "c2", "c1")]
    assert git(root, "status", "--porcelain").splitlines() == [" M toycache/lru.py"]
    changed = [line for line in git(root, "diff").splitlines() if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    assert changed == ["+            # TODO: a CLOCK approximation would avoid reordering the dict on every hit."]
    # c4 changed exactly one policy file; c3 had the other tie-breaking
    assert git(root, "show", "--name-only", "--format=", "HEAD~1").split() == ["toycache/lookahead.py"]
    assert "sorted(self.blocks)" in git(root, "show", "HEAD~2:toycache/lookahead.py")
    # machine-local state is ignored, the rest of .research/ is committed
    assert (root / ".research" / ".gitignore").read_text().split() == [
        "sessions.json", "context/", "writing/reviews/", "writing/snapshots/", "figures/", "dag/.cache/"]
    tracked = git(root, "ls-files").split()
    assert ".research/dag/nodes/sol.lfu.yaml" in tracked and ".research/experiments/lookahead.json" in tracked
    assert not any(t.startswith(".research/dag/.cache") for t in tracked)


def test_shas_are_stable(built, tmp_path):
    again = demo.ensure_demo(tmp_path / "demo" / demo.NAME)
    assert read_json(again / ".git" / demo.COMPLETE) == read_json(built["root"] / ".git" / demo.COMPLETE)
    assert tree_digest(again) == tree_digest(built["root"])


def test_dag_lenses(deck):
    client, pid, root = deck
    lenses = client.get(f"/api/projects/{pid}/dag/lenses").json()
    tried = {i["id"]: i["note"] for i in lenses["tried"]["items"]}
    assert len(tried) == 15 and lenses["tried"]["dead"] == 1
    assert "LFU hits 0.37" in tried["sol.lfu"]
    assert {i["id"]: i["cells"] for i in lenses["rerun"]["items"]} == {
        "exp.lookahead": ["_"],
        "exp.window-sweep": ["lookahead.window=16", "lookahead.window=32", "lookahead.window=4"]}
    assert {i["note"] for i in lenses["rerun"]["items"]} == {"rerun"}
    confirmed = {i["id"] for i in lenses["confirmed"]["items"]}
    assert {"prob.hit-rate", "find.lru-low", "gap.queue-hint", "dec.policy", "design.cache"} <= confirmed

    g = client.get(f"/api/projects/{pid}/dag/graph").json()
    ev, nodes = g["eval"], {n["id"]: n for n in g["nodes"]}
    stages = {n["stage"] for n in nodes.values()}
    assert stages == {"S0", "S1", "S2", "S3", "S4", "S5", "S6", "W"}
    # the reused baseline stays fresh: c4 did not touch what it read, and a comment in lru.py never counts
    assert ev["exp.baseline"]["level"] == "fresh"
    assert {c: x["level"] for c, x in ev["exp.baseline"]["cells"].items()} == {"policy=lfu": "fresh", "policy=lru": "fresh"}
    assert ev["exp.lookahead"]["level"] == "stale" and ev["exp.window-sweep"]["level"] == "unbuilt"
    assert ev["fig.hit-rate"]["level"] == "fresh"
    why = ev["exp.lookahead"]["cells"]["_"]["why"]
    assert [w["addr"] for w in why] == ["code:toycache/lookahead.py"]
    # the refuted attempt keeps its evidence, frozen to the run it was judged on
    lfu = nodes["sol.lfu"]
    assert lfu["status"] == "refuted" and lfu["alt_group"] == nodes["sol.lookahead"]["alt_group"]
    frozen = [e for e in lfu["edges"] if e["type"] == "evidence"]
    run_lfu = read_json(root / ".research" / "experiments" / "baseline-lfu.json")["run_id"]
    assert [e["to"] for e in frozen] == [f"run:{run_lfu}#out.hit_rate"] and frozen[0]["kill_if"]["rhs"] == 0.45
    assert nodes["sol.lookahead"]["status"] == "confirmed" and ev["sol.lookahead"]["level"] == "pending"
    # the claim waits for the rerun, and already notices the paper's number
    claim = ev["claim.hit-rate"]
    assert claim["level"] == "pending"
    assert any("text says 0.61, evidence 0.58" in (r.get("note") or "") for r in claim["reasons"])


def test_experiment_records_freshness(deck):
    client, pid, root = deck
    want = {"baseline-lru": "fresh", "baseline-lfu": "fresh", "lookahead": "stale", "window-sweep": "unknown"}
    for eid, fresh in want.items():
        rec = read_json(root / ".research" / "experiments" / f"{eid}.json")
        assert rec["node_id"].startswith("exp.")
        f = service.experiment_freshness(pid, rec["node_id"], run_id=rec.get("run_id"), cell=rec.get("cell"))
        assert f["freshness"] == fresh, (eid, f)
    lookahead = read_json(root / ".research" / "experiments" / "lookahead.json")
    run = next((root / ".research" / "dag" / "runs" / "exp.lookahead").rglob(f"{lookahead['run_id']}.json"))
    assert read_json(run)["experiment"] == "lookahead"
    assert lookahead["code"]["commit"] == read_json(root / ".git" / demo.COMPLETE)["commits"]["c3"]
    listed = {e["id"]: e["freshness"] for e in client.get(f"/api/projects/{pid}/experiments").json()}
    assert listed == want


def test_figures_render_and_link(deck):
    client, pid, root = deck
    figs = {f["id"]: f for f in client.get(f"/api/projects/{pid}/figures").json()}
    assert figs["hit-rate"]["node_id"] == "fig.hit-rate" and figs["hit-rate"]["node"]["freshness"] == "fresh"
    assert figs["pipeline"]["kind"] == "drawio" and figs["pipeline"]["exists"]
    r = client.post(f"/api/projects/{pid}/figures/hit-rate/render", json={})
    assert r.status_code == 200 and r.json()["ok"], r.json().get("log")
    assert client.get(f"/api/projects/{pid}/figures/hit-rate").json()["status"] == "ok"
    assert git(root, "status", "--porcelain").splitlines() == [" M toycache/lru.py"]   # previews are machine-local


def test_writing_and_coding_panels(deck):
    client, pid, root = deck
    docs = {d["path"]: d for d in client.get(f"/api/projects/{pid}/writing/docs").json()}
    assert "paper/main.md" in docs
    terms = client.get(f"/api/projects/{pid}/writing/glossary").json()["terms"]
    assert {t["preferred"] for t in terms} >= {"lookahead"}
    paper = (root / "paper" / "main.md").read_text()
    assert "recieves" in paper and "look-ahead" in paper and "0.61" in paper     # the three deliberate issues
    assert "0.58" in (root / "experiments" / "results" / "lookahead.csv").read_text()
    status = client.get(f"/api/projects/{pid}/git/status").json()
    assert "toycache/lru.py" in str(status)


def test_idempotent(built):
    root = built["root"]

    def state():
        return (tree_digest(root), git(root, "for-each-ref", "--format=%(refname) %(objectname)"),
                git(root, "status", "--porcelain"), (root / ".git" / demo.COMPLETE).read_text())

    before = state()
    t = time.monotonic()
    assert demo.ensure_demo(root) == root
    assert time.monotonic() - t < 0.5
    assert state() == before


def test_interrupted_build_is_redone_and_foreign_folders_are_left_alone(tmp_path):
    target = tmp_path / "demo" / demo.NAME
    (target / ".git").mkdir(parents=True)
    (target / ".git" / demo.BUILDING).write_text("")
    (target / "half-written.txt").write_text("x")
    assert demo.ensure_demo(target) == target and demo.is_complete(target)
    assert not (target / "half-written.txt").exists()
    foreign = tmp_path / "other" / demo.NAME
    foreign.mkdir(parents=True)
    (foreign / "notes.txt").write_text("mine")
    assert demo.ensure_demo(foreign) is None and (foreign / "notes.txt").read_text() == "mine"


def test_registry_forgets_the_old_bundled_demo(built, client, monkeypatch, tmp_path):
    from research_deck.util import write_json
    write_json(config.REGISTRY_FILE, {"version": 1, "projects": [
        {"id": "old-demo", "root": str(tmp_path / "gone" / "old-demo"), "demo": True, "added_at": "2026-11-02T00:00:00Z"}]})
    monkeypatch.setattr(config, "LOCAL_DIR", built["local"])
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    assert [(p["id"], p["root"]) for p in client.get("/api/projects").json()] == [("demo", str(built["root"]))]


def test_dismissing_the_demo_keeps_it_away(deck):
    client, pid, root = deck
    assert client.delete(f"/api/projects/{pid}").json() == {"ok": True}
    assert not any(p["demo"] for p in client.get("/api/projects").json())
    assert read_json(config.REGISTRY_FILE)["demo_dismissed"] is True
    assert demo.is_complete(root)                                   # the folder itself is untouched
