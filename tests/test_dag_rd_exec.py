"""rd_exec traces a real (small) job: file reads, imports, rd.cfg() reads and misses, directory listings; files the job
writes are excluded; outputs are extracted; the code snapshot lands at refs/rd/runs/<id>; the record verifies."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import git
from research_deck.dag import seed
from research_deck.dag.evaluate import current
from research_deck.dag.fp import MISSING, fp_json

SERVER = Path(__file__).resolve().parents[1] / "server"
SCRIPT = """\
import json, os
import rd
import helper
lr = rd.cfg("train.lr")
missing = rd.cfg("train.warmup", 0)
with open("data/input.txt") as f:
    n = len(f.read())
names = os.listdir("data")
os.makedirs("out", exist_ok=True)
with open("out/metrics.json", "w") as f:
    json.dump({"score": helper.scale(n) * lr, "names": len(names)}, f)
print("score", helper.scale(n) * lr)
"""


def run_rd_exec(root: Path, spec_doc: dict, cell: dict, out: Path) -> dict:
    spec_path = root.parent / "spec.json"
    spec_path.write_text(json.dumps(spec_doc))
    env = {**os.environ, "PYTHONPATH": str(SERVER)}
    p = subprocess.run([sys.executable, "-m", "research_deck.dag.rd_exec", "--spec", str(spec_path), "--cell", json.dumps(cell),
                        "--root", str(root), "--out", str(out), "--", sys.executable, "script.py"],
                       cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(out.read_text())


def test_rd_exec_traces_a_small_script(tmp_path):
    root = tmp_path / "toy"
    (root / "data").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "script.py").write_text(SCRIPT)
    (root / "helper.py").write_text("def scale(x):\n    return x * 2\n")
    (root / "unused.py").write_text("x = 1\n")
    (root / "data/input.txt").write_text("hello")
    (root / "configs/base.yaml").write_text("train:\n  lr: 0.5\n  epochs: 3\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    (root / "helper.py").write_text("def scale(x):\n    return x * 2  # dirty but same tokens\n")   # dirty file: in the snapshot

    s = seed.store(root)
    seed.add(s, "exp.toy", "experiment", purpose="profile", facets={
        "spec": {"command": "python script.py", "config": ["configs/base.yaml"], "sweep": {"train.epochs": [3, 5]}, "replicates": 2},
        "outputs": {"score": {"from": "out/metrics.json:$.score"}}})
    rec = run_rd_exec(root, seed.exec_spec(s, "exp.toy"), {"train.epochs": 5}, tmp_path / "rd_run.json")

    T = rec["trace"]
    assert rec["state"] == "succeeded" and rec["trace_quality"] == "traced" and rec["cell"] == "train.epochs=5"
    assert {"code:script.py", "code:helper.py", "code:data/input.txt"} <= set(T)          # entrypoint, import, file read
    assert "code:unused.py" not in T                                                     # never read
    assert not any(a.startswith("code:out/") for a in T)                                 # it wrote that file itself
    assert "code:configs/base.yaml" not in T                                             # the declared chain is per key
    assert T["cfg:train.lr"]["fp"] == fp_json(0.5) and T["cfg:train.warmup"]["fp"] == MISSING
    assert "cfg:train.epochs" not in T                                                   # not read by the script
    assert T["dir:data"]["fp"].startswith("d:")
    assert "env:python" in T
    assert rec["outputs"]["score"]["value"] == 5.0 and rec["outputs"]["score"]["n"] == 2
    assert rec["git"]["snapshot"] == f"refs/rd/runs/{rec['id']}" and rec["git"]["dirty"] is True
    tree = git(root, "show", f"{rec['git']['snapshot']}:helper.py")
    assert "dirty but same tokens" in tree                                               # exact code, dirty files included

    # the record verifies against the project as it is now
    from research_deck.dag.ops import record_run
    out = record_run(s, rec, "system")
    st = current(s)
    cell = st.E["exp.toy"].cells["train.epochs=5"]
    assert cell.level == "fresh" and cell.run["id"] == out["run_id"]
    assert st.E["exp.toy"].cells["train.epochs=3"].level == "unbuilt"
    # changing a key the script read makes it stale; one it never read does not
    (root / "configs/base.yaml").write_text("train:\n  lr: 0.5\n  epochs: 4\n")
    assert current(s).E["exp.toy"].cells["train.epochs=5"].level == "fresh"
    (root / "configs/base.yaml").write_text("train:\n  lr: 0.1\n  epochs: 3\n")
    assert current(s).E["exp.toy"].cells["train.epochs=5"].level == "stale"
    (root / "configs/base.yaml").write_text("train:\n  lr: 0.5\n  epochs: 3\n  warmup: 10\n")      # a key read as a miss
    assert current(s).E["exp.toy"].cells["train.epochs=5"].level == "stale"
