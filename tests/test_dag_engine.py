"""DAG engine: fingerprints, evaluation passes, impact previews, rollback revival, cutoff vs predicates, refutation.

The fixture is a small `lookahead-serve` (docs/DAG.md §9): a scheduler module, a kv module, an e2e experiment with
2 systems × 2 rates whose traces list exactly the files and keys each cell read, a kv microbenchmark, a claim with a
predicate, and the design / module / section / drawn-figure soft edges.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import git
from research_deck.dag import seed
from research_deck.dag.evaluate import current
from research_deck.dag.fp import MISSING, cell_id, fp_file, fp_json, glob_match, parse_cell
from research_deck.dag.impact import impact
from research_deck.dag.ops import OpError, apply_ops
from research_deck.dag.store import DagStore

POLICY = "def admit(slack):\n    # admit prefill chunks while slack remains\n    return slack > 0\n"
FILES = {
    "src/lookahead/__init__.py": "",
    "src/lookahead/sched/__init__.py": "",
    "src/lookahead/sched/policy.py": POLICY,
    "src/lookahead/sched/budget.py": "def budget(slack_ms):\n    return slack_ms * 2\n",
    "src/lookahead/kv/cache.py": "class Cache:\n    block = 16\n",
    "bench/e2e.py": "import rd\nsystem = rd.cfg('system')\nif system == 'ours':\n    import lookahead.sched.policy\n",
    "bench/micro_kv.py": "import lookahead.kv.cache\n",
    "proto/mlfq_sim.py": "def sim():\n    return 0.9\n",
    "configs/sched.yaml": "sched:\n  chunk:\n    max: 2048   # tokens per chunk\n    min: 256\n  budget:\n    slack_ms: 50\n",
    "configs/base.yaml": "kv:\n  block: 16\n",
    "paper/design.tex": "\\section{Design}\n% rd:sec sec.design\nDecode is never preempted; speedup \\rdTtftSpeedupMax.\n% rd:end\n",
}
SCHED = ["src/lookahead/sched/policy.py", "src/lookahead/sched/budget.py"]
OURS_READS = ["bench/e2e.py", *SCHED, "src/lookahead/kv/cache.py"]
OURS_CFG = ["system", "rate", "sched.chunk.max", "sched.budget.slack_ms"]
TTFT = {("ours", 4): 121.0, ("ours", 8): 205.0, ("vllm", 4): 266.0, ("vllm", 8): 420.0}
E2E_SPEC = {"command": "python bench/e2e.py", "config": ["configs/sched.yaml"], "sweep": {"system": ["vllm", "ours"], "rate": [4, 8]},
            "platform": "workstation", "gpus": 1, "replicates": 1, "est_hours": 0.4}


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def commit(root: Path, msg: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)


def record_e2e(s: DagStore, system: str, rate: int, ttft: float, **kw):
    reads = OURS_READS if system == "ours" else ["bench/e2e.py"]
    keys = OURS_CFG if system == "ours" else ["system", "rate"]
    return seed.record(s, "exp.e2e", {"system": system, "rate": rate}, reads=reads, cfg_keys=keys,
                       outputs={"ttft_p99": ttft}, gpu_hours=0.4, **kw)


def build_world(root: Path, *, lock_design: bool = False) -> DagStore:
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in FILES.items():
        write(root, rel, text)
    git(root, "init", "-q", "-b", "main")
    commit(root, "init")
    s = seed.store(root)
    seed.env(s, "workstation", {"gpu_model": "NVIDIA L4", "python": "3.12.7"}, usd_per_gpu_hour=0.5)
    seed.add(s, "design.sched", "design", title={"en": "Lookahead scheduler", "zh": "前瞻调度器"}, status="confirmed", facets={
        "policy": "Admit prefill chunks until the tightest request's TTFT slack reaches zero.",
        "preemption": "None. Decode requests are never preempted.",
        "chunk": {"type": "bound", "bind": "configs/sched.yaml#sched.chunk"},
        "budget_slack_ms": {"type": "bound", "bind": "configs/sched.yaml#sched.budget.slack_ms"}})
    seed.add(s, "mod.sched", "module", facets={"globs": ["src/lookahead/sched/**"]},
             edges=[{"type": "implements", "to": "node:design.sched#policy"}, {"type": "implements", "to": "node:design.sched#preemption"}])
    seed.add(s, "mod.kv", "module", facets={"globs": ["src/lookahead/kv/**"]})
    seed.add(s, "exp.e2e", "experiment", purpose="eval", facets={"spec": E2E_SPEC, "outputs": {
        "ttft_p99": {"from": "metrics.json:$.ttft.p99", "unit": "ms", "tol": {"rel": 0.05}},
        "ttft_speedup": {"derive": "ratio(ttft_p99[system=vllm], ttft_p99) by rate"}}})
    seed.add(s, "exp.kv-micro", "experiment", purpose="microbench", facets={
        "spec": {"command": "python bench/micro_kv.py", "config": ["configs/base.yaml"], "platform": "workstation", "gpus": 1},
        "outputs": {"lat_us": {"from": "m.json:$.lat"}}})
    seed.add(s, "exp.proto-mlfq", "experiment", purpose="validate", facets={
        "spec": {"command": "python proto/mlfq_sim.py", "platform": "workstation", "gpus": 0}, "outputs": {"gain": {}}})
    for (system, rate), v in TTFT.items():
        record_e2e(s, system, rate, v)
    seed.record(s, "exp.kv-micro", "_", reads=["bench/micro_kv.py", "src/lookahead/kv/cache.py"], cfg_keys=["kv.block"],
                outputs={"lat_us": 3.2}, gpu_hours=0.2)
    seed.record(s, "exp.proto-mlfq", "_", reads=["proto/mlfq_sim.py"], cfg_keys=[], outputs={"gain": 0.9}, gpu_hours=0)
    seed.add(s, "claim.ttft-2x", "claim", status="confirmed", facets={
        "role": "result", "text": "Lookahead lowers P99 TTFT by up to {{speedup_max}} over vLLM, and by at least 2x at every load.",
        "bindings": {"speedup_max": {"from": "node:exp.e2e#out.ttft_speedup[system=ours]", "agg": "max", "fmt": "{:.1f}x",
                                     "macro": "rdTtftSpeedupMax"}}},
             edges=[{"type": "evidence", "to": "node:exp.e2e#out.ttft_speedup[system=ours]", "polarity": "supports",
                     "predicate": {"agg": "min", "op": ">=", "rhs": 2.0}}])
    seed.add(s, "sec.design", "section", facets={"file": {"type": "json", "value": "paper/design.tex"}, "text": {"type": "derived"}},
             edges=[{"type": "describes", "to": "node:design.sched#preemption"}])
    seed.add(s, "fig.arch", "figure", facets={"tool": "drawio", "file": {"type": "json", "value": "figures/arch.drawio"}},
             edges=[{"type": "describes", "to": "node:design.sched#preemption"}])
    if lock_design:
        seed.lock(s, "design.sched", "design freeze")
    commit(root, "dag")
    return s


@pytest.fixture
def world(tmp_path) -> DagStore:
    return build_world(tmp_path / "lookahead")


def cells(imp: dict, cat: str) -> set[tuple[str, str]]:
    return {(i["node"], c) for i in imp[cat] for c in i.get("cells") or []}


def nodes_in(imp: dict, cat: str) -> set[str]:
    return {i["node"] for i in imp[cat]}


OURS = {("exp.e2e", "rate=4,system=ours"), ("exp.e2e", "rate=8,system=ours")}
VLLM = {("exp.e2e", "rate=4,system=vllm"), ("exp.e2e", "rate=8,system=vllm")}


# ---------------------------------------------------------------- fingerprints

def test_fingerprints_normalize_python_and_json():
    a = fp_file("x.py", b"def f(x):\n    return x + 1  # add one\n")
    assert fp_file("x.py", b"def f(x):\n\n    # a comment line\n    return x + 1\n") == a          # comments / blank lines
    assert fp_file("x.py", b"def f(x):\n  return x + 1\n") == a                                    # indentation width
    assert fp_file("x.py", b"def f(x):\n    return x + 2\n") != a                                  # real change
    assert fp_file("x.py", b'def f(x):\n    """doc"""\n    return x + 1\n') != a                  # docstrings count
    assert fp_file("x.py", b'v = f"{a} b"  # c\n') == fp_file("x.py", b'v = f"{a} b"\n')           # f-strings joined
    assert fp_file("x.py", b"def f(:\n").startswith("g:")                                          # unparsable → blob
    assert fp_json({"a": 1, "b": [1.5, "x"]}) == fp_json({"b": [1.5, "x"], "a": 1})
    assert fp_json({"a": 1}) != fp_json({"a": 1.0})
    assert fp_file("c.json", b'{"a": 1,\n  "b": 2}') == fp_file("c.json", b'{"a":1,"b":2}')
    assert fp_json("Two  words\n here ", "prose") == fp_json("Two words here", "prose")
    assert fp_json("line  \nnext", "text") == fp_json("line\nnext", "text") != fp_json("line next", "text")
    assert glob_match("src/a/b/c.py", "src/a/**") and glob_match("src/a/c.py", "src/a/*.py") and not glob_match("src/a/b/c.py", "src/a/*.py")
    assert glob_match("src/a/b.py", "src/a") and not glob_match("src/ab.py", "src/a")
    assert cell_id({"system": "ours", "rate": 8}) == "rate=8,system=ours" and parse_cell("rate=8,system=ours") == {"rate": 8, "system": "ours"}


def test_comment_only_edit_keeps_cells_fresh(world):
    root = world.root
    write(root, "src/lookahead/sched/budget.py", "def budget(slack_ms):\n    # twice the slack, see §4\n    return slack_ms * 2\n")
    st = current(world)
    assert {c.level for c in st.E["exp.e2e"].cells.values()} == {"fresh"}
    write(root, "src/lookahead/sched/budget.py", "def budget(slack_ms):\n    return slack_ms * 3\n")
    st = current(world)
    assert st.E["exp.e2e"].cells["rate=8,system=ours"].level == "stale"
    assert st.E["exp.e2e"].cells["rate=8,system=vllm"].level == "fresh"         # baselines never read sched files
    why = st.E["exp.e2e"].cells["rate=8,system=ours"].why
    assert why[0]["addr"] == "code:src/lookahead/sched/budget.py"
    assert st.E["claim.ttft-2x"].level == "pending"


# ---------------------------------------------------------------- evaluation

def test_world_evaluates_fresh_with_derived_outputs(world):
    st = current(world)
    assert all(c.level == "fresh" for c in st.E["exp.e2e"].cells.values())
    assert st.E["claim.ttft-2x"].level == "fresh"
    assert st.E["claim.ttft-2x"].values["speedup_max"] == pytest.approx(266 / 121)
    assert st.E["design.sched"].level == "fresh" and st.E["mod.sched"].level == "fresh"
    assert st.E["sec.design"].level == "fresh"
    # the bound facet resolves to the config subtree
    assert st.R.node_fp("node:design.sched#chunk") == fp_json({"max": 2048, "min": 256})
    for nid, ev in st.E.items():
        assert "unsealed" not in ev.flags, nid


def test_env_is_checked_against_the_target_platform(world):
    seed.env(world, "workstation", {"gpu_model": "NVIDIA A100", "python": "3.12.7"})
    st = current(world)
    assert st.E["exp.e2e"].cells["rate=4,system=vllm"].level == "stale"
    assert any(w["addr"] == "env:gpu_model" for w in st.E["exp.e2e"].cells["rate=4,system=vllm"].why)


def test_predicate_crossing_is_caught_even_when_cutoff_keeps_the_fp(world):
    before = current(world)
    table_fp = before.E["exp.e2e"].out_fp("ttft_p99", None)
    speed_fp = before.E["exp.e2e"].out_fp("ttft_speedup", "system=ours")
    out = record_e2e(world, "ours", 8, 214.0)            # +4.4% vs the 205 anchor: within the 5% tolerance
    assert out["cutoff"]["ttft_p99"] is True
    st = current(world)
    assert st.E["exp.e2e"].out_fp("ttft_p99", None) == table_fp
    assert st.E["exp.e2e"].out_fp("ttft_speedup", "system=ours") == speed_fp
    claim = st.E["claim.ttft-2x"]
    assert claim.level == "broken"                         # 420/214 = 1.96 < 2.0 despite an unchanged fingerprint
    assert any(r["level"] == "broken" and "min >= 2.0" in r["note"] for r in claim.reasons)
    assert "lock_alert" not in claim.flags


def test_drift_flag_when_value_moves_but_predicate_holds(world):
    record_e2e(world, "ours", 4, 100.0)                   # −17%: outside tolerance, new fingerprint
    st = current(world)
    claim = st.E["claim.ttft-2x"]
    assert claim.level == "fresh" and "drift" in claim.flags


# ---------------------------------------------------------------- impact

def test_predicted_impact_of_a_design_edit(world):
    imp = impact(world, {"ops": [{"op": "edit", "node": "design.sched",
                                  "set": {"preemption": "Preempt decode-starved requests when TTFT slack < 0."}}]})
    assert imp["precision"] == "predicted"
    assert cells(imp, "rerun") == OURS                                       # their traces read sched files
    assert VLLM <= cells(imp, "reused") and ("exp.kv-micro", "_") in cells(imp, "reused")
    assert ("exp.proto-mlfq", "_") not in cells(imp, "reused")              # unrelated: not "near"
    assert nodes_in(imp, "review") >= {"mod.sched", "sec.design", "fig.arch"}
    assert "claim.ttft-2x" in nodes_in(imp, "conditional")
    assert imp["summary"]["rerun"] == 2 and imp["summary"]["gpu_h"]["rerun"] == pytest.approx(0.8)
    assert any(p["addr"] == "code:src/lookahead/sched/**" and p["to"] == "UNKNOWN" for p in imp["patched"])
    assert imp["why_paths"]["exp.e2e[rate=8,system=ours]"][:4] == ["node:design.sched#preemption", "implements", "mod.sched", "glob"]
    rerun = next(i for i in imp["rerun"] if i["node"] == "exp.e2e")
    assert rerun["impl_lag"] is True and rerun["platform"] == "workstation"
    assert not imp["lock"]


def test_design_edit_applies_and_flags_impl_lag(world):
    apply_ops(world, [{"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt when slack < 0."}}], "human:r")
    st = current(world)
    assert st.nodes["design.sched"]["status"] == "active"                 # a human edit demotes confirmed
    assert st.E["mod.sched"].level == "review"
    assert st.E["sec.design"].level == "review" and st.E["fig.arch"].level == "review"
    ours = st.E["exp.e2e"].cells["rate=8,system=ours"]
    assert ours.level == "fresh" and ours.impl_lag and not st.E["exp.e2e"].cells["rate=8,system=vllm"].impl_lag
    assert "design.sched" not in st.E["claim.ttft-2x"].shaky                 # changes never flow upstream / through cells


def test_exact_impact_of_a_code_diff(world):
    root = world.root
    write(root, "src/lookahead/sched/policy.py", POLICY.replace("slack > 0", "slack >= 0"))
    write(root, "src/lookahead/sched/budget.py", "def budget(slack_ms):\n    return slack_ms * 2  # unchanged logic\n")
    assert cells(impact(world, {"code": {"worktree": True}}), "rerun") == OURS        # unstaged
    git(root, "add", "-A")
    assert cells(impact(world, {"code": {"staged": True}}), "rerun") == OURS          # staged
    commit(root, "policy tweak")
    imp = impact(world, {"code": {"diff": "HEAD~1..HEAD"}})
    assert imp["precision"] == "exact"
    assert [p["addr"] for p in imp["patched"]] == ["code:src/lookahead/sched/policy.py"]
    assert [p["addr"] for p in imp["ignored"]] == ["code:src/lookahead/sched/budget.py"]
    assert cells(imp, "rerun") == OURS
    assert VLLM | {("exp.kv-micro", "_")} <= cells(imp, "reused")
    kv = next(i for i in imp["reused"] if i["node"] == "exp.kv-micro")
    assert kv["reason"].startswith("trace has 0 of 1 changed files")
    # after the commit the cells are already stale: a further edit is "not caused by this change"
    write(root, "src/lookahead/sched/policy.py", POLICY.replace("slack > 0", "slack > 1"))
    assert cells(impact(world, {"code": {"worktree": True}}), "rerun") == set()


def test_config_edit_of_a_bound_key(world):
    world_locked = world
    imp = impact(world_locked, {"ops": [{"op": "config_edit", "file": "configs/sched.yaml", "key": "sched.chunk.max", "value": 4096}]})
    assert imp["precision"] == "exact"
    assert cells(imp, "rerun") == OURS
    reused = {i["reason"] for i in imp["reused"] if i["node"] == "exp.e2e"}
    assert reused == {"never read sched.*"}
    assert any(p["addr"] == "cfg:sched.chunk.max" for p in imp["patched"])
    assert (world.root / "configs/sched.yaml").read_text() == FILES["configs/sched.yaml"]     # a preview writes nothing
    apply_ops(world, [{"op": "config_edit", "file": "configs/sched.yaml", "key": "sched.chunk.max", "value": 4096}], "human:r")
    text = (world.root / "configs/sched.yaml").read_text()
    assert "max: 4096   # tokens per chunk" in text                                        # comments and layout kept
    assert current(world).E["exp.e2e"].cells["rate=4,system=ours"].level == "stale"


def test_config_edit_bound_by_a_locked_design_needs_unlock(tmp_path):
    s = build_world(tmp_path / "locked", lock_design=True)
    imp = impact(s, {"ops": [{"op": "config_edit", "file": "configs/sched.yaml", "key": "sched.chunk.max", "value": 4096}]})
    assert imp["lock"] and imp["lock"][0]["requires"] == "unlock:design.sched"
    with pytest.raises(OpError) as e:
        apply_ops(s, [{"op": "config_edit", "file": "configs/sched.yaml", "key": "sched.chunk.max", "value": 4096}], "human:r")
    assert e.value.status == 409


def test_code_rollback_revives_old_runs_with_zero_reruns(world):
    root = world.root
    old = {c: current(world).E["exp.e2e"].cells[c].run["id"] for c in ("rate=4,system=ours", "rate=8,system=ours")}
    write(root, "src/lookahead/sched/policy.py", POLICY.replace("slack > 0", "slack > -1"))
    commit(root, "preempt")
    assert current(world).E["exp.e2e"].cells["rate=4,system=ours"].level == "stale"
    record_e2e(world, "ours", 4, 119.0)
    record_e2e(world, "ours", 8, 160.0)
    st = current(world)
    assert all(c.level == "fresh" for c in st.E["exp.e2e"].cells.values())
    imp = impact(world, {"code": {"diff": "HEAD..HEAD~1"}})
    assert imp["summary"]["rerun"] == 0
    revived = {(i["node"], i["cells"][0]): i["run"] for i in imp["revived"] if i.get("cells")}
    assert revived == {("exp.e2e", c): r for c, r in old.items()}
    # apply the revert the way an agent would (git), and the old runs verify again
    git(root, "revert", "--no-edit", "HEAD")
    st = current(world)
    assert {c: st.E["exp.e2e"].cells[c].run["id"] for c in old} == old
    assert st.E["exp.e2e"].cells["rate=4,system=ours"].reused


def test_node_rollback_restores_fp_and_clears_review(world):
    head0 = current(world).nodes["design.sched"]["head"]
    apply_ops(world, [{"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt when slack < 0."}}], "human:r")
    assert current(world).E["mod.sched"].level == "review"
    imp = impact(world, {"ops": [{"op": "rollback", "node": "design.sched", "to_vid": head0["vid"]}]})
    assert imp["summary"]["rerun"] == 0 and "mod.sched" in nodes_in(imp, "revived")
    apply_ops(world, [{"op": "rollback", "node": "design.sched", "to_vid": head0["vid"]}], "human:r")
    st = current(world)
    head = st.nodes["design.sched"]["head"]
    assert head["fp"] == head0["fp"] and head["rev"] == head0["rev"] + 2
    assert world.history("design.sched")[-1]["reverts"] == head0["vid"]
    assert st.E["mod.sched"].level == "fresh" and st.E["sec.design"].level == "fresh"


def test_rollback_closure_suggests_restoring_attested_edges(world):
    head0 = current(world).nodes["design.sched"]["head"]
    apply_ops(world, [{"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt when slack < 0."}}], "human:r")
    apply_ops(world, [{"op": "attest", "node": "mod.sched"}], "agent:codex:1")
    assert current(world).E["mod.sched"].level == "fresh"
    imp = impact(world, {"ops": [{"op": "rollback", "node": "design.sched", "to_vid": head0["vid"]}]})
    assert "mod.sched" in nodes_in(imp, "review")
    sug = next(i for i in imp["suggest_restore"] if i["node"] == "mod.sched")
    assert sug["op"]["op"] == "rollback" and sug["op"]["edges"] == "only"


def test_refute_freezes_evidence_and_revival_reports_already_tried(world):
    root = world.root
    seed.add(world, "sol.mlfq", "solution", alt_group="gap.interference",
             edges=[{"type": "evidence", "to": "node:exp.proto-mlfq#out.gain", "kill_if": {"agg": "max", "op": "<", "rhs": 1.1}}])
    assert current(world).E["sol.mlfq"].level == "broken"                 # the kill criterion is met
    r1 = current(world).E["exp.proto-mlfq"].cells["_"].run["id"]
    apply_ops(world, [{"op": "set_status", "node": "sol.mlfq", "to": "refuted", "reason": "gain 0.9 < 1.1"}], "human:r")
    n = current(world).nodes["sol.mlfq"]
    assert [e["to"] for e in n["edges"]] == [f"run:{r1}#out.gain"]
    assert n["edges"][0]["frozen_from"] == "node:exp.proto-mlfq#out.gain"
    assert any(e["op"] == "decision" and e["kind"] == "refute" for e in world.events())
    write(root, "proto/mlfq_sim.py", "def sim():\n    return 1.3\n")
    commit(root, "mlfq v2")
    seed.record(world, "exp.proto-mlfq", "_", reads=["proto/mlfq_sim.py"], cfg_keys=[], outputs={"gain": 1.3}, gpu_hours=0)
    imp = impact(world, {"code": {"diff": "HEAD..HEAD~1"}})
    assert ("exp.proto-mlfq", "_") in cells(imp, "revived")
    tried = imp["already_tried"]
    assert tried and tried[0]["node"] == "sol.mlfq" and tried[0]["run"] == r1 and "kill_if met" in tried[0]["note"]


def test_lenses_and_gates(world):
    from research_deck.dag.gates import compute, lenses, plan
    st = current(world)
    L = lenses(st)
    assert L["confirmed"]["count"] == 2 and L["revise"]["count"] == 0 and L["rerun"]["count"] == 0
    assert L["tried"]["runs"] == 6
    write(world.root, "bench/e2e.py", FILES["bench/e2e.py"] + "print('v2')\n")
    st = current(world)
    L = lenses(st)
    assert L["rerun"]["count"] == 4 and L["rerun"]["gpu_h"] == pytest.approx(1.6)
    assert L["rerun"]["items"][0]["id"] == "exp.e2e"
    assert plan(st)["gpu_h"] == pytest.approx(1.6)
    gates = {g["gate"]: g for g in compute(st)}
    assert list(gates) == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert gates["G6"]["state"] == "failing"
    assert {c["key"] for c in gates["G6"]["checks"]} == {"claims_fresh", "figures_fresh", "closure_built"}
    g5 = {c["key"]: c["ok"] for c in gates["G5"]["checks"]}
    assert g5["design_frozen"] and g5["implements_current"] and g5["microbench_fresh"]


def test_input_edges_stay_acyclic_and_pending_propagates(world):
    seed.add(world, "fig.e2e", "figure", facets={"spec": {"command": "python plots/e2e.py"}},
             edges=[{"type": "input", "to": "node:exp.e2e#out.ttft_p99"}])
    seed.record(world, "fig.e2e", "_", reads=[], cfg_keys=[], outputs={"pdf": "figs/e2e.pdf"})
    assert current(world).E["fig.e2e"].level == "fresh"
    write(world.root, "bench/e2e.py", FILES["bench/e2e.py"] + "x = 1\n")
    assert current(world).E["fig.e2e"].level == "pending"
    with pytest.raises(OpError) as e:
        apply_ops(world, [{"op": "link", "node": "exp.e2e", "edge": {"type": "input", "to": "node:fig.e2e#out.pdf"}}], "human:r")
    assert e.value.status == 400 and "cycle" in e.value.message


def test_store_layout_and_history(world):
    d = world.dir
    for sub in ("nodes", "history", "runs", "proposals", "snapshots", "envs"):
        assert (d / sub).is_dir()
    assert (d / ".gitignore").read_text() == ".cache/\n"
    assert "merge=union" in (world.root / ".gitattributes").read_text()
    cfg = (d / "config.yaml").read_text()
    # the file keeps only this project's settings; the neutral defaults stay layered underneath
    assert "schema: rd-dag/1" in cfg and "autocommit" not in cfg
    eff = world.config() if hasattr(world, "config") else None
    if eff:
        assert eff["autocommit"]["enabled"] is False and eff["policy"]["agent_auto_run"]["max_gpu_hours_per_day"] == 0
    assert (d / "cache" if False else d / ".cache" / "blobfp.sqlite").exists()
    hist = world.history("design.sched")
    assert [h["rev"] for h in hist] == [1, 2] and hist[1]["parent"] == hist[0]["vid"] and hist[1]["status"] == "confirmed"
    assert all(h["vid"].startswith("v-") and len(h["vid"]) == 10 for h in hist)
    assert (d / "runs" / "exp.e2e" / "rate=4,system=ours").is_dir()
    ev = world.events()
    assert ev[0]["e"] == "e-000001" and all("by" in e for e in ev)


def test_non_git_project_hashes_files_directly(tmp_path):
    root = tmp_path / "plain"
    write(root, "run.py", "print(1)\n")
    s = seed.store(root)
    seed.add(s, "exp.plain", "experiment", facets={"spec": {"command": "python run.py"}})
    seed.record(s, "exp.plain", "_", reads=["run.py"], cfg_keys=[], outputs={"v": 1})
    assert current(s).E["exp.plain"].level == "fresh"
    write(root, "run.py", "print(1)  # comment\n")
    assert current(s).E["exp.plain"].level == "fresh"
    write(root, "run.py", "print(2)\n")
    assert current(s).E["exp.plain"].level == "stale"
    (root / "run.py").unlink()
    assert current(s).E["exp.plain"].cells["_"].why[0]["to"] == MISSING


def test_unsealed_stated_numbers_and_datasets(world):
    import yaml
    # a YAML edit outside the API is flagged
    path = world.dir / "nodes" / "mod.kv.yaml"
    data = yaml.safe_load(path.read_text())
    data["facets"]["globs"]["value"] = ["src/elsewhere/**"]
    path.write_text(yaml.safe_dump(data))
    assert "unsealed" in current(world).E["mod.kv"].flags
    # a number typed into prose must stay within tolerance of its evidence
    apply_ops(world, [{"op": "edit", "node": "claim.ttft-2x", "editorial": True, "set": {"bindings": {"speedup_max": {
        "from": "node:exp.e2e#out.ttft_speedup[system=ours]", "agg": "max", "stated": 2.5, "macro": "rdTtftSpeedupMax"}}}}], "human:r")
    claim = current(world).E["claim.ttft-2x"]
    assert claim.level == "review" and any("text says 2.5" in (r.get("note") or "") for r in claim.reasons)
    # a dataset input: its version is the fingerprint, a new version makes the cell stale
    seed.add(world, "data.sharegpt", "dataset", facets={"version": {"type": "json", "value": "hf:sharegpt@r3"}})
    seed.add(world, "exp.load", "experiment", facets={"spec": {"command": "python bench/e2e.py", "datasets": ["data.sharegpt"]}},
             edges=[{"type": "input", "to": "node:data.sharegpt"}])
    seed.record(world, "exp.load", "_", reads=["bench/e2e.py"], cfg_keys=[], outputs={"n": 1})
    assert current(world).E["exp.load"].level == "fresh"
    seed.edit(world, "data.sharegpt", {"version": "hf:sharegpt@r4"})
    cell = current(world).E["exp.load"].cells["_"]
    assert cell.level == "stale" and {w["addr"] for w in cell.why} == {"node:data.sharegpt", "data:data.sharegpt"}


def test_graph_at_a_past_commit(world):
    from research_deck.dag.service import graph_json, past_state
    apply_ops(world, [{"op": "edit", "node": "design.sched", "set": {"preemption": "Preempt."}}], "human:r")
    write(world.root, "src/lookahead/sched/policy.py", "def admit(slack):\n    return True\n")
    commit(world.root, "after")
    g = graph_json(past_state(world, "HEAD~1"), at="HEAD~1")
    design = next(n for n in g["nodes"] if n["id"] == "design.sched")
    assert design["facets"]["preemption"]["value"].startswith("None.") and g["eval"]["mod.sched"]["level"] == "fresh"
    assert g["eval"]["exp.e2e"]["cells"]["rate=8,system=ours"]["level"] == "fresh"       # code resolved at that commit
    now = current(world)
    assert now.E["exp.e2e"].cells["rate=8,system=ours"].level == "stale"
