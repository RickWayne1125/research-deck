"""The demo project, materialized on first start from demo/minimal into <LOCAL_DIR>/demo/toycache.

ensure_demo() copies the source files, replays a short git history with a fixed author and fixed dates (so the shas
are stable), builds the research DAG through the engine (dag.seed: the op engine and record_run as the system actor,
the engine's clock pinned to the story), links the experiment records and figures to their nodes, commits .research/
and leaves one uncommitted edit for the Coding panel. It writes nothing outside the target folder, returns at once
when the demo is already complete (it never resets a demo the user has worked in) and returns None without git.

  commit  files                                          DAG (as the researcher would have built it at that commit)
  c1      LRU baseline: trace, simulator, both configs   problem, 2 references, exp.baseline + LRU run, finding, gap
  c2      attempt A: LFU, baseline results               sol.lfu with its kill criterion, LFU run, sol.lfu refuted
                                                         (evidence frozen to the run)
  c3      attempt B: lookahead, results, paper, figures  exp.lookahead + run, sol.lookahead confirmed, decision,
                                                         design, module, fig.hit-rate + render run, claim,
                                                         exp.window-sweep (planned: unbuilt)
  c4      lookahead.py: ties go in LRU order             nothing: the engine sees exp.lookahead go stale while
                                                         exp.baseline and the figure stay fresh (reused)
  c5      .research/                                     the DAG, experiment records, figure registry, glossary
  worktree  a comment in toycache/lru.py (a comment never changes a Python fingerprint)
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from . import config
from .util import read_json, write_json, write_text_atomic, write_yaml

log = logging.getLogger("research_deck.demo")

NAME = "toycache"
PROJECT_ID = "demo"
VERSION = 1
AUTHOR = ("Research Deck Demo", "demo@example.invalid")
HUMAN = "human:demo"
COMPLETE = "research-deck-demo.json"        # in .git/: written last, so it means "complete"
BUILDING = "research-deck-demo.building"    # in .git/: a build in progress (or one that died): safe to redo

# Every source file outside .research/ enters in exactly one of c1-c3; c4 changes one policy file.
HISTORY = [
    ("c1", "2026-10-05T14:00:00Z", "Baseline: LRU block cache simulator, synthetic trace, experiment configs",
     ["README.md", ".gitignore", "toycache/__init__.py", "toycache/trace.py", "toycache/sim.py", "toycache/lru.py",
      "configs/base.yaml", "configs/lookahead.yaml"]),
    ("c2", "2026-10-12T14:00:00Z", "Attempt A: LFU eviction; baseline results",
     ["toycache/lfu.py", "experiments/results/baseline.csv", "experiments/logs/baseline.log"]),
    ("c3", "2026-10-19T14:00:00Z", "Attempt B: lookahead eviction; results, paper draft, figures",
     ["toycache/lookahead.py", "experiments/results/lookahead.csv", "experiments/logs/lookahead.log", "paper/main.md",
      "figures/_rdstyle.py", "figures/fig_hit_rate.py", "figures/data/hit_rate.csv", "figures/pipeline.drawio"]),
    ("c4", "2026-10-26T14:00:00Z", "lookahead: break ties in LRU order, as the design says", ["toycache/lookahead.py"]),
]
RESEARCH_COMMIT = ("c5", "2026-10-26T15:00:00Z", "Research Deck: research DAG, experiment records, figure registry")
# The c3 version of a file = its demo/minimal (final) text with these replacements.
EARLIER = {("c3", "toycache/lookahead.py"): [(
    "        # Ties (blocks the window never asks for) go in LRU order: max() keeps the first, the least recently used.\n"
    "        return max(self.blocks, key=lambda b: next_use.get(b, len(upcoming)))\n",
    "        # Ties (blocks the window never asks for): the smallest block id.\n"
    "        return max(sorted(self.blocks), key=lambda b: next_use.get(b, len(upcoming)))\n")]}
WORKTREE_EDIT = ("toycache/lru.py", "            self.blocks.move_to_end(block)\n",
                 "            # TODO: a CLOCK approximation would avoid reordering the dict on every hit.\n"
                 "            self.blocks.move_to_end(block)\n")
RESEARCH_GITIGNORE = "sessions.json\ncontext/\nwriting/reviews/\nwriting/snapshots/\nfigures/\ndag/.cache/\n"

SIM = ["toycache/__init__.py", "toycache/sim.py", "toycache/trace.py"]
BASE_KEYS = ["policy", "cache.capacity_blocks", "trace.length", "trace.blocks", "trace.skew", "trace.drift_every",
             "trace.seed"]
# experiment record -> (node, cell, files the run read, config keys it read)
RUNS = {
    "baseline-lru": ("exp.baseline", {"policy": "lru"}, [*SIM, "toycache/lru.py"], BASE_KEYS),
    "baseline-lfu": ("exp.baseline", {"policy": "lfu"}, [*SIM, "toycache/lfu.py"], BASE_KEYS),
    "lookahead": ("exp.lookahead", {}, [*SIM, "toycache/lookahead.py"], [*BASE_KEYS, "lookahead.window"]),
}
PLANNED = {"window-sweep": "exp.window-sweep"}
FIGURES = {"hit-rate": "fig.hit-rate", "pipeline": "design.cache"}
FIG_READS = ["figures/fig_hit_rate.py", "figures/_rdstyle.py", "figures/data/hit_rate.csv"]

_LOCK = threading.Lock()
_FAILED: set[str] = set()
_GIT_OK: bool | None = None


def source_dir() -> Path:
    return config.APP_ROOT / "demo" / "minimal"


def target_dir() -> Path:
    return config.LOCAL_DIR / "demo" / NAME


def is_complete(target: Path) -> bool:
    return (target / ".git" / COMPLETE).is_file()


def ensure_demo(target: Path | None = None) -> Path | None:
    """The demo project's folder, materialized first if it does not exist or a build was interrupted; None when git is
    missing, the source is missing, the build failed (once per process) or the folder holds something else."""
    target = Path(target) if target is not None else target_dir()
    if is_complete(target):
        return target
    if str(target) in _FAILED or not _git_works() or not source_dir().is_dir():
        return None
    with _LOCK:
        if is_complete(target):
            return target
        if target.exists():
            if not (target / ".git" / BUILDING).exists() and any(target.iterdir()):
                log.warning("%s exists and is not a Research Deck demo; leaving it alone", target)
                _FAILED.add(str(target))
                return None
            shutil.rmtree(target)          # an interrupted build of ours
        try:
            build(source_dir(), target)
        except Exception:  # noqa: BLE001 — the dashboard works without its demo
            log.exception("could not materialize the demo project in %s", target)
            shutil.rmtree(target, ignore_errors=True)
            _FAILED.add(str(target))
            return None
    return target


# ---------------------------------------------------------------- git

def _git_works() -> bool:
    global _GIT_OK
    if _GIT_OK is None:
        try:
            _GIT_OK = shutil.which("git") is not None and subprocess.run(
                ["git", "--version"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _GIT_OK = False
    return _GIT_OK


def _git(root: Path, *args: str, when: str | None = None) -> str:
    """git with no user or system config (hooks, signing, filters, excludes and templates never apply) and the demo's
    fixed identity; `when` pins the author and committer dates."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    name, email = AUTHOR
    cmd = ["git", "-C", str(root), "-c", f"user.name={name}", "-c", f"user.email={email}", "-c", "commit.gpgsign=false",
           "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false", "-c", "core.excludesFile=/dev/null", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, env=env, timeout=60,
                          stdin=subprocess.DEVNULL).stdout


def _commit(root: Path, paths: list[str], when: str, message: str) -> str:
    _git(root, "add", "--", *paths)
    _git(root, "commit", "-q", "--no-verify", "-m", message, when=when)
    return _git(root, "rev-parse", "HEAD").strip()


# ---------------------------------------------------------------- the build

def _source_files(src: Path) -> dict[str, bytes]:
    out = {}
    for p in sorted(src.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store" and p.suffix != ".pyc":
            out[p.relative_to(src).as_posix()] = p.read_bytes()
    return out


def _write(root: Path, rel: str, data: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def _at_stage(files: dict[str, bytes], label: str, rel: str) -> bytes:
    data = files[rel]
    for final, earlier in EARLIER.get((label, rel), []):
        text = data.decode("utf-8")
        if text.count(final) != 1:
            raise ValueError(f"demo/minimal/{rel} no longer contains the text its {label} version replaces")
        data = text.replace(final, earlier).encode("utf-8")
    return data


def build(src: Path, dst: Path) -> dict:
    """Materialize the demo from `src` into the new folder `dst`; returns {commit label: sha}."""
    from .dag import seed   # noqa: PLC0415 — the DAG engine is only needed while building

    files = _source_files(src)
    code = {r for r in files if not r.startswith(".research/")}
    staged = [r for label, _, _, paths in HISTORY if label != "c4" for r in paths]
    if sorted(staged) != sorted(code) or len(set(staged)) != len(staged):
        raise ValueError(f"demo.HISTORY does not list every file of {src} exactly once: "
                         f"{sorted(set(code) ^ set(staged))}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _git(dst.parent, "init", "-q", "-b", "main", dst.name)
    (dst / ".git" / BUILDING).write_text("", encoding="utf-8")
    for rel, data in files.items():            # Research Deck's seed files; committed last (c5)
        if rel.startswith(".research/"):
            _write(dst, rel, data)
    _write_dag_config(dst)
    records = {p.stem: read_json(p) for p in sorted((dst / ".research" / "experiments").glob("*.json"))}

    shas: dict[str, str] = {}
    story = Story(dst, records)
    with seed.clock(HISTORY[0][1]) as clk:
        story.clk = clk
        for label, when, message, paths in HISTORY:
            for rel in paths:
                _write(dst, rel, _at_stage(files, label, rel) if label != "c4" else files[rel])
            shas[label] = _commit(dst, paths, when, message)
            getattr(story, label)(shas[label])
    _link_records(dst, records, story.run_ids, shas)
    write_text_atomic(dst / ".research" / ".gitignore", RESEARCH_GITIGNORE)
    label, when, message = RESEARCH_COMMIT
    union = [".gitattributes"] if (dst / ".gitattributes").is_file() else []   # the DAG's merge=union lines
    shas[label] = _commit(dst, [".research", *union], when, message)

    rel, old, new = WORKTREE_EDIT                  # the uncommitted change the Coding panel shows
    text = (dst / rel).read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"demo/minimal/{rel} no longer contains the line the working-tree edit extends")
    (dst / rel).write_text(text.replace(old, new), encoding="utf-8")

    write_json(dst / ".git" / COMPLETE, {"version": VERSION, "commits": shas})
    (dst / ".git" / BUILDING).unlink()
    return shas


def _write_dag_config(dst: Path) -> None:
    """A complete config.yaml, so neither the user's dag_defaults nor future engine defaults change the demo's files."""
    from .dag.store import DEFAULT_CONFIG, deep_merge   # noqa: PLC0415
    cfg = deep_merge(DEFAULT_CONFIG, {
        "code": {"roots": ["toycache", "figures"], "exclude": ["**/*.md", "**/test_*.py"]},
        "config": {"roots": ["configs"], "ignore_keys": ["log_level"]},
        "env": {"key": ["python", "gpu_model", "gpu_count"], "lockfile": None},
    })
    write_yaml(dst / ".research" / "dag" / "config.yaml", cfg)


def _link_records(dst: Path, records: dict[str, dict], run_ids: dict[str, str], shas: dict[str, str]) -> None:
    """node_id, cell, run_id, code commit and footprint into .research/experiments/*.json; node ids into figures.json."""
    from .dag.fp import cell_id   # noqa: PLC0415
    when = {"baseline-lru": "c1", "baseline-lfu": "c2", "lookahead": "c3"}
    for eid, rec in records.items():
        if eid in RUNS:
            nid, cell, reads, _ = RUNS[eid]
            rec.update(node_id=nid, cell=cell_id(cell) if cell else None, run_id=run_ids[eid],
                       code={"commit": shas[when[eid]], "footprint": reads})
        elif eid in PLANNED:
            rec["node_id"] = PLANNED[eid]
        write_json(dst / ".research" / "experiments" / f"{eid}.json", rec)
    path = dst / ".research" / "figures.json"
    doc = read_json(path)
    for f in doc["figures"]:
        f["node_id"] = FIGURES.get(f["id"], f.get("node_id"))
    write_json(path, doc)


# ---------------------------------------------------------------- the research story, commit by commit

def T(en: str) -> dict:
    return {"en": en}


def J(value) -> dict:
    return {"type": "json", "value": value}


def out(nid: str, name: str, sel: str = "") -> str:
    return f"node:{nid}#out.{name}" + (f"[{sel}]" if sel else "")


def basis(addr: str) -> dict:
    return {"type": "basis", "to": addr}


def cites(nid: str) -> dict:
    return {"type": "cites", "to": f"node:{nid}"}


def evidence(addr: str, *, predicate: tuple | None = None, kill_if: tuple | None = None, polarity: str = "supports") -> dict:
    e = {"type": "evidence", "to": addr, "polarity": polarity}
    for key, p in (("predicate", predicate), ("kill_if", kill_if)):
        if p:
            e[key] = {"agg": p[0], "op": p[1], "rhs": p[2]}
    return e


def run_id(eid: str, started: str) -> str:
    t = datetime.fromisoformat(started.replace("Z", "+00:00"))
    return f"r-{t:%Y%m%d-%H%M}-{hashlib.sha1(eid.encode()).hexdigest()[:4]}"


def _hours(a: str, b: str) -> float:
    return round((datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00")))
                 .total_seconds() / 3600, 2)


class Story:
    """What the researcher did in the DAG while each commit was HEAD (methods c1 … c4, called right after the commit)."""

    def __init__(self, root: Path, records: dict[str, dict]):
        from .dag import seed   # noqa: PLC0415
        self.seed, self.root, self.records = seed, root, records
        self.s = None
        self.clk = None
        self.run_ids: dict[str, str] = {}

    def at(self, t: str) -> None:
        self.clk.set(t)

    def add(self, nid: str, kind: str, **kw) -> None:
        self.seed.add(self.s, nid, kind, actor=HUMAN, **kw)

    def apply(self, ops: list[dict]) -> None:
        self.seed.apply(self.s, ops, HUMAN)

    def run(self, eid: str, sha: str) -> None:
        """The run behind an experiment record: its trace fingerprints the files it read at `sha`."""
        rec = self.records[eid]
        nid, cell, reads, keys = RUNS[eid]
        self.at(rec["finished_at"])
        rid = run_id(eid, rec["started_at"])
        gpus = int((rec.get("target") or {}).get("gpus") or 0)
        metrics = {k: v for k, v in (rec.get("metrics") or {}).items() if isinstance(v, (int, float))}
        self.seed.record(self.s, nid, cell, reads=reads, cfg_keys=keys, commit=sha, outputs=metrics, run_id=rid,
                         started=rec["started_at"], ended=rec["finished_at"], experiment=eid,
                         gpu_hours=round(_hours(rec["started_at"], rec["finished_at"]) * gpus, 2))
        self.run_ids[eid] = rid

    # ------------------------------------------------------------ c1: the LRU baseline
    def c1(self, sha: str) -> None:
        self.at("2026-10-05T14:10:00Z")
        self.s = self.seed.store(self.root)
        self.seed.env(self.s, "workstation", {"python": "3.12", "gpu_model": "GPU-24GB", "gpu_count": 1}, via="demo")
        self.seed.env(self.s, "cloud-a100", {"python": "3.12", "gpu_model": "A100 40GB", "gpu_count": 1},
                      usd_per_gpu_hour=1.2, via="demo")
        self.add("prob.hit-rate", "problem", status="confirmed", reason="framing of the project",
                 title=T("A small GPU block cache misses most requests when the hot set moves"),
                 facets={"statement": "A 64-block cache in front of host memory serves too few requests from the GPU "
                                      "when the set of popular blocks keeps moving.",
                         "scope": J({"trace": "synthetic: 20,000 requests over 1,024 blocks, hot set moves every 2,000",
                                     "cache_blocks": 64}),
                         "success": J({"metric": "hit_rate", "threshold": 0.5, "direction": "higher"}),
                         "kill_criteria": "Stop if no policy that uses only what the serving queue already knows "
                                          "reaches a hit rate of 0.5 at 64 blocks."})
        self.add("ref.lru", "reference", title=T("Least-recently-used replacement"),
                 facets={"citation": J({"bibkey": "lru", "note": "textbook algorithm"}), "role": J("baseline"),
                         "takeaway": "Evicts the block unused for the longest time. Cheap and quick to follow a moving "
                                     "hot set, but it cannot tell a block that returns soon from one that never returns."})
        self.add("ref.offline-opt", "reference", title=T("Offline optimal replacement"),
                 facets={"citation": J({"bibkey": "opt-replacement", "note": "textbook algorithm"}), "role": J("theory"),
                         "takeaway": "With the whole future known, evicting the block whose next use is farthest away "
                                     "minimizes misses. A serving queue knows a short window of that future."})
        self.add("exp.baseline", "experiment", purpose="profile", title=T("Baseline eviction policies at 64 blocks"),
                 facets={"spec": J({"command": "python -m toycache.sim --config configs/base.yaml",
                                    "config": ["configs/base.yaml"], "sweep": {"policy": ["lru"]},
                                    "platform": "workstation", "gpus": 1, "replicates": 1, "est_hours": 0.1}),
                         "outputs": J({"hit_rate": {"from": "experiments/results/baseline.csv[policy=<cell>].hit_rate",
                                                    "tol": {"abs": 0.01}}})},
                 edges=[basis("node:prob.hit-rate#statement"), cites("ref.lru")])
        self.run("baseline-lru", sha)
        self.at("2026-10-05T15:30:00Z")
        lru = out("exp.baseline", "hit_rate", "policy=lru")
        self.add("find.lru-low", "finding", status="confirmed", reason="exp.baseline: LRU hits 0.41 at 64 blocks",
                 title=T("LRU hits only 0.41 of the requests at 64 blocks"),
                 facets={"statement": "With 64 blocks LRU serves {{lru}} of the requests from the cache, short of the "
                                      "0.5 target: the hot set moves before recency can settle on it.",
                         "bindings": J({"lru": {"from": lru, "stated": 0.41, "fmt": "{:.2f}"}})},
                 edges=[evidence(lru, predicate=("max", "<", 0.5))])
        self.add("gap.queue-hint", "gap", status="confirmed", reason="find.lru-low and the offline optimum",
                 title=T("The serving queue knows the next requests, but LRU ignores them"),
                 facets={"statement": "The serving queue holds the next requests before they run, yet LRU evicts by the "
                                      "past alone. Offline optimal replacement hits 0.72 on the same trace.",
                         "headroom": J({"metric": "hit_rate at 64 blocks", "current": 0.41, "bound": 0.72,
                                        "ratio": 1.76})},
                 edges=[basis("node:find.lru-low#statement"), cites("ref.offline-opt")])

    # ------------------------------------------------------------ c2: attempt A (LFU), refuted
    def c2(self, sha: str) -> None:
        self.at("2026-10-12T14:05:00Z")
        self.add("sol.lfu", "solution", alt_group="gap.queue-hint", title=T("Attempt A: least-frequently-used eviction"),
                 facets={"mechanism": "Evict the cached block with the fewest requests so far, so popular blocks stay.",
                         "expected_gain": J({"metric": "hit_rate", "target": 0.5}),
                         "assumptions": J(["popularity is skewed enough that past counts predict the next requests"]),
                         "code": J({"path": "toycache/lfu.py", "symbol": "LFUCache"})},
                 edges=[basis("node:gap.queue-hint#statement")])
        self.at("2026-10-12T14:10:00Z")
        spec = dict(self.seed.current(self.s).nodes["exp.baseline"]["facets"]["spec"]["value"])
        self.seed.edit(self.s, "exp.baseline", {"spec": J({**spec, "sweep": {"policy": ["lru", "lfu"]}})}, actor=HUMAN,
                       notes="Attempt A runs in the same harness: one more value of the policy sweep.")
        self.run("baseline-lfu", sha)
        self.at("2026-10-12T15:00:00Z")
        self.apply([{"op": "link", "node": "sol.lfu",
                     "edge": evidence(out("exp.baseline", "hit_rate", "policy=lfu"), kill_if=("max", "<", 0.45),
                                      polarity="refutes")},
                    {"op": "set_status", "node": "sol.lfu", "to": "refuted",
                     "reason": "exp.baseline: LFU hits 0.37 at 64 blocks, below LRU (0.41) and the 0.45 kill line; "
                               "its counts still favor blocks that were popular before the hot set moved."}])

    # ------------------------------------------------------------ c3: attempt B (lookahead), chosen; paper and figure
    def c3(self, sha: str) -> None:
        self.at("2026-10-19T14:05:00Z")
        self.add("sol.lookahead", "solution", alt_group="gap.queue-hint",
                 title=T("Attempt B: lookahead eviction over the queued requests"),
                 facets={"mechanism": "On a miss, evict the cached block whose next request among the next W queued "
                                      "requests is farthest away; a block the window never asks for goes first.",
                         "expected_gain": J({"metric": "hit_rate", "target": 0.5}),
                         "assumptions": J(["the scheduler can show the cache its next W requests",
                                           "W = 8 separates the blocks that return soon from the rest"]),
                         "code": J({"path": "toycache/lookahead.py", "symbol": "LookaheadCache"})},
                 edges=[basis("node:gap.queue-hint#statement"), cites("ref.offline-opt")])
        self.add("exp.lookahead", "experiment", purpose="validate", title=T("Attempt B: lookahead eviction, window 8"),
                 facets={"spec": J({"command": "python -m toycache.sim --config configs/base.yaml "
                                               "--config configs/lookahead.yaml",
                                    "config": ["configs/base.yaml", "configs/lookahead.yaml"],
                                    "platform": "workstation", "gpus": 1, "replicates": 1, "est_hours": 0.12}),
                         "outputs": J({"hit_rate": {"from": "experiments/results/lookahead.csv[window=8].hit_rate",
                                                    "tol": {"abs": 0.01}}})})
        self.run("lookahead", sha)
        self.at("2026-10-19T15:00:00Z")
        ours = out("exp.lookahead", "hit_rate")
        self.apply([{"op": "link", "node": "sol.lookahead", "edge": evidence(ours, predicate=("min", ">=", 0.5))},
                    {"op": "set_status", "node": "sol.lookahead", "to": "confirmed",
                     "reason": "exp.lookahead: 0.58 at 64 blocks, above the 0.5 target."}])
        self.at("2026-10-19T15:10:00Z")
        self.add("dec.policy", "decision", status="confirmed", reason="attempt B validated; attempt A refuted",
                 title=T("Eviction policy: lookahead (attempt B)"),
                 facets={"question": "Which eviction policy should toycache use?", "choice": J("sol.lookahead"),
                         "rejected": J([{"node": "sol.lfu",
                                         "reason": "Refuted by exp.baseline: 0.37 at 64 blocks, below LRU."}])},
                 edges=[basis("node:sol.lookahead#mechanism")])
        self.at("2026-10-19T15:20:00Z")
        self.add("design.cache", "design", status="confirmed", reason="follows dec.policy",
                 title=T("Cache design: lookahead eviction with LRU tie-breaking"),
                 facets={"policy": "On a miss, evict the cached block whose next request in the lookahead window is "
                                   "farthest away; blocks the window never asks for go in LRU order.",
                         "window": {"type": "bound", "bind": "configs/lookahead.yaml#lookahead.window"},
                         "capacity": {"type": "bound", "bind": "configs/base.yaml#cache.capacity_blocks"}},
                 edges=[basis("node:dec.policy#choice")])
        self.at("2026-10-19T15:25:00Z")
        self.add("mod.policies", "module", title=T("Eviction policies"),
                 facets={"globs": J(["toycache/lru.py", "toycache/lfu.py", "toycache/lookahead.py"]),
                         "src": {"type": "derived"}},
                 edges=[{"type": "implements", "to": "node:design.cache#policy"}],
                 notes="One module per policy; the simulator loads the one the config names.")
        self.at("2026-10-19T15:40:00Z")
        self.add("fig.hit-rate", "figure", stage="W", title=T("Figure 1: hit rate by eviction policy"),
                 facets={"spec": J({"command": "python figures/fig_hit_rate.py", "gpus": 0, "replicates": 1}),
                         "outputs": J({"series": {"from": "figures/data/hit_rate.csv"}})},
                 notes="Plots figures/data/hit_rate.csv, copied from experiments/results/.")
        self.at("2026-10-19T15:41:04Z")
        series = {"lru": 0.41, "lfu": 0.37, "lookahead": 0.58}
        self.seed.record(self.s, "fig.hit-rate", "_", reads=FIG_READS, cfg_keys=[], env_keys=[], commit=sha,
                         outputs={"series": {"value": series}}, run_id=run_id("fig.hit-rate", "2026-10-19T15:41:00Z"),
                         started="2026-10-19T15:41:00Z", ended="2026-10-19T15:41:04Z", gpu_hours=0)
        self.at("2026-10-19T16:00:00Z")
        lru = out("exp.baseline", "hit_rate", "policy=lru")
        self.add("claim.hit-rate", "claim", stage="W", title=T("Lookahead eviction beats LRU at 64 blocks"),
                 facets={"role": J("result"),
                         "text": "Lookahead eviction raises the hit rate at 64 blocks from {{lru}} (LRU) to {{ours}}.",
                         "bindings": J({"lru": {"from": lru, "stated": 0.41, "fmt": "{:.2f}"},
                                        "ours": {"from": ours, "stated": 0.61, "fmt": "{:.2f}"}})},
                 edges=[evidence(ours, predicate=("min", ">=", 0.5)), evidence(out("fig.hit-rate", "series"))],
                 notes="Stated in paper/main.md, section 4.")
        self.at("2026-10-19T16:10:00Z")
        self.add("exp.window-sweep", "experiment", purpose="sensitivity", title=T("Sensitivity to the lookahead window"),
                 facets={"spec": J({"command": "python -m toycache.sim --config configs/base.yaml "
                                               "--config configs/lookahead.yaml",
                                    "config": ["configs/base.yaml", "configs/lookahead.yaml"],
                                    "sweep": {"lookahead.window": [4, 16, 32]},
                                    "platform": "cloud-a100", "gpus": 1, "replicates": 1, "est_hours": 0.2}),
                         "outputs": J({"hit_rate": {"from": "experiments/results/window_sweep.csv[window=<cell>].hit_rate",
                                                    "tol": {"abs": 0.01}}})},
                 edges=[basis("node:design.cache#policy")], notes="Planned: no run yet.")

    # ------------------------------------------------------------ c4: the code catches up with the design
    def c4(self, sha: str) -> None:
        """No DAG op: changing lookahead.py is enough for the engine to mark exp.lookahead stale."""
