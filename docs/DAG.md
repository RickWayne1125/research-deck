# Research DAG spec v1

Code: `server/research_deck/dag/` (backend), `web/src/panels/dag/` (the map) and `web/src/panels/overview/` (Today). Per-project state lives in `<project>/.research/dag/`; `projects.init_research_dir` creates that folder.

**How it works.** A research project is treated as a build graph.
- **Action nodes** produce data: experiments (one cell per sweep point) and scripted figures. They are cached build actions. A run stays valid as long as every input it actually read still has the same content fingerprint. Those inputs are code files, config keys, dataset versions, environment keys and upstream outputs.
- **Belief nodes** hold reasoning: findings, gaps, solutions, decisions, designs, modules, claims, sections and drawn figures. On each edge they record the fingerprint they last saw. Evidence edges carry predicates, and these are re-checked on every evaluation.
- **Status** is what we decided. It is stored, and humans control the important transitions. **Freshness** is whether that decision still holds. It is derived and never stored.
- Every change, whether from a human, Codex or Claude, goes through one op engine. The impact preview is computed first.

---

## 0. Scorecard

Weights: invalidation correctness 35%, agent/git legibility 20%, implementability in about 1,500 LOC 25%, UI clarity for the four questions 20%.

| | A: RBG (build graph) | B: ProvLedger (event log) | C: Research Ledger |
|---|---|---|---|
| Invalidation correctness | **9**: reuse follows what each run actually read; per-cell; any past run can verify again; early cutoff | 6.5: fingerprints hash declared glob trees and declared design facets, so edits to unused files or reworded prose cause reruns; agents can claim "editorial" and so hide a real change | 7: declared globs plus observed imports, so unused declared files cause reruns and `open()` reads are not seen; prose design facets are hard inputs; one run covers a whole sweep |
| Legibility for agents and git | 7: one YAML per node, but facet_fps add noise; HMAC; custom merge driver | 5: the log is the source of truth and the node files are generated views; `merge=ours` plus required hooks; every change shows up in two diffs | **9**: small YAML per node, `seen` stored on edges, `$bind` to config, short ids |
| Implementability (~1.5k LOC) | 6: Keychain HMAC, merge driver, TrackingDict and 14 kinds go over budget | 4.5: reducers, replay, upcasters, materializer, union-find, hooks | **8**: the simplest algorithm; the budget is realistic |
| UI clarity (4 questions) | 7: rich visual encodings, but none of the views answers one question directly | 7: History view, evidence matrix, already-tried | **9**: four lenses that map one-to-one onto the user's questions; near-miss "reused because…" |
| **Weighted** | **7.45** | **5.80** | **8.05** |

**Defects I would block in review**
- **A**:
  1. Its validator rejects cycles over HARD ∪ SOFT edges, but its own pipeline creates `exp →basis→ sol →evidence→ exp#out` (S3.3), so every validation experiment would be refused.
  2. Predicates are re-checked only when a fingerprint changes. With early cutoff, a value can drift within tolerance from 2.02 to 1.98, the fingerprint stays the same, and `min >= 2.0` silently fails. That is a false "still valid".
  3. `verify` checks the environment of `run.platform`, not the spec's target platform. A run on an A100 can therefore satisfy an L4 spec.
  4. Files under the config roots are always excluded from `code:`. If code opens a YAML file outside the declared chain, that read is invisible.
  5. In fallback config mode it records only leaves, so a newly added key that the code reads with a default is missed.
  6. Evaluation writes back re-verified edges, which causes git churn and races.
- **B**: Declared `core: src/tempo/engine/**` tree hashes force a rerun on any engine edit. Design prose is a hard input to experiments. The editorial union-find is a false-valid channel. Generated views plus `merge=ours` break whenever the hooks are not installed. Undeclared traced files are compared by raw blob, so editing a comment invalidates.
- **C**: `consumes: D2#policy` makes rewording a design trigger a rerun. One run per experiment means one bad cell or one new sweep value reruns the whole sweep. Non-import reads are missed unless they fall inside the include globs.

**What v1 takes**
- **Core engine from A.** Facet addresses; dynamic run traces (audit hook plus `sys.modules`, config reads, env probes, datasets); fingerprints that depend on content, never on commit SHAs; every past run verified per sweep cell, so a rollback revives old runs; anchor-based early cutoff; hard/soft edge split with soft review that does not chain onward; status kept separate from freshness; a git snapshot ref per run; impact computed by evaluating twice over an overlay, with predicted vs exact precision; paper numbers through macros; cost and why-paths.
- **Skeleton from C.**
  - One small YAML per node, with the recorded fingerprint (`seen`) on each edge and no per-facet fingerprints in the file.
  - The **four lenses**.
  - `$bind` design knobs to config keys, which makes knob previews exact.
  - Near-miss "reused because…" explanations.
  - **Rollback closure** suggestions.
  - `touch_code` predictions and predicted-vs-actual.
  - The "safe" rule for auto-applying agent changes.
  - Stated-number tolerance.
  - Computed gates (not gate nodes), and the eval matrix.
- **From B.** The `impl_lag` flag ("implement first"), `already_tried` detection, rerun waves, fingerprints recomputed on the machine that ran the job, a reason on every human verdict, the light `shaky` inherited flag, pre-registered kill criteria, claims written before evaluation, baseline-reproduction and oracle stages.
- **New in v1 (judge's fixes).**
  - Predicates are checked on every evaluation against actual values.
  - Environment is checked against the spec's target platform.
  - Config files outside the declared chain are traced as code.
  - Fallback config mode records a key-set fingerprint.
  - Directory listings made by user code are traced (`dir:`).
  - Python fingerprints are token-normalized, which is stable across interpreter versions.
  - Evaluation is pure, with no write-backs.
  - Acyclicity is enforced on `input` edges only, and evaluation runs in passes.
  - Refutations are frozen to immutable `run:` addresses.
  - Files a run wrote itself are excluded from its reads.

---

## 1. Refined research pipeline

The user's four steps are kept. S0–S1 = "Draft idea", S2–S4 = "Motivation and insights", S5 = "System design", S6 = "Evaluation". Writing (W) runs throughout.

| user step | stage | sub-steps (node kinds produced) |
|---|---|---|
| 1.1 identify the general problem | **S0 Frame / 问题定义** | 0.1 `problem` (statement, scope: workloads, models, hardware); 0.2 target metric and success threshold (json, used by predicates); 0.3 **kill criteria written down before any work** (new) |
| 1.2 search references | **S1 Landscape and baselines / 相关工作与基线** | 1.1 `reference` nodes, each with a role (related, baseline, competitor, theory, module, benchmark) and a takeaway; 1.2 a "delta vs us" for the 3 closest works; 1.3 choose baselines and `dataset` nodes; 1.4 **reproduce the baselines** with `experiment` purpose=reproduce (new: profiling a misconfigured baseline produces fake opportunities) |
| 2.1.1 preliminary experiments, profiling | **S2 Characterize / 现象刻画** | 2.1 pre-register hypotheses as `finding` nodes in status `proposed`, each with a predicate; 2.2 profiling experiments (purpose=profile) on ≥2 workloads or platforms |
| 2.1.2 analyze to find opportunities | S2 (cont.) | 2.3 analysis (purpose=analysis) moves findings to confirmed or refuted |
| 2.2.1 identify performance gaps | **S3 Opportunity / 机会与差距** | 3.1 **oracle/limit study** (purpose=oracle) produces a `gap` with quantified headroom (new: it bounds the gain before anything is built) |
| 2.2.2 related work with theory or modules | S3 (cont.) | 3.2 references with role theory or module, each with a "reuse" note |
| 2.2.3 draft solutions | **S4 Solution exploration / 方案探索** | 4.1 at least 2 `solution` siblings in one `alt_group`, each with mechanism, expected gain, assumptions and **kill_if predicates** |
| 2.2.4 validate draft solutions | S4 (cont.) | 4.2 cheap validation (purpose=validate: simulator, prototype or oracle injection); 4.3 a `decision` chooses one solution, the losers become refuted or abandoned with reasons (kept); 4.4 **draft the `claim` nodes now** (claims first, new) |
| 3 System design | **S5 Design and implementation / 系统设计与实现** | 5.1 `design` with one facet per decision, knobs `$bind`-ed to config keys; 5.2 `module` nodes map code globs to the design facets they implement; 5.3 agents implement on branches/worktrees, with an exact impact preview for every commit; 5.4 microbenchmarks (purpose=microbench) |
| 4 Evaluation | **S6 Evaluation / 评估** | 6.1 eval matrix: each claim × {end-to-end, ablation, sensitivity, overhead, generality} × workloads × platforms; 6.2 campaign (reused cells skipped); 6.3 scripted figures and macros |
| (throughout) | **W Writing / 写作** | `section` nodes are created automatically from tex markers and get `describes` edges to claims, figures and design facets. S0–S3 feed the intro and motivation, S4–S5 the design, S6 the evaluation. Refuted solutions feed the discussion and "why not X". |

**Gates.** Gates are computed checklists, not nodes. Their thresholds live in `config.yaml`. They are advisory by default (`gates.blocking: false`). A human passes a gate. That act logs a `gate_passed` event and creates the snapshot `gate-Gk`.

| gate | after | checks (each turns green or red live) |
|---|---|---|
| G1 worth pursuing | S1 | problem confirmed; ≥5 references, including ≥2 competitors with a delta; each reproduce experiment fresh and within `baseline_repro_tol` (10%), or a finding that explains the gap |
| G2 issue is real | S2 | ≥1 confirmed finding with fresh evidence on ≥`min_workloads` (2) workloads, n ≥ 3 replicates |
| G3 go / no-go | S3 | ≥1 confirmed gap with headroom ≥ `min_headroom` (1.3×); no competitor reference marked `closes_gap` |
| G4 commit to an approach | S4 | decision locked; ≥2 alternatives tried, each with a verdict; the validation of the chosen solution captures ≥ `min_captured` (50%) of the headroom; claims drafted |
| G5 design frozen | S5 | design confirmed or locked; no module `implements` edge in review; microbenchmarks fresh and ≥ `microbench_vs_proto` (80%) of the prototype gain |
| G6 claims hold | S6 | every live claim fresh with its predicate holding; every figure fresh; no stale or unbuilt cell in any claim's evidence closure |
| G7 submission | W | G6, plus no section in review; snapshot `submit-<venue>`; claims, figures and design locked |

**Loop-backs.** A failed gate or a broken claim never rewrites history. The agent proposes one of three things: a new node whose `basis` is the failing evidence, an edit with an impact preview, or a rollback. Dead nodes stay visible in the Tried lens. A gate that later loses a check shows `passed-degraded`.

---

## 2. Entities

### 2.1 Common fields

- **Node id.** `<prefix>.<slug>`. The prefixes are `prob ref data exp find gap sol dec design mod fig claim sec`. Slugs are chosen by their author, which keeps ids merge-safe. Any id used in tex or chat is the full id.
- **Fields on every node** (not hashed): `id, kind, stage (S0..S6|W), title {en, zh}, status, head {rev, vid, fp}, notes, created, updated`.
- **Hashed fields**: `facets` (hashed one facet at a time).
- **Structural fields**: `edges`, `alt_group`, `superseded_by`, `lock`.

**Facet types**

| type | canonicalization |
|---|---|
| `prose` | NFC, LF line endings, whitespace runs collapsed |
| `text` | NFC, LF, rstrip |
| `json` | sorted keys, compact; floats via `repr` |
| `bound` | `{bind: "file#dotted.key"}`; the value and fingerprint are those of the resolved config leaf or subtree |
| `artifact` | sha256 of the file |
| `derived` | computed: module `src`, dataset `version`, section `text` |

### 2.2 Node kinds

| kind | stage | facets | action? | example |
|---|---|---|---|---|
| problem | S0 | statement (prose), scope (json), success {metric, threshold, direction} (json), kill_criteria (prose) | no | `prob.tail-ttft` |
| reference | S1, S3 | citation {bibkey, venue, year, url}, role, takeaway (prose), delta (prose), closes_gap (bool) | no | `ref.sarathi-serve` role=baseline |
| dataset | S1 | version (derived: manifest Merkle `m:` or `hf:<repo>@<rev>`), subtype (dataset, trace, model), schema | no | `data.sharegpt-v3` |
| experiment | by purpose: reproduce, profile, analysis → S1/S2; oracle → S3; validate → S4; microbench → S5; eval, ablation, sensitivity, overhead → S6 | purpose, spec (json, §6), outputs (json: metric specs, tol, derive) | **yes, per cell** | `exp.e2e-sharegpt`: 3 systems × 3 rates = 9 cells |
| finding | S2 | statement (prose with `{{name}}`), bindings (json) | no | `find.prefill-stall`: decode TPOT p99 rises 3.1× when a ≥2k-token prefill is co-scheduled |
| gap | S3 | statement, headroom {metric, current, bound, ratio} | no | `gap.interference`: 1.8× |
| solution | S4 | mechanism (prose), expected_gain (json), assumptions (json list), cost_risk (prose); `alt_group` | no | `sol.chunk-budget` (confirmed), `sol.mlfq` (refuted) |
| decision | S4–S5 | question (prose), choice (node id), rejected [{node, reason}] | no | `dec.sched-approach` (locked) |
| design | S5 | one facet per design decision (prose, json or bound) | no | `design.sched`: policy, preemption, chunk (bound), budget_slack_ms (bound) |
| module | S5 | globs (json), opaque (bool: compiled or JIT code the tracer cannot see), src (derived) | no | `mod.sched` → `src/lookahead/sched/**`; feeds the Coding panel's `ArchComponent.node_id` |
| figure | S2–S6 | scripted: spec {script, inputs, style, format}, outputs (artifact). drawn: tool (drawio, omnigraffle), file (artifact) | **scripted only** | `fig.e2e-latency` (scripted), `fig.arch` (drawn) |
| claim | S4 → S6 | text (prose with `{{name}}`), role (contribution, motivation, result, limitation), bindings | no | `claim.ttft-2x` |
| section | W | file, text (derived from the region between `% rd:sec <id>` and `% rd:end`) | no | `sec.design` → `paper/sections/design.tex` |

A `finding` in status proposed or active **is** a pre-registered hypothesis. Confirming it makes it a finding; refuting it records the negative result.

### 2.3 Edges (consumer → upstream; one edge per `(type, to)`)

| edge | from → to | stored on the consumer | upstream change → consumer |
|---|---|---|---|
| `input` (hard) | action → `node:<action>#out.<name>[sel]`, `node:<dataset>` | `{type, to}`; fingerprints live in each run's trace | trace mismatch → cell `stale`; upstream cell not fresh → `pending`; upstream dead → `orphaned` |
| trace items (hard, not edges) | run → `code:` `dir:` `cfg:` `data:` `env:` | in the run record | any mismatch → cell `stale` |
| `evidence` (checked) | belief → `node:<action>#out.<name>[sel]` or `run:<id>#out.<name>` | `seen`, `polarity` (supports, refutes), `predicate` or `kill_if` | predicate **re-checked on every evaluation**: fails → `broken`; holds with a new fp → fresh plus `drift` flag; no predicate and a new fp → `review`; upstream not fresh → `pending`; a `run:` target never changes |
| `basis` (soft) | belief or action → `node:<id>[#facet]` | `seen`, optional `pin: <vid>` | fp differs → `review`; upstream dead → `orphaned`; upstream broken → `review`. **Not transitive.** |
| `implements` (soft) | module → `node:<design>#<prose facet>` | `seen` | fp differs → module `review`, plus an `impl_lag` flag on every cell whose trace reads the module's files |
| `describes` (soft) | section or drawn figure → claim, figure, finding, design facet | `seen` (set when the anchor is written) | fp differs → `review`; target broken → `review` |
| `cites` (info) | any → reference | `{type, to}` | none, unless the reference is dead (retracted), which gives `review` |

Structural fields:
- `alt_group: <parent id>` marks siblings that answer the same question. At most one sibling per group may be confirmed or locked (for solutions and designs).
- `superseded_by: <id>`.

**Graph rules**
- `input` edges must form a DAG; this is enforced on write. `basis` edges among beliefs must also be acyclic, as a sanity check.
- Hard targets (`input` and `evidence`) are always action outputs or runs, so beliefs are sinks of the hard graph.
- Cycles that pass through an action and a belief are therefore allowed. A typical one is `exp.proto →basis→ sol →evidence→ exp.proto#out`. The staged evaluation in §4.5 handles them.
- Validator warnings:
  - `implements` pointing at a bound facet (knobs are realized by config; there is nothing to implement);
  - an experiment with a `basis` edge to a facet that its own outputs justify;
  - raw numbers in claim text outside `{{…}}`.

### 2.4 Lifecycle status (stored)

`proposed | active | confirmed | locked | refuted | abandoned | superseded`. DEAD = {refuted, abandoned, superseded}; dead nodes are never deleted.

| transition | human | agent (Codex/Claude) | preconditions |
|---|---|---|---|
| ∅ → proposed | yes | **yes** (agents create only proposed nodes) | id unique; schema valid; `input` graph stays acyclic |
| ∅ → active | yes | no | — |
| proposed → active | yes | yes, direct | — |
| active → confirmed | yes | proposal | level `fresh`, plus a rule per kind: finding or claim needs ≥1 supports edge whose predicate holds; solution needs validate evidence or a theory reference; decision needs a choice and a reason for each rejected sibling; experiment needs every cell fresh; ≤1 confirmed per alt_group |
| confirmed → locked | **human only** | no (not exposed via MCP) | fresh; writes a lock record and tag |
| locked → confirmed (unlock) | **human only** | proposal with `requires: [unlock:<id>]` | reason logged |
| confirmed → active | yes; automatic when a human edits a facet without `editorial: true` | proposal | — |
| proposed or active → refuted | yes | direct only on its own proposed node; otherwise proposal | reason, plus ≥1 evidence edge. On apply, `node:` evidence is **frozen to `run:` addresses** of the selected runs. |
| proposed, active or confirmed → abandoned | yes | direct only on its own proposed node; otherwise proposal | reason ∈ {infeasible, dominated, no_headroom, competitor_closed_gap, out_of_scope, cost, time, other}, plus a note |
| live, not locked → superseded | yes | proposal | `superseded_by` names a live node |
| dead → active (revive) | yes | proposal | reason |
| delete | proposed node with no dependents and no runs | its own such nodes | otherwise use abandoned |

Every human verdict (confirm, refute, abandon, supersede, revive, lock, unlock, gate pass, rollback) logs a `decision` event with `{reason, evidence, proposer, approver}`. This is a lightweight ADR. A `dec.*` node is needed only for choosing among alternatives.

### 2.5 Freshness (derived on every evaluation, never stored)

| level (order) | applies to | meaning | cleared by |
|---|---|---|---|
| `fresh` 0 | all | every recorded fp matches and every predicate holds | — |
| `review` 1 | beliefs; actions (ring only, cells unaffected) | a soft upstream changed or is broken; evidence without a predicate moved; a stated number is out of tolerance | `attest` (copies the current fp into `seen`) or an edit |
| `orphaned` 2 | all | an upstream it builds on is dead or missing | relink to the successor, revive the upstream, or retire this node |
| `pending` 3 | cells, beliefs | its own inputs match, but an upstream action cell is not fresh | rerun the upstream (it may clear through cutoff) |
| `unbuilt` 4 | cells | no succeeded run | run |
| `stale` 4 | cells | a traced input changed | rerun or roll back |
| `broken` 5 | beliefs | a predicate fails or a kill criterion is met | human only: revise text or predicate, refute, fix the harness and rerun, or exclude a bad run |

**Flags** never change the level:
- `drift`: evidence moved, but the predicate still holds.
- `shaky: [ids]`: something upstream through soft or evidence edges is not fresh. Shown as a light hint, "via X".
- `impl_lag`: the code read by this cell belongs to a module whose implements edge is in review.
- `reused`: the cell is valid through an older run.
- `cutoff`: the rerun landed within tolerance.
- `lock_alert`: a locked node that is not fresh.
- `unsealed`: the YAML was edited outside the API.
- `behind_head`: a pinned edge.
- `conflict`: a history fork after a merge.
- `trace_quality`: traced, declared or coarse.

An action node's level for the lenses is the max over its cells. Its soft-edge review shows only as a ring.

### 2.6 Run states

- `queued → running → succeeded | failed | cancelled | lost`. A scheduler's states map in directly; heartbeat loss maps to `lost`.
- A run is immutable once terminal.
- Only succeeded runs whose `excluded` flag is unset take part in reuse.
- A human may set `excluded {by, reason}`, for example for thermal throttling. A run flagged `code_mismatch` (the fps computed on the host differ from the dispatched snapshot) is valid only for what actually ran; its trace is the truth.

### 2.7 Ops and permissions

Every mutation is a list of ops, applied atomically.

```json
{"op":"create","node":{...}}
{"op":"edit","node":"design.sched","base_vid":"v-5c0e19a2","set":{"preemption":"..."},"unset":[],"editorial":false}
{"op":"config_edit","file":"configs/sched.yaml","key":"sched.chunk.max","value":4096}
{"op":"link","node":"claim.ttft-2x","edge":{"type":"evidence","to":"node:exp.e2e-sharegpt#out.ttft_speedup[system=ours]","predicate":{"agg":"min","op":">=","rhs":2.0}}}
{"op":"unlink","node":"claim.ttft-2x","edge":"evidence:node:exp.e2e-sharegpt#out.ttft_speedup[system=ours]"}
{"op":"set_status","node":"sol.mlfq","to":"refuted","reason":"...","evidence":["node:exp.proto-mlfq#out.p99_gain"]}
{"op":"attest","node":"mod.sched","edges":["implements:node:design.sched#preemption"]}
{"op":"rollback","node":"design.sched","to_vid":"v-5c0e19a2","edges":false}
{"op":"restore_snapshot","name":"gate-G5"}
{"op":"lock","node":"design.sched","reason":"design freeze"}
{"op":"select_run","node":"exp.overhead","cell":"_","run":"r-20261028-1530-0c3e"}
{"op":"exclude_run","run":"r-20261030-0912-77aa","reason":"GPU throttled at 83C"}
// preview-only ops: {"op":"touch_code","globs":["src/lookahead/sched/**"]}  {"op":"code","diff":"HEAD~1..HEAD"}
```

`editorial: true` means: after apply, auto-attest the direct soft dependents of the edited facets. Normal attest permissions apply. It never touches hard edges, because action results never depend on prose.

| op | agent direct | agent → proposal | human |
|---|---|---|---|
| create (as proposed) | yes | — | yes (proposed or active) |
| edit, link, unlink on proposed or active nodes | yes | — | yes |
| edit on confirmed | no | yes | yes (demotes to active unless editorial) |
| edit on locked | no | yes, `requires: [unlock:<id>]` | 409 until unlocked |
| config_edit | yes, if every node bound to the key is proposed or active | otherwise | yes |
| attest | on proposed or active nodes | on confirmed or locked nodes | yes |
| set_status | proposed → active; refute or abandon its own proposed nodes | everything else | yes |
| rollback | on proposed or active nodes | otherwise | yes |
| lock, unlock, approve, reject, gate pass, select_run, exclude_run, restore_snapshot | **never** (absent from MCP) | unlock and restore as proposals | yes |
| queue runs | live actions, no `impl_lag`, within `policy.agent_auto_run` (GPU-h/day, platforms) | over budget: a human click | yes (cloud runs need `confirm: true`) |
| record_run, render | `system` (runner, renderer) | — | — |

**Safe auto-apply.** An agent's op batch applies directly only when all of these hold:
- every op is "agent direct";
- the preview has zero lock hits;
- no op changes the status of a confirmed or locked node.

Otherwise the whole batch becomes one proposal.

---

## 3. Versioning, pins, git linkage, rollback

**Node versions**
- The head lives in `nodes/<id>.yaml`.
- Every applied change to facets, edges (including `seen`), status or lock appends one line to `history/<id>.jsonl`: `{vid, rev, parent, reverts?, fp, facets (full values), edges, status, by, at, git, op, via}`.
  - `rev` is the display ordinal.
  - `vid = "v-" + sha256(parent | fp | edges_digest | status | at | by)[:8]`.
  - `fp = fp_node` covers facets only. Status, title and notes never invalidate consumers; status acts only through the dead and broken rules.
- Two versions with identical facets share an fp. A rollback is therefore recognized everywhere automatically.

**Pins**
- An edge with `pin: <vid>` resolves to that version's fp. It never goes stale and shows `behind_head`.
- A cell's `selected` run override pins a run.
- Snapshots pin vids and runs.
- Consumers otherwise reference fps, never vids.

**Runs and git**
- At dispatch, the runner builds `refs/rd/runs/<run_id>`, a commit of the exact code-root contents including dirty and untracked-not-ignored files. It does this through a temporary index (`GIT_INDEX_FILE=… git read-tree HEAD && git add -A -- <roots> && git write-tree && git commit-tree -p HEAD`), then runs `update-ref`.
- The run record stores `{head, snapshot, dirty}` and a per-file blob SHA next to each fp.
- So every result's code can be recovered (`git worktree add /tmp/x refs/rd/runs/<id>`), and gc cannot remove it.
- **Cache keys never contain a commit SHA.** An unrelated commit, rebase or cherry-pick never invalidates anything.

**Autocommit**
- The backend commits only `git commit --only -- .research/dag paper/generated`, debounced 30 s after each event batch.
- Message: `dag: <summary>` with trailers `RD-Events: e-000412..e-000419` and `RD-Actor: agent:claude:46e445`.
- It never commits code. Agents and the user commit code; the dashboard only links commits.
- Autocommit runs only while the primary checkout is on `home_branch` (default `main`). Otherwise the UI shows a banner and holds commits; files are still written.

**Attempts**
- Alternatives are siblings in an `alt_group`, not git branches. An attempt that needs its own code sets `spec.code_ref: branch:rd/attempt/<id>` or `wt:<path>` on its action nodes.
- The resolver reads that branch's tree (`git ls-tree -r -z`) or that worktree's index plus dirty files. The DAG can therefore evaluate every alternative without a checkout, and the runner executes in a worktree.
- There is one DAG per project, living in the primary checkout. Agents working in worktrees write through the API (MCP), never to their worktree's `.research/`.
- When a decision picks a winner, its branch is merged. Losing branches are tagged `rd/attempt/<id>/final` before deletion, and their runs stay valid records against their own trees.

**Locks.** A lock record lives in the node YAML: `{by, at, vid, fp, edges_seen, runs: {cell: run_id}}`. It also creates the annotated tag `rd/lock/<id>/r<rev>`. Unlocking appends an `unlocked` history line and keeps the old record. HMAC signing is deferred to v2. In v1, `dag check` compares each locked node against its lock record and the history head.

**Snapshots.** `snapshots/<name>.yaml = {at, by, git, nodes: {id: vid}, runs: {"node/cell": run_id}, eval_digest}`. One is created automatically at each gate pass, and manually for milestones such as `submit-osdi27` (tag `rd/snap/<name>`).

**Rollback.** Always preview, then apply. Never destructive.
1. **Node**: `rollback {node, to_vid}` appends a new version with the target's facets and `reverts: <vid>`.
   - Its fp equals the target's, so every `seen` and every run trace recorded against that content matches again. Old evidence **revives** with no reruns.
   - `edges: true` also restores that version's edge records.
2. **Code**: the preview runs on `code: {diff: "HEAD..<commit>"}`, and the apply is `git revert <range>`, or a branch `rd/rollback/<name>` created from the commit.
   - Never `reset --hard`.
   - The approved agent performs the revert; the dashboard never runs destructive git commands.
   - The revived runs are exactly those whose traces match the restored blobs.
3. **Snapshot restore**: one proposal that contains a rollback op for every node whose vid differs, plus a code-rollback step and the snapshot's run selections.
4. **Rollback closure.** For each node that the rollback newly puts into `review`, the preview searches that node's history for the latest version whose edge `seen` values all equal the post-rollback fps. It then offers "restore mod.sched edges from r2".
5. **Run selection.** Each cell uses its **newest valid** run unless a human selected another valid one. An invalid run can never be selected.
6. **Materialization.** Figure files and `rdvalues.tex` are regenerated from the selected runs' stored artifacts and values. This takes zero compute, so a revived render restores the old PDF.

**Merges and time travel**
- `history/*.jsonl` and `log.jsonl` use `merge=union`. Run files have unique names and never conflict.
- `dag repair` regenerates `nodes/*.yaml` from history. Two history lines that share a parent mark the node `conflict`; the later one is materialized provisionally and a human resolves it.
- `GET /graph?at=<commit|snap:name>` loads `.research/dag` via `git show <c>:<path>` and resolves code with `git ls-tree <c>`. The result is a read-only DAG at any past point.

---

## 4. Facets, fingerprints, and the staleness/reuse algorithm

### 4.1 Addresses

```
addr := scheme ":" locator [ "#" facet [ "[" selector "]" ] ]
  node:<id>#<facet>                authored, bound or derived facet      node:design.sched#preemption
  node:<id>                        whole node (fp_node)                  node:sol.chunk-budget
  node:<id>#out.<name>[k=v,...]    action output table or slice          node:exp.e2e-sharegpt#out.ttft_p99[system=ours]
  run:<run_id>#out.<name>          immutable output of one run           run:r-20261101-2307-9e4d#out.tpot_ratio
  code:<repo path>                 one tracked or untracked-not-ignored file
  dir:<repo path>                  names in a directory listed by user code
  cfg:<dotted.key> | cfg:@keys     one resolved config leaf in the cell's context | the key set (fallback mode)
  data:<dataset id>                dataset version
  env:<key>                        python | gpu_model | gpu_count | driver_major | cuda | image | pkg:<dist>
```

### 4.2 Fingerprints

```python
FP_ALGO = "rd/1"                                              # stored on every run
def H(tag, b):        return f"{tag}:" + sha256(b"rd/1\0" + b).hexdigest()[:12]
def fp_json(v, t="json"): return H("s", canon(v, t))         # sorted keys, compact, NFC; prose collapses whitespace
def fp_file(path, data):
    if path.endswith(".py"):
        try: return H("p", py_tokens(data))                   # tokenize: drop COMMENT/NL, keep NEWLINE/INDENT/DEDENT,
        except (tokenize.TokenError, SyntaxError): pass       # join (type, string); stable across Python 3 versions
    return "g:" + git_blob_sha(data)[:12]                     # comments/formatting in .py never count; docstrings do
def fp_dir(names):    return H("d", "\n".join(sorted(names)))
def fp_table(cells):  return H("t", canon(sorted((cid, anchor_fp) for cid, anchor_fp in cells)))  # selector = subset
def fp_node(n):       return fp_json(sorted(facet_fps(n).items()))
MISSING = "∅"; UNKNOWN = Sentinel()                           # UNKNOWN never equals anything (predicted previews)
```

Blob → fp results are cached in `.cache/blobfp.sqlite`. A blob SHA is content, so each one is hashed once, ever.

### 4.3 Capturing what a run consumed (`rd-exec`, stdlib only, shipped to every host)

The job command becomes `python rd_exec.py --spec spec.json --cell '<json>' -- <command>`. `rd-exec` does five things:
1. Sets `RD_CELL` and `RD_OVERRIDES`. Sweep keys are dotted config keys, and `rd.cfg()` applies them.
2. Prepends `rd_trace/` to `PYTHONPATH`, so every Python process (vLLM engine-core, Ray, multiprocessing) loads the hook.
3. Probes the environment.
4. Runs `replicates` times and extracts outputs.
5. Writes `rd_run.json`. The experiments slice fetches it and POSTs it to `/dag/runs`.

```python
# rd_trace/sitecustomize.py  (chains to any pre-existing sitecustomize; re-entrancy guarded)
def hook(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        p = realpath(args[0]); writing = mode_or_flags_write(args[1], args[2])
        first_seen(("W" if writing else "R"), p)              # appended line-buffered to trace.<pid>.jsonl at once,
    elif event in ("os.listdir", "os.scandir", "glob.glob"):  # so os._exit (fork children) loses nothing
        if caller_module() not in IMPORT_MACHINERY: first_seen("L", realpath(args[0] or "."))
    elif event == "subprocess.Popen":
        first_seen("X", json.dumps(list(map(fspath, args[1] or []))))
sys.addaudithook(hook)
atexit.register(lambda: append({"modules": [m.__file__ for m in sys.modules.values() if getattr(m, "__file__", None)],
                                "cfg_reads": rd_cfg.READS}))   # rd.cfg(): every leaf read, misses recorded as ∅

# rd_exec.build_trace — runs ON THE HOST that executed the job, over its own files
def build_trace(spec, cell, dumps, root, manifest):           # manifest = files dispatched from refs/rd/runs/<id>
    reads = (∪R ∪ modules ∪ {entrypoint} ∪ glob(spec.code_inputs) ∪ repo_paths_in(∪X)) - ∪W   # drop files it wrote
    T, untracked = {}, []
    for p in reads:
        rel = repo_rel(p, root)
        if rel is None:
            if dist := owning_dist(p): T[f"env:pkg:{dist}"] = fp_json(version(dist))
            elif ds := dataset_of(p):  T[f"data:{ds}"] = dataset_version(ds)
            else: untracked.append(p)                           # warning badge; suggest declaring a dataset
            continue
        if ds := dataset_of(rel):          T[f"data:{ds}"] = dataset_version(ds); continue
        if rel in spec.config:             continue             # declared chain → tracked per key below
        if rel not in manifest or under(rel, ".research/"): untracked.append(rel); continue
        T[f"code:{rel}"] = {"fp": fp_file(rel, read(p)), "blob": blob_sha(read(p))}  # config files OUTSIDE the chain land here
    for d in ∪L under root:                T[f"dir:{rel(d)}"] = fp_dir(listing(d))
    for m in opaque_modules_touched(T):    T |= {f"code:{f}": fp_of(f) for f in ls(m.globs)}
    if cfg_tracked(dumps):  T |= {f"cfg:{k}": fp_json(v) for k, v in ∪cfg_reads}       # includes misses (∅)
    else:
        leaves = flatten(resolve(spec.config, spec.overrides, cell)) - ignore_keys(config)
        T |= {f"cfg:{k}": fp_json(v) for k, v in leaves} | {"cfg:@keys": fp_json(sorted(leaves))}
    T |= {f"env:{k}": fp_json(probe[k]) for k in spec.env_keys or config.env.key}
    T |= {a: resolved_at_start[a] for a in spec.inputs}         # node:…#out.* fps recorded when the run started
    quality = "traced" if dumps else ("declared" if spec.code_inputs else "coarse")   # coarse: code:* = Merkle of all roots
    return T, untracked, quality
```

The **footprint** of a cell is the set of `code:` and `dir:` keys in its selected run's trace. The Experiments panel shows it as `Experiment.code.footprint`.

### 4.4 Current-value resolver `R` (memoized per evaluation; overlays for previews)

```python
R.code(path, ref)      # ref: worktree | branch:<b> | wt:<path>
    # index from `git ls-files -s -z` (or `ls-tree -r -z <b>`), dirty/untracked from `git status --porcelain=v2 -z
    # --untracked-files=all` + `git hash-object`; blob → fp via blobfp cache; absent → MISSING
R.dir(path, ref)       # names from the same index + untracked, minus ignored
R.cfg(key, n, cell)    # flatten(merge(load(spec.config @ ref), spec.overrides, cell))[key] → fp | MISSING; "@keys" → key set
R.data(id)             # dataset node's version facet
R.env(key, n)          # probe of n.spec.platform — the TARGET platform (envs/<platform>.json; pkg:* from uv.lock if set)
R.node(addr, pin)      # authored/derived facet fp at head (pinned → that vid); bound → R.cfg in the base context;
                       # output → E[id].out_fp(addr) (computed earlier in the pass order)
R.with(P)              # P: addr | glob → fp | MISSING | UNKNOWN; takes precedence over everything above

def code_patch(spec):  # git → overlay; spec = "A..B" | "staged" | "worktree" | "branch:X"
    for st, path, old in git_diff_name_status_z(spec, renames=True):
        P[f"code:{path}"] = MISSING if st == "D" else fp_file(path, blob_at(spec.to, path))
        if st == "R": P[f"code:{old}"] = MISSING
        if st in "ADR": P[f"dir:{dirname(path)}"] = fp_dir(names_at(spec.to, dirname(path)))
    drop entries whose fp is unchanged         # comment-only .py edits → listed as "ignored (format/comments)"
```

### 4.5 Evaluation

The evaluation is pure: it reads files and caches and writes nothing.

```python
LEVEL = {"fresh":0, "review":1, "orphaned":2, "pending":3, "unbuilt":4, "stale":4, "broken":5}
DEAD = {"refuted", "abandoned", "superseded"};  SOFT = {"basis", "implements", "describes"}

def evaluate(G, R):
    E = {n.id: Eval(n, archived=n.status in DEAD) for n in G.nodes}

    # Pass 1 — action cells, topological over `input` edges (a DAG by construction)
    for n in toposort(G.actions(), edge="input"):
        ev = E[n.id]
        if ev.archived: continue
        for cell in expand_cells(n):                        # canonical "rate=8,system=ours"; "_" without sweep
            runs = usable_runs(n.id, cell)                  # succeeded, not excluded, newest first
            cands = [n.selected[cell]] if cell in n.selected else runs
            hit = next((r for r in cands if not mismatches(r, n, cell, R, E)), None)
            if hit:            ev.cells[cell] = Cell("fresh", hit, reused=hit is not runs[0])
            elif not runs:     ev.cells[cell] = Cell("unbuilt")
            else:
                r = cands[0]; mm = mismatches(r, n, cell, R, E)
                lvl = ("orphaned" if any(m.kind == "upstream_dead" for m in mm) else
                       "pending"  if all(m.kind == "upstream_pending" for m in mm) else "stale")
                ev.cells[cell] = Cell(lvl, r, provisional=True, why=mm)
        ev.out = output_tables(n, ev.cells)   # {name: {cell: (value, anchor, fp)}} + derived outputs (fp from anchors)
        ev.raise_to(max(c.level for c in ev.cells.values()))

    # Pass 2 — evidence of live beliefs (beliefs are hard-graph sinks: any order)
    for n in G.beliefs():
        ev = E[n.id]
        if ev.archived: continue
        for e in n.edges("evidence"):
            if e.to.scheme == "run":
                if excluded(e.to.run): ev.add("review", e, "evidence run excluded")
                continue
            up = E.get(e.to.node)
            if up is None or up.archived:            ev.add("orphaned", e); continue
            if up.tainted(e.to):                     ev.add("pending", e, provisional=up.value(e.to)); continue
            cur, val = up.out_fp(e.to), up.value(e.to)      # fp from anchors; value = actual numbers
            if e.predicate or e.kill_if:                    # checked EVERY time: cutoff cannot hide a crossing
                ok = holds(e.predicate, val) if e.predicate else not holds(e.kill_if, val)
                if not ok:             ev.add("broken", e, value=val)
                elif cur != e.seen:    ev.flag("drift", e, seen=e.seen, now=val)
            elif cur != e.seen:        ev.add("review", e, now=val)
        for b in n.bindings():                              # a number typed into prose, e.g. "2.1x" in the abstract
            if b.stated is not None and (v := value_of(b, E)) is not None and off_tol(b.stated, v, b.tol):
                ev.add("review", b, f"text says {b.stated}, evidence {v}")

    # Pass 3 — soft edges and dead upstreams, all live nodes (for actions: ring only, cells untouched)
    for n in G.nodes:
        ev = E[n.id]
        if ev.archived: continue
        for e in n.edges(SOFT):
            up = G.get(e.to.node)
            if up is None or up.status in DEAD:       ev.add("orphaned", e, up and up.status); continue
            cur = R.node(e.to, pin=e.pin)
            if cur != e.seen:                         ev.add("review", e, diff=facet_diff(e.seen, cur))
            elif E[up.id].level == LEVEL["broken"]:   ev.add("review", e, "upstream broken")
        for e in n.edges("cites"):
            if G[e.to.node].status in DEAD:           ev.add("review", e, "cited reference retracted")

    # Pass 4 — flags (never change levels)
    lagging = [m for m in G.kind("module") if E[m.id].has_reason("implements")]
    for n in G.actions():
        for c in E[n.id].cells.values():
            c.impl_lag = bool(c.run) and any(in_globs(a, m.globs) for m in lagging for a in c.run.code_keys())
    roots = {i for i, ev in E.items() if not ev.archived and ev.level >= LEVEL["review"]}
    shaky = reverse_bfs(roots, edges=SOFT | {"evidence"})             # {node: {root ids}}
    for n in G.nodes:
        ev = E[n.id]
        ev.shaky = shaky.get(n.id, set()) - {n.id}
        ev.lock_alert = n.status == "locked" and ev.level > 0
        ev.unsealed = fp_node(n) != n.head.fp
        ev.behind_head = [e.key for e in n.edges() if e.pin and e.pin != head_vid(e.to.node)]
    return E

def mismatches(run, n, cell, R, E):                        # Shake-style verifying trace
    mm = []
    if run.spec_fp != spec_fp(n, cell): mm.append(Mis("spec", run.spec_fp, spec_fp(n, cell)))
    for addr, item in run.trace.items():
        if addr.scheme == "node":
            up = E.get(addr.node)
            if up is None or up.archived: mm.append(Mis(addr, kind="upstream_dead")); continue
            if up.tainted(addr):          mm.append(Mis(addr, kind="upstream_pending")); continue
        cur = R.get(addr, ctx=(n, cell))                    # env against n.spec.platform
        if cur != item.fp: mm.append(Mis(addr, item.fp, cur))
    return mm

def spec_fp(n, cell):    # the action's own definition. Overrides, sweep and cell values reach it via cfg:;
    s = n.spec           # platform via env:; tolerances and est_hours never count
    return fp_json({"command": s.command, "config": s.config, "replicates": s.replicates, "gpus": s.gpus,
                    "datasets": s.datasets, "env_keys": s.env_keys, "code_inputs": s.code_inputs, "algo": FP_ALGO})
```

Changing `outputs.*.from` or `derive` triggers `dag reextract` from the stored artifacts. If the artifacts are missing, those cells go `stale` with the reason "outputs spec changed". Changing `tol` has no effect.

Predicates are data, not code: `{agg: min|max|mean|all|any, op: >=|<=|>|<|==, rhs: number}`, applied to the selected cells.

### 4.6 Recording a run, and early cutoff

```python
def record_run(n, cell, run):
    prev = newest succeeded, non-excluded run of (n, cell)          # what consumers saw most recently
    for name, v in run.outputs.items():
        tol = n.outputs[name].tol or config.outputs.default_tol     # {rel: 0.05} | {abs: 0.1}
        a = prev and prev.outputs.get(name)
        if a and same_shape(a, v) and within(a.anchor, v.value, tol):
            v.fp, v.anchor, v.cutoff = a.fp, a.anchor, True         # compared to the ANCHOR: drift stays bounded by one tol
        else:
            v.fp, v.anchor, v.cutoff = fp_json(quantize(v.value, config.outputs.sig)), v.value, False
    write runs/<n>/<cell>/<run.id>.json; log("run_recorded"); publish("dag", evaluate_delta())
```

After a cutoff, consumers keep the same fingerprint, so figures and soft dependents do not churn. Predicates and macros always use the **actual** value of the selected run. A cutoff can therefore never hide a threshold crossing.

### 4.7 What "unchanged facet ⇒ reuse" means, and its limits

**Rule:** `valid(r, n, c) ⇔ spec_fp(n, c) = r.spec_fp ∧ ∀ (a ↦ f) ∈ r.trace : R_c(a) = f ∧ no node: input of r is tainted.`

**Soundness argument.** Take a deterministic program and suppose every input it read is unchanged. By induction over its execution, it follows the same control flow, so it reads the same set of inputs. A file or key it never read cannot change the result unless something it did read also changed. GPU timing noise is not covered by this argument; replicates plus tolerance handle it. The argument has a few known gaps:

| hole | v1 mitigation |
|---|---|
| reads from C or `fopen` and non-Python binaries | `opaque` modules add their whole glob set; `spec.code_inputs`; trace_quality badge; `coarse` fallback |
| import shadowing by a newly added file | accepted; documented. Directory scans by registries are caught through `dir:` |
| reads outside the repo or ignored files | `untracked_reads` warning, with a suggestion to declare a dataset |
| hub files (utils imported everywhere) | token normalization; per-key config; `dag hubs` report ("utils.py is in 94% of traces") |
| tolerance hides a real regression | tight per-output tolerances; cutoff Δ shown on every cell; predicates use actual values |
| empirical check | v1.5 `dag audit`: re-runs one random reused cell per week within budget and alarms if the result falls outside tolerance |

### 4.8 Complexity

One evaluation costs O(V + E + Σ over checked runs of |trace|). Runs are checked newest first and the check stops at the first valid one. Calls to `R` are memoized and the git index is read once (about 20 ms).

Example: 200 nodes, 60 cells, 3 runs each, 300 items per trace. That is about 54k lookups, well under 100 ms. The result is cached by `(git index mtime, max mtime under .research/dag, envs digest)`, and `base_digest` is the hash of all of these.

---

## 5. Impact preview API

`POST /api/projects/{pid}/dag/impact`. The same function backs the MCP tool `rd_impact`, the CLI `python -m research_deck.dag preview --staged`, the inspector what-if, and every proposal.

**Input**

```json
{"ops": [{"op": "edit", "node": "design.sched", "base_vid": "v-5c0e19a2",
          "set": {"preemption": "Preempt decode-starved requests when TTFT slack < 0; resume by recompute."}}],
 "code": {"diff": "HEAD~1..HEAD"},          // or {"staged": true} | {"worktree": true} | {"branch": "rd/attempt/sol.x"} | omitted
 "touch_code": ["src/lookahead/sched/**"],  // optional prediction for code that does not exist yet
 "explain": true}
```

**Algorithm**

1. `G1` = a copy-on-write overlay of the ops, applied through the same reducers in dry-run mode. Permission failures become `requires_human` entries, not errors. `P` = the overlay patch:
   - `edit` → `P[node:id#f] = fp(v)` (exact);
   - `config_edit` or a bound facet → re-resolve `cfg:` for every consumer of that file (exact);
   - `code` → `code_patch` (exact);
   - `rollback` → the target vid's facet fps (exact);
   - a design `edit` with no code yet → `P[code:p] = UNKNOWN` for every `p` in the globs of modules that implement the edited facet (**predicted**);
   - `touch_code` → `UNKNOWN` for every match (**predicted**).
2. `E0 = evaluate(G0, R)` (cached by digest) and `E1 = evaluate(G1, R.with(P))`. Classify every action cell and every node by the rules below.
3. Estimate cost: the median duration of the cell's last 3 successful runs × gpus × `envs/<platform>.json.usd_per_gpu_hour`. Fall back to the node median, then to `spec.est_hours`.
4. Why-paths: BFS from each patched address to each affected item over the reverse graph, using implements → glob → trace items as edges.
5. Store `base_digest`. On approve, recompute. If the counts or categories changed, return 409 `needs_rebase` with the new impact.

| category | rule | shown as |
|---|---|---|
| `rerun` | cell: E0 ∈ {fresh, pending} → E1 ∈ {stale, unbuilt} | cells, why items (`addr: from → to`), GPU-h, $, `impl_lag` → "implement first" |
| `conditional` | cell or belief: E0 fresh → E1 pending | best case (every rerun cuts off) vs worst case; predicates with their current margin |
| `reused` | cell fresh in both, and "near" the change: its node is downstream of a changed node, or its trace shares a family (directory, module glob or cfg top-level key) with a patched address | one reason per group, e.g. "trace has 0 of 4 changed files", "cell overrides sched.chunk.max" |
| `revived` | E0 not fresh → E1 fresh | the run that becomes selected, its age, GPU-h recovered |
| `review` / `orphaned` / `broken` | new in E1 for beliefs | the edge, the facet text diff, the predicate value |
| `already_tried` | a revived cell whose selected run is cited by a `run:` evidence edge of a dead node | the refuted node, its reason and verdict value |
| `suggest_restore` | rollback closure (§3) | "restore mod.sched edges from r2" (one click, adds an op) |
| `lock` | an op writes a locked node (hard: `requires unlock`), or a locked node's level rises (needs a human tick) | purple |
| `gates` | gate checks that flip | e.g. G6 passed → passed-degraded |
| `already` | not fresh in both | "not caused by this change" |

**Output**

```json
{"base_digest": "d:9a40c2e1b7f3", "precision": "predicted",
 "patched": [{"addr": "node:design.sched#preemption", "from": "s:3a1f6e20c94d", "to": "s:9be04d71a2c3"},
             {"addr": "code:src/lookahead/sched/*", "from": "4 files", "to": "UNKNOWN", "via": "mod.sched implements design.sched#preemption"}],
 "summary": {"rerun": 11, "conditional": 5, "reused": 22, "revived": 0, "review": 3, "orphaned": 0, "broken": 0, "lock": 1,
             "gpu_h": {"rerun": 3.7, "conditional_worst": 0.0, "reused": 6.5, "full_campaign": 10.2}, "usd": {"rerun": 0.0}},
 "rerun": [{"node": "exp.e2e-sharegpt", "cells": ["rate=4,system=ours", "rate=8,system=ours", "rate=16,system=ours"],
            "why": [{"addr": "code:src/lookahead/sched/policy.py", "from": "p:41ac9e07d2b3", "to": "UNKNOWN"}],
            "est_gpu_h": 1.2, "platform": "workstation", "impl_lag": true}],
 "conditional": [{"node": "claim.ttft-2x", "via": ["exp.e2e-sharegpt"], "predicate": "min >= 2.0", "current": 2.2, "margin": 0.2}],
 "reused": [{"node": "exp.e2e-sharegpt", "cells": ["rate=*,system=vllm", "rate=*,system=sarathi"], "reason": "trace has no src/lookahead/** file"},
            {"node": "exp.kv-micro", "cells": ["_"], "reason": "trace: src/lookahead/kv/*, bench/micro_kv.py; 0 of 4 changed files"}],
 "review": [{"node": "mod.sched", "edge": "implements:node:design.sched#preemption", "diff": "None. → Preempt decode-starved…"},
            {"node": "sec.design", "edge": "describes:node:design.sched#preemption"},
            {"node": "fig.arch", "edge": "describes:node:design.sched#preemption"}],
 "revived": [], "already_tried": [], "suggest_restore": [], "broken": [], "orphaned": [],
 "lock": [{"node": "design.sched", "kind": "edit_locked", "requires": "unlock:design.sched"}],
 "gates": [{"gate": "G5", "from": "passed", "to": "passed_degraded"}],
 "requires_human": {"value": true, "reasons": ["edit of locked design.sched"]},
 "why_paths": {"exp.e2e-sharegpt[rate=8,system=ours]":
   ["node:design.sched#preemption", "implements", "mod.sched", "glob", "code:src/lookahead/sched/policy.py", "trace"]}}
```

When a code diff later arrives for the same proposal, it is re-previewed with `precision: exact`, and the card shows **predicted vs actual** ("predicted 11, actual 11").

---

## 6. Storage layout under `.research/dag/`

```
<project>/
  .research/
    project.yaml                         (existing) name, venue, stage, paper, code.roots
    dag/
      config.yaml                        roots, env keys, tolerances, gates, policy, autocommit
      nodes/<node-id>.yaml               head: facets, edges (+seen), status, lock
      history/<node-id>.jsonl            append-only versions (merge=union)
      runs/<node-id>/<cell-id>/<run-id>.json   immutable run record: trace, outputs, provenance
      proposals/<pid>.yaml               agent proposals: ops, base_digest, impact, state
      snapshots/<name>.yaml              gate and milestone pins
      envs/<platform>.json               latest probe per platform + usd_per_gpu_hour
      datasets/<dataset-id>.manifest.json
      log.jsonl                          append-only event stream (merge=union)
      .cache/                            gitignored: blobfp.sqlite, eval.json, layout.json
    experiments/                         (experiments slice) job records; Experiment.node_id + run_id link here
  paper/generated/rdvalues.tex           generated number macros (committed)
  .gitattributes                         .research/dag/history/*.jsonl merge=union; .research/dag/log.jsonl merge=union
  .git/refs/rd/runs/<run-id>             exact code snapshot per run
```

**config.yaml**

```yaml
schema: rd-dag/1
fp_algo: rd/1
home_branch: main
code: {roots: [src, bench, proto, plots], exclude: ["**/*.md", "notebooks/**", "**/test_*.py"]}   # default: project.yaml code.roots
config: {roots: [configs], ignore_keys: [output_dir, run_name, "wandb.*", log_level]}
datasets_roots: {local: data/, shared: /mnt/shared/lookahead-serve/data}
env: {key: [python, gpu_model, gpu_count, driver_major, cuda, "pkg:*"], lockfile: uv.lock}
outputs: {default_tol: {rel: 0.03}, sig: 4}
paper: {root: paper, macros: paper/generated/rdvalues.tex}
gates: {blocking: false, G1: {min_refs: 5, baseline_repro_tol: 0.10}, G2: {min_workloads: 2, min_replicates: 3},
        G3: {min_headroom: 1.3}, G4: {min_captured: 0.5, min_alternatives: 2}, G5: {microbench_vs_proto: 0.8}}
policy:
  agent_auto_apply: safe
  agent_auto_run: {max_gpu_hours_per_day: 8, platforms: [workstation], kinds: [experiment, figure]}
autocommit: {enabled: true, debounce_s: 30, paths: [.research/dag, paper/generated]}
```

**nodes/design.sched.yaml** (belief; `seen` on edges)

```yaml
id: design.sched
kind: design
stage: S5
title: {en: Lookahead scheduler, zh: 前瞻调度器}
status: locked
head: {rev: 3, vid: v-5c0e19a2, fp: s:2f6d0c41b8e7}
facets:
  policy: {type: prose, value: "Each iteration admits prefill chunks until the tightest request's predicted TTFT slack reaches zero."}
  preemption: {type: prose, value: "None. Decode requests are never preempted."}
  chunk: {type: bound, bind: "configs/sched.yaml#sched.chunk"}                    # {min: 256, max: 2048, align: 128}
  budget_slack_ms: {type: bound, bind: "configs/sched.yaml#sched.budget.slack_ms"}   # 50
edges:
  - {type: basis, to: "node:dec.sched-approach#choice", seen: s:91ab2c7e0d4f}
  - {type: cites, to: "node:ref.sarathi-serve"}
lock: {by: human:alice, at: "2026-10-28T16:00:00Z", vid: v-5c0e19a2, fp: s:2f6d0c41b8e7, tag: rd/lock/design.sched/r3}
updated: {by: human:alice, at: "2026-10-28T16:00:00Z", via: p-0009}
```

**nodes/exp.e2e-sharegpt.yaml** (action; fingerprints live in its runs)

```yaml
id: exp.e2e-sharegpt
kind: experiment
stage: S6
purpose: eval
status: active
title: {en: End-to-end latency on ShareGPT, zh: ShareGPT 端到端延迟}
head: {rev: 2, vid: v-a91c33d0, fp: s:0e4b7f2c9a1d}
facets:
  spec:
    type: json
    value:
      command: python bench/e2e.py            # cell values arrive as config overrides via rd.cfg()
      config: [configs/base.yaml, configs/sched.yaml, configs/e2e.yaml]
      overrides: {workload: sharegpt, duration_s: 600}
      sweep: {system: [vllm, sarathi, ours], rate: [4, 8, 16]}
      datasets: [data.sharegpt-v3]
      platform: workstation
      gpus: 1
      replicates: 3
      code_ref: worktree
      est_hours: 0.4
  outputs:
    type: json
    value:
      ttft_p99: {from: "metrics.json:$.ttft.p99", unit: ms, tol: {rel: 0.05}}
      tpot_p99: {from: "metrics.json:$.tpot.p99", unit: ms, tol: {rel: 0.05}}
      ttft_speedup: {derive: "ratio(ttft_p99[system=vllm], ttft_p99) by rate"}
edges:
  - {type: basis, to: "node:sol.chunk-budget#expected_gain", seen: s:5f20c1a9e7b3}
selected: {}
```

**nodes/claim.ttft-2x.yaml**

```yaml
id: claim.ttft-2x
kind: claim
stage: S6
status: confirmed
title: {en: Headline TTFT speedup, zh: 核心 TTFT 加速比}
head: {rev: 2, vid: v-77d0a1b3, fp: s:6c1e0b9a2f47}
facets:
  role: {type: json, value: contribution}
  text: {type: prose, value: "Lookahead lowers P99 TTFT by up to {{speedup_max}} over vLLM, and by at least 2x at every load."}
  bindings:
    type: json
    value:
      speedup_max: {from: "node:exp.e2e-sharegpt#out.ttft_speedup[system=ours]", agg: max, fmt: "{:.1f}\\ensuremath{\\times}", macro: rdTtftSpeedupMax}
edges:
  - type: evidence
    to: "node:exp.e2e-sharegpt#out.ttft_speedup[system=ours]"
    polarity: supports
    predicate: {agg: min, op: ">=", rhs: 2.0}
    seen: t:44e1b07a2c9d
```

**history/design.sched.jsonl** (one line per version)

```json
{"vid":"v-5c0e19a2","rev":3,"parent":"v-1b9d07e4","fp":"s:2f6d0c41b8e7","facets":{"policy":"…","preemption":"None. Decode requests are never preempted.","chunk":{"bind":"configs/sched.yaml#sched.chunk"},"budget_slack_ms":{"bind":"configs/sched.yaml#sched.budget.slack_ms"}},"edges":[{"type":"basis","to":"node:dec.sched-approach#choice","seen":"s:91ab2c7e0d4f"}],"status":"confirmed","by":"human:alice","at":"2026-10-28T15:40:12Z","git":"4be1c0d","op":"edit","via":"p-0009"}
```

**runs/exp.e2e-sharegpt/rate=8,system=ours/r-20261029-1844-a1b2.json**

```json
{"id":"r-20261029-1844-a1b2","node":"exp.e2e-sharegpt","node_vid":"v-a91c33d0","cell":"rate=8,system=ours","state":"succeeded",
 "by":"agent:codex:019a3f","experiment":"e-0031","deck_job":"workstation/job-1187","platform":"workstation",
 "started":"2026-10-29T18:44:02Z","ended":"2026-10-29T19:08:31Z","gpu_hours":0.41,
 "git":{"head":"4be1c0d","snapshot":"refs/rd/runs/r-20261029-1844-a1b2","dirty":false},
 "fp_algo":"rd/1","trace_quality":"traced","spec_fp":"s:6d02b8e1a4c9",
 "trace":{
  "code:src/lookahead/sched/policy.py":{"fp":"p:41ac9e07d2b3","blob":"8c3d5e1f0a7b"},
  "code:src/lookahead/sched/budget.py":{"fp":"p:9e12c7d04b5a","blob":"3e91a7c0d2f4"},
  "code:src/lookahead/engine.py":{"fp":"p:0b3e7d91c4a2","blob":"a17c2e90b3d1"},
  "code:bench/e2e.py":{"fp":"p:77d0f4a2b9c1","blob":"0d4e6a1b9c33"},
  "cfg:rate":{"fp":"s:1f0c8a2e7d3b","v":8},
  "cfg:sched.chunk.max":{"fp":"s:e3a17c0d52b9","v":2048},
  "cfg:sched.preempt.mode":{"fp":"∅","v":null},
  "data:data.sharegpt-v3":{"fp":"m:b7e21c90d4a3"},
  "env:pkg:vllm":{"fp":"s:5e1b2d9c07a4","v":"0.11.0"},
  "env:gpu_model":{"fp":"s:d4c86a1e0b3f","v":"NVIDIA L4"}},
 "untracked_reads":[],
 "outputs":{"ttft_p99":{"value":182.4,"unit":"ms","n":3,"ci95":[176.0,189.1],"anchor":182.4,"fp":"s:b21f09a4c6d3","cutoff":false}},
 "artifacts":{"raw":{"uri":"s3://research-artifacts/lookahead-serve/runs/r-20261029-1844-a1b2/raw.parquet","sha256":"9f1c…"}}}
```

**log.jsonl**

```json
{"e":"e-000412","at":"2026-11-01T22:41:03Z","by":"system","op":"run_recorded","node":"exp.e2e-sharegpt","cell":"rate=16,system=ours","run":"r-20261101-2219-5c0d","cutoff":false}
{"e":"e-000419","at":"2026-11-02T09:05:40Z","by":"human:alice","op":"decision","kind":"refute","node":"sol.decode-preempt","reason":"TPOT p99 1.21x vs vLLM on LMSYS @16 req/s","evidence":["run:r-20261101-2307-9e4d#out.tpot_ratio"],"proposer":"agent:claude:46e445"}
```

**proposals/p-0012.yaml**

```yaml
id: p-0012
by: agent:claude:46e445
at: "2026-11-01T09:12:44Z"
state: open                 # open | applied | rejected | withdrawn | needs_rebase
title: Add decode preemption to cut LMSYS P99 TTFT at high load
ops:
  - {op: edit, node: design.sched, base_vid: v-5c0e19a2, set: {preemption: "Preempt decode-starved requests when TTFT slack < 0; resume by recompute."}}
requires: [unlock:design.sched]
base_digest: d:9a40c2e1b7f3
impact: {precision: predicted, rerun: 11, reused: 22, review: [mod.sched, sec.design, fig.arch], conditional: 5, lock: [design.sched], gpu_h: {rerun: 3.7, reused: 6.5}}
```

**snapshots/gate-G5.yaml**

```yaml
name: gate-G5
at: "2026-10-28T16:02:00Z"
by: human:alice
git: 4be1c0d
nodes: {design.sched: v-5c0e19a2, dec.sched-approach: v-77c1a0e9, mod.sched: v-3d81f0aa}
runs: {"exp.overhead/_": r-20261028-1530-0c3e, "exp.kv-micro/_": r-20261028-1544-4b19}
eval_digest: d:31f7a9c0e2b4
```

**envs/workstation.json** and **paper/generated/rdvalues.tex**

```json
{"platform":"workstation","probed":"2026-11-01T22:05:10Z","via":"rd-exec-probe",
 "key":{"python":"3.12.7","gpu_model":"NVIDIA L4","gpu_count":1,"driver_major":"580","cuda":"12.9"},
 "pkgs":{"torch":"2.9.0","vllm":"0.11.0"},"usd_per_gpu_hour":0}
```

```tex
% generated by research-deck dag; do not edit
\newcommand{\rdTtftSpeedupMax}{2.5\ensuremath{\times}}   % claim.ttft-2x speedup_max; fresh
\newcommand{\rdOverheadPct}{\rdstale{0.4\%}}             % claim.overhead-lt-1pct; pending (red in draft mode)
```

---

## 7. HTTP API and MCP

All paths are under `/api/projects/{pid}/dag`. JSON throughout. Changes publish SSE topic `dag` with `{digest, changed: [ids]}`.

**Actors.** The browser holds an HttpOnly cookie with an in-memory token (`human:<name>`). The MCP server sends `X-RD-Actor: agent:<claude|codex>:<session>` with the agent token from `research-deck/.local/agent.token`. If an agent calls a human-only op, the server answers 403 `{"message": "open a proposal"}`. This is tamper-evident, not tamper-proof. Every op is logged with its actor, and `dag check` flags direct YAML edits.

| method | path | body / query | response | who |
|---|---|---|---|---|
| GET | `/graph` | `?at=&lens=tried\|confirmed\|revise\|rerun&dead=1` | `{nodes: DagNode[], eval: Record<id, NodeEval>, lenses, digest}` | all |
| GET | `/nodes/{id}` | | `DagNode` + eval + recent history + runs per cell | all |
| GET | `/nodes/{id}/explain` | `?cell=` | `WhyChain[]` (root-cause paths with from→to values) | all |
| GET | `/nodes/{id}/history` | | `Version[]` with facet diffs | all |
| POST | `/ops` | `{ops, base_digest?, rationale?}` | `{applied: true, events, eval_delta}`, or 202 `{proposal}` (safe rule); 409 on a `base_vid` or digest mismatch | all (permissions per §2.7) |
| POST | `/impact` | §5 input | `Impact` | all |
| GET | `/proposals` | `?state=` | `Proposal[]` | all |
| POST | `/proposals` | `{title, rationale, ops}` | `Proposal` with fresh impact | all |
| POST | `/proposals/{id}/approve` | `{ops?: indices}` | applied result, or 409 `needs_rebase` with the new impact | human |
| POST | `/proposals/{id}/reject` | `{reason}` | `Proposal` | human |
| POST | `/nodes/{id}/lock` · `/unlock` | `{reason}` | `DagNode` | human |
| GET | `/runs` | `?node=&cell=` | `RunSummary[]` | all |
| POST | `/runs` | run record (from rd-exec via the experiments slice) | `{run_id, cutoff: {...}, eval_delta}` | system |
| POST | `/runs/plan` | `{targets?: ids, conditional?: bool}` | `{waves: [[{node, cell, est_gpu_h, platform, blocked?}]], gpu_h, usd}` | all |
| POST | `/runs/queue` | `{cells: [{node, cell}], platform, confirm: true}` | `{experiments: [eid]}` (creates experiments-slice records and submits only with confirm) | agent within budget; human |
| POST | `/runs/{run_id}/exclude` | `{reason}` | `RunSummary` | human |
| POST | `/cells/select` | `{node, cell, run_id\|null}` | `CellEval` | human |
| GET | `/lenses` | | `{tried, confirmed, revise, rerun}`: counts and item ids | all |
| GET | `/timeline` | `?since=&node=&actor=` | `Event[]` | all |
| GET / POST | `/snapshots` | `{name, note}` | `Snapshot` | all |
| POST | `/snapshots/{name}/restore` | | `Proposal` | all (approve: human) |
| GET | `/gates` | | `GateStatus[]` (checks with live values) | all |
| POST | `/gates/{gate}/pass` | `{note}` | `Snapshot` | human |
| GET | `/check` | | `{schema, cycles, dangling, unsealed, conflicts, alt_group, anchors}` | all |
| POST | `/paper/sync` | | `{sections, edges_added, edges_removed, macros}` (tex anchors → section nodes; regenerates rdvalues.tex) | all |

**MCP tools** (in `mcp_server.py`, proxying the routes above): `rd_graph(lens)`, `rd_node(id)`, `rd_explain(id, cell?)`, `rd_impact(ops, code?)`, `rd_apply(ops)`, `rd_propose(title, rationale, ops)`, `rd_attest(id, edges)`, `rd_plan_runs(targets?)`, `rd_queue_runs(cells, platform)`, `rd_record_run(record)`, `rd_lenses()`. Lock, unlock, approve, gate pass, select and exclude are deliberately absent. `BRIEF.md` (agents slice) includes the lens counts and the top items of Revise and Rerun.

**Integration with existing slices**
- The Experiments slice's `Experiment.freshness` maps from the cell: `fresh` = this run is selected; `reusable` = valid but not selected; `stale` = stale or pending; `unknown` = no trace.
- `code.footprint` is the run's `code:` keys.
- `/writing/claims` reads claim nodes plus their eval.
- The Architecture view's components come from `module` nodes.
- The viz slice's `Figure.node_id` points at `fig.*`, and its renders go through rd-exec locally.

**`web/src/dag-types.ts` (core)**

```ts
export type NodeStatus = 'proposed' | 'active' | 'confirmed' | 'locked' | 'refuted' | 'abandoned' | 'superseded';
export type Freshness = 'fresh' | 'review' | 'orphaned' | 'pending' | 'unbuilt' | 'stale' | 'broken';
export interface Reason { level: Freshness; edge?: string; addr?: string; from?: string | null; to?: string | null; value?: number; note?: string }
export interface CellEval { level: Freshness; run: string | null; reused: boolean; cutoff?: boolean; impl_lag?: boolean; why: Reason[]; gpu_h?: number }
export interface NodeEval { level: Freshness | null; archived: boolean; reasons: Reason[]; flags: string[]; shaky: string[]; cells?: Record<string, CellEval> }
export interface DagEdge { type: 'input' | 'evidence' | 'basis' | 'implements' | 'describes' | 'cites'; to: string; seen?: string; pin?: string;
  polarity?: 'supports' | 'refutes'; predicate?: { agg: string; op: string; rhs: number }; kill_if?: { agg: string; op: string; rhs: number } }
export interface DagNode { id: string; kind: string; stage: string; title: { en?: string; zh?: string }; status: NodeStatus;
  head: { rev: number; vid: string; fp: string }; facets: Record<string, { type: string; value?: unknown; bind?: string }>;
  edges: DagEdge[]; alt_group?: string; superseded_by?: string; lock?: Record<string, unknown> }
```

**Module layout and LOC budget (Python, about 1,540)**

| file | contents | LOC |
|---|---|---|
| `fp.py` | canon, json/token/blob/dir/table fps | 100 |
| `model.py` | pydantic models, enums, transition table, permission matrix | 130 |
| `store.py` | YAML/JSONL I/O (via `util.write_yaml`), history, log, repair, file lock, autocommit | 150 |
| `resolve.py` | git index, ls-tree and status; blob-fp sqlite; cfg resolution; env and data; overlays | 180 |
| `evaluate.py` | passes 1–4, mismatches, output tables, derived outputs, predicates | 230 |
| `impact.py` | ops → overlay, `code_patch`, classification, cost, why-paths, closure, already-tried | 160 |
| `ops.py` | apply, permissions, proposals, rollback, locks, snapshots, select/exclude | 170 |
| `gates.py` | gate checks, lenses, rerun waves | 80 |
| `paper.py` | tex anchors → section nodes and describes edges; macros | 60 |
| `api.py` | routes and SSE | 120 |
| `rd_exec/` | sitecustomize hook, `rd.cfg`, trace builder, output extraction, snapshot ref (stdlib only) | 160 |

Deferred to v2:
- HMAC lock signing;
- a per-facet git merge driver;
- cross-experiment run sharing;
- CI-overlap tolerances;
- function-level coverage;
- editorial equivalence classes;
- the `dag audit` canary scheduler.

---

## 8. UI

The map is `panels/dag/`, Today is `panels/overview/`. Class prefixes `.dg-` / `.dl-` / `.td-`, strings `dag.*` / `td.*`
(zh and en), colors only from `styles/tokens.css`. The graph uses `@xyflow/react` and `@dagrejs/dagre`.

The UI answers the four questions without asking the researcher to learn the model's vocabulary: it shows only the
exceptions (a draft to review, a run to start, a broken basis), and the mechanism behind them (13 kinds, 7 statuses,
7 freshness levels, 6 edge types, gates) stays in the details.

**Today** (the project's home) lists what needs a decision, each with the action that settles it: agent proposals
(approve / reject, with their impact), drafted nodes (review one by one, or accept all), open decisions (their options),
nodes to revise, experiments to run or rerun (the run plan), failed runs; then what waits for evidence, and the latest
events. Above it, the four steps — Idea → Motivation & insight → System design → Evaluation (the six coarse stages
grouped; writing is not a step) — and "N to go before the next stage": the failing checks of the gates that close this
step. Moving on passes those gates (each pass saves a snapshot) and sets the project's stage; with `gates.blocking`
the checks must hold first. J/K move between items, Y runs an item's first action, N its second.

**The map, as a list (default).** Nodes grouped by the four steps, one row each: a status mark (dashed = proposed),
the title, the kind as a small word, and only the exceptions (a freshness badge when not fresh, "undecided" for an open
decision). A row opens in place: what the node says (its main facet), what it rests on and what depends on it, the
options of a decision — choosing one is a what-if first, so the side panel shows the impact before Apply — and the
actions (accept / reject a draft, details, ask the agent). Review mode is the keyboard: J/K move, Y accepts a draft,
N rejects it, Enter opens the details (the inspector).

**Filters.** All · To review (proposed) · Needs attention (live and not fresh, or listed to revise or rerun) ·
Confirmed (confirmed or locked) · Abandoned (refuted, abandoned, superseded, with their reasons). The four lenses of the
model (tried, confirmed, revise, rerun) are these filters; `/dag/lenses` still serves their counts and items.

**The map, as a graph.**
- Columns are stage lanes: S0 Frame | S1 Landscape | S2 Characterize | S3 Opportunity | S4 Solutions | S5 Design | S6 Evaluation. A **W** swimlane spans the bottom. References and datasets sit in a collapsible rail at the top.
- Each lane is laid out by dagre (rankdir LR). Lanes are concatenated left to right, and cross-lane edges use xyflow smoothstep routing.
- Positions are deterministic and cached in `.cache/layout.json`. Manual drags are remembered.
- Each lane header carries its gate chip (G1…G7: go, no-go or degraded). Clicking it opens the live checklist.
- **Attempts**: an `alt_group` is drawn as a labelled bracket container, for example "gap.interference: 4 tried, 1 chosen". The chosen sibling has a thick edge; dead siblings collapse to chips unless the Abandoned filter is on. A supersede chain collapses into a card stack.
- A filter other than All dims everything else to 25%.

**Encodings.** Each state is shown through three channels: color, icon (`icons.tsx`, adding `hourglass` and `unlink`) and a word.

| channel | mapping |
|---|---|
| shape = kind | rounded rectangle: problem, finding, gap, solution; small pill: reference; cylinder: dataset; cut-corner card with a cell mini-grid: experiment and scripted figure; diamond: decision; rectangle with `layers` icon: design and module; page shape: claim and section; drawn figure: thumbnail |
| fill and border = status | proposed: dashed `--rule-strong`, no fill. active: `--process` / `--process-line`. confirmed: `--data` / `--data-line`. locked: `--data` with a double border and the `lock` icon. refuted: `--neutral` at 50%, struck-through title, `close` icon, reason chip. abandoned: `--neutral` at 50%, dashed, reason chip. superseded: `--neutral` with a "→ successor" chip |
| ring and badge = freshness | fresh: none. review: `--warn` dot, `warn` icon. orphaned: `--emphasis-line` ring, `unlink` icon. pending: dashed `--stale` ring, `hourglass`. stale: solid `--stale` ring, `refresh`, "rerun". unbuilt: dashed `--faint` ring, "not run". broken: `--accent` ring, `close` icon |
| corner flags | lock_alert (accent `lock`), unsealed (`file`), behind_head (`pin`), conflict (`split`), drift (small `info`), shaky (light amber dot, tooltip "via design.sched") |
| cell mini-grid | one square per cell, colored by cell freshness; a cutoff cell shows a tiny "≈" |
| version and runs | `r4` pill with stacked-card shadow when rev > 1; run count; Codex or Claude avatar (`robot`, colored by provider) for the last agent that touched the node |
| edges | input: solid `--ink`. evidence: solid with a green (supports) or red (refutes) head. basis: dashed. implements: dotted. describes: thin `--faint`. cites: hidden by default. An edge whose `seen` ≠ current is drawn in `--stale` and labelled with its facet chip ("preemption") |

**Node inspector** (right drawer). Tabs:
- **Overview**: facets, editable where policy allows. Bound facets show `file#key` and "open in editor".
- **Edges**: seen vs current per edge, with a value diff and an Attest button.
- **Cells**: matrix of freshness, selected run, newest run, trace quality, GPU-h and platform. The trace diff lists mismatched items. A `code:` item opens the Coding tab's diff between the two blobs; a `cfg:` item shows a key/value diff; an `env:` item shows the probe diff.
- **History**: versions with facet diffs and "Roll back to rK".
- **Why**: a plain-language root-cause chain, for example "stale because code:src/lookahead/sched/policy.py changed p:41ac→p:d07e in 9d21e77".
- **Agent**: "Explain this staleness" and "Propose fix", sent to the project conversation.

**Impact preview.** It opens on any what-if edit (300 ms debounce), a decision's option, a rollback or a relink. The map switches to preview mode:
- unaffected nodes dim to 30%;
- rerun: solid orange; conditional: dashed orange; review: amber; revived: `--data` glow; reused-near: thin `--info` outline; lock: accent.

The side panel holds:
- a summary bar, e.g. "rerun 11 (3.7 GPU-h) · reused 22 · review 3 · conditional 5 · lock 1";
- a precision badge (predicted or exact);
- grouped lists with why-paths that highlight on hover;
- lock checkboxes that must be ticked;
- buttons: **Apply**, **Apply + queue reruns**, **Send to human** (agent sessions), **Discard**.

**Elsewhere.**
- **Proposals** are on Today: impact chips, approve or reject.
- **Eval matrix** (shared with the Experiments panel): rows are claim × workload; columns are system × platform; each cell is colored by freshness, and clicking one selects it.
- **Writing integration**: gutter markers beside `% rd:` regions and `\rd…` macros, colored by freshness. A section in review offers "Draft revision", which runs the fixed typo → terminology → wording passes.

---

## 9. Worked example: `lookahead-serve` (SLO-aware chunked-prefill scheduler)

**Project layout**
- Code: `src/lookahead/{sched/{policy,budget,queue,__init__}.py, kv/{layout,cache}.py, engine.py}`.
- Benchmarks: `bench/{e2e,common,launch_vllm,launch_sarathi,profile,oracle,micro_kv,overhead}.py`.
- Simulators: `proto/{chunk_sim,mlfq_sim}.py`; plots: `plots/*.py`; configs: `configs/{base,sched,e2e,ablation}.yaml`.
- `bench/e2e.py` imports `lookahead` lazily, only when `system == ours`.
- Every experiment loads its config through `rd.cfg()`, so key reads are tracked.

**Nodes**
- `design.sched` is locked at r3: preemption = "None…", `chunk` bound to `sched.chunk` (max 2048), `budget_slack_ms` bound to 50.
- `mod.sched` (`src/lookahead/sched/**`) implements design.sched#policy and #preemption. `mod.kv` implements design.kv#layout.
- Solutions in `alt_group: gap.interference`:
  - `sol.chunk-budget`: confirmed;
  - `sol.disagg`: abandoned (infeasible: needs 2 GPUs);
  - `sol.mlfq`: refuted by `exp.proto-mlfq`.
- `dec.sched-approach` is locked.

| experiment | stage | cells | GPU-h/cell | what the traces contain |
|---|---|---|---|---|
| exp.prof-baseline | S2 | workload ×3 | 0.25 | bench/profile.py, bench/common.py, env:pkg:vllm; no src/lookahead |
| exp.oracle-isolation | S3 | workload ×3 | 0.25 | bench/oracle.py; no src/lookahead |
| exp.proto-chunk | S4 | budget ∈ {fixed, slo} | 0 (CPU sim) | proto/chunk_sim.py |
| exp.proto-mlfq | S4 | `_` | 0 | proto/mlfq_sim.py |
| exp.e2e-sharegpt | S6 | system ×3 × rate ∈ {4, 8, 16} | 0.4 | **ours**: 41 items (sched/*, kv/*, engine.py, bench/e2e.py, cfg rate, system, sched.chunk.max, sched.budget.slack_ms, sched.preempt.mode = ∅, data, env). **vllm/sarathi**: 19 items (bench/e2e.py, common.py, launch_*.py, cfg system and rate, data, env) and **no src/lookahead file** |
| exp.e2e-lmsys | S6 | same 9 | 0.4 | same pattern |
| exp.ablation-chunk | S6 | `sched.chunk.max` ∈ {512, 1024, 2048, 4096} | 0.3 | sched/*; `cfg:sched.chunk.max` comes from the cell override |
| exp.overhead | S6 | `_` | 0.1 | sched/*, bench/overhead.py |
| exp.kv-micro | S5 | `_` | 0.2 | kv/*, bench/micro_kv.py |

That is 33 cells, all fresh, 10.2 GPU-h for the full campaign.
- Figures: `fig.motivation`, `fig.e2e-latency` (input `exp.e2e-*#out.ttft_p99`), `fig.ablation`, and the drawn `fig.arch` (describes design.sched#preemption).
- Claims:
  - `claim.ttft-2x`: min speedup ≥ 2.0; values 2.20 / 2.30 / 2.50.
  - `claim.overhead-lt-1pct`: 0.4 ≤ 1.0.
  - `claim.tpot-no-regress`: `exp.e2e-lmsys#out.tpot_ratio[system=ours]`, max ≤ 1.05; currently 1.02.
- vLLM ttft_p99 by rate: 266, 420, 1026 ms.

**Step 1: exact knob what-if (discarded).** The human previews `config_edit sched.chunk.max 2048 → 4096`, which is design.sched#chunk.
- Exact patch: `cfg:sched.chunk.max s:e3a1… → s:0c72…`.
- **Rerun 7 cells (2.5 GPU-h)**: the ours cells of e2e-sharegpt and e2e-lmsys (6), and exp.overhead (1).
- **Reused 26 cells.** Near-miss reasons:
  - ablation-chunk: "each cell overrides sched.chunk.max";
  - baselines: "never read sched.*";
  - kv-micro: "reads kv.* only".
- Lock: design.sched.
- The human clicks **Fork as attempt**. This creates `exp.e2e-sharegpt-chunk4k` (override sched.chunk.max = 4096, system = ours) with 3 unbuilt cells. Nothing in the existing graph changes.

**Step 2: Claude proposes a design change (p-0012, 2026-11-01 09:12).** The change edits design.sched#preemption to "Preempt decode-starved requests when TTFT slack < 0; resume by recompute". The preview is *predicted*:
- `node:design.sched#preemption s:3a1f6e20c94d → s:9be04d71a2c3`.
- Through `mod.sched implements`, the four `code:src/lookahead/sched/*.py` files become UNKNOWN.
- **Rerun (predicted) 11 cells, 3.7 GPU-h**: e2e-sharegpt ours ×3, e2e-lmsys ours ×3, ablation ×4, overhead ×1. Every one of these traces contains a sched file.
- **Reused 22 cells, 6.5 GPU-h**:
  - the 12 vllm/sarathi cells (no src/lookahead in their traces);
  - prof-baseline ×3 and oracle-isolation ×3 (stock vLLM);
  - proto-chunk ×2 and proto-mlfq ×1 (their own simulators);
  - kv-micro ×1.
- **Review**: mod.sched (implements), sec.design (describes), fig.arch (drawn, describes).
- **Conditional**: fig.e2e-latency, fig.ablation, and the three claims.
- **Lock**: design.sched, so the proposal gets `requires: [unlock:design.sched]`.
- **Untouched**: problem, references, findings, gap, solutions, dec.sched-approach, fig.motivation. Changes never flow upstream.

The human unlocks and approves. design.sched goes to r4, status active. mod.sched, sec.design and fig.arch turn amber.

No experiment turns orange, because no code has changed. Instead the 11 cells show **`impl_lag`**: "results reflect code that no longer matches the design". The Rerun lens lists them under "blocked: implement first", so no GPU time is wasted on old code.

**Step 3: Codex commits 9d21e77.** The exact preview of `HEAD~1..HEAD`:
- `policy.py`: p:41ac9e07d2b3 → p:d07e3b52f1a9 (a real change).
- `preempt.py`: a new file. It is in no existing trace and lives in a directory that no user code lists, so it has no direct effect; it is reached only through policy.py.
- `budget.py`: the blob changed but the token fp is still p:9e12c7d04b5a (comment-only), so it is ignored.
- `configs/sched.yaml` gains `sched.preempt.slack_ms: 0`. No old run read that key; misses are recorded only for keys that were actually read. So it has no effect, which is sound because the code that reads the key (policy.py) did change.
- Result: **exact = the same 11 rerun / 22 reused**, and the card shows "predicted 11, actual 11".

The same commit revises the preemption paragraph in `paper/sections/design.tex`. Claude attests sec.design and Codex attests mod.sched's implements edges, which agents may do on active nodes. `impl_lag` clears and the 11 cells turn **stale**.

**Step 4: reruns.** Codex queues the 11 cells on workstation; 3.7 GPU-h is within the 8 GPU-h/day agent budget. While they run, the figures and claims show `pending`.

| cell / output | anchor | new | Δ | tol | output fp |
|---|---|---|---|---|---|
| sharegpt ours rate=4 ttft_p99 | 121.0 | 119.2 | −1.5% | 5% | kept (cutoff) |
| sharegpt ours rate=8 ttft_p99 | 182.4 | 176.9 | −3.0% | 5% | kept (cutoff) |
| sharegpt ours rate=16 ttft_p99 | 410.3 | 298.6 | −27.2% | 5% | changed |
| lmsys ours rate=16 tpot_ratio | 1.02 | 1.21 | +18.6% | 3% | changed |
| overhead overhead_pct | 0.4 | 0.9 | +0.5 | abs 0.1 | changed |

Downstream effects:
- **Tables.** `exp.e2e-sharegpt#out.ttft_p99` moves from t:58d2a0c4e71b to t:a7c31e5d08f2. The derived speedup computed from actual values is 2.23 / 2.37 / 3.44, and its fp moves from t:44e1b07a2c9d to t:c90b3e61f4a2.
- **Figures.** fig.e2e-latency and fig.ablation go stale. The `system` actor re-renders them automatically (0 GPU-h) and they turn fresh.
- **claim.ttft-2x.** min 2.23 ≥ 2.0 holds, so it stays **fresh** with a `drift` flag (2.5× → 3.4×), and `\rdTtftSpeedupMax` updates. claim.overhead-lt-1pct: 0.9 ≤ 1.0 holds, so it is fresh with drift.
- **claim.tpot-no-regress.** max 1.21 > 1.05, so it is **broken** (red). sec.eval describes a broken claim and goes to **review**. Gate G6 turns red.
- **Lenses**: Revise shows 2 (claim.tpot-no-regress, sec.eval); Rerun shows 0; the footer reads "22 reused, 6.5 GPU-h saved this change".

**Step 5: rollback (2026-11-02).** The human previews "rollback design.sched → r3 + git revert 9d21e77":
- Patch: preemption s:9be0… → s:3a1f…; policy.py p:d07e… → p:41ac…; preempt.py → ∅; the design.tex hunk reverts.
- **Revived 11 cells, 0 GPU-h.** The r-20261029-* runs verify again and become selected, because each cell uses its newest valid run. The r-20261101-* runs stay on record.
- **Revived figures.** The old render runs' traces match t:58d2… again, so their stored PDFs are re-materialized.
- **claim.tpot-no-regress** is fresh again (1.02). claim.ttft-2x is fresh and its drift disappears, because its `seen` equals the current fp again.
- **fig.arch** is fresh with no action: nobody had re-attested it, so its `seen` was still s:3a1f…
- **Review**: mod.sched and sec.design. Their edges were attested against r4.
- **Rollback closure**: "restore mod.sched edges from r2" and "restore sec.design edges from r3". Both are one click and agent-allowed.

Applying creates design.sched **r5 `{reverts: v-5c0e19a2}`** with fp s:2f6d0c41b8e7 (equal to r3), plus revert commit 1f0a3c2. The human re-locks it (r6).

**Step 6: keep the negative result.** Claude proposes `sol.decode-preempt` in `alt_group: gap.interference`, status **refuted**:
- reason: "TPOT p99 1.21× vs vLLM on LMSYS @16 req/s";
- evidence: frozen `run:r-20261101-2307-9e4d#out.tpot_ratio` with `kill_if: {agg: max, op: ">", rhs: 1.05}`.

The human approves. The attempts bracket now reads "4 tried, 1 chosen". design.sched r4 stays in history, and the 11 preemption runs stay in `runs/` with their code at `refs/rd/runs/*`.

**Step 7: the idea comes back (2026-12-03).** Codex proposes reverting 1f0a3c2 together with the r4 preemption text. The preview shows:
- **revived 11 cells from the r-20261101-* runs, 0 GPU-h**;
- **already_tried**: "sol.decode-preempt refuted, kill_if met (tpot_ratio 1.21)";
- **broken (known now)**: claim.tpot-no-regress.

Today shows the earlier decision next to the new proposal. No GPU time is spent learning the same thing twice.

---

## 10. Open questions

Each question lists the default the implementation assumes.

1. **How do your experiment harnesses load config?** Can entrypoints load config through `rd.cfg()` (key-level read tracking) and accept sweep values as config overrides? The options are argparse + YAML, OmegaConf, or Hydra. Default: wrap YAML/OmegaConf. Argparse-only scripts get the whole-config fallback, which still gives correct results but less reuse. Non-Python pieces (CUDA kernels, compiled extensions) are declared as `opaque` modules.
2. **How should runs ship code to remote hosts?** Default: rsync a `git archive` of `refs/rd/runs/<id>` plus its manifest, and rd-exec checks the fingerprints on arrival. The alternative is to push `refs/rd/*` to a private remote that the hosts fetch.
3. **How much autonomy should agents have?** Default:
   - auto-apply only "safe" batches;
   - agents may promote their own proposed nodes to active;
   - agents may auto-queue up to 8 GPU-h per day, on workstation only, never on cloud;
   - figures re-render automatically;
   - gates are advisory, not blocking.
4. **What tolerances and replicates should be the defaults?** Default: 3 replicates; tolerance 5% relative for latency percentiles and 3% otherwise; anchor-based cutoff on. Should the `submit-<venue>` snapshot instead require a "strict mode" that reruns cutoff cells exactly?
5. **Git policy.** Default:
   - one DAG per project in the primary checkout;
   - autocommit `.research/dag` and `paper/generated` every 30 s, only while on `main`;
   - attempts as branches or worktrees referenced through `code_ref`.

   Or do you prefer manual commits, or a separate branch for DAG state?
---

## 11. v1 implementation decisions (Research Deck build, 2026-11-02)

**Defaults for §10 until the researcher answers** (all configurable in `dag/config.yaml`):
1. Config: YAML loaded through `rd.cfg()` when the harness uses it, otherwise the whole-config fallback (`cfg:@keys`).
2. Remote code shipping: not wired in v1 (no dispatch from the DAG); runs arrive as records (`POST /dag/runs`), from `rd_exec`
   on the local machine or imported from a scheduler's results.
3. Agent autonomy: as in §10.3, except **no automatic queueing of runs at all in v1** (`policy.agent_auto_run.max_gpu_hours_per_day: 0`).
4. Tolerances: as in §10.4.
5. Git: **autocommit disabled by default** (`autocommit.enabled: false`) until the researcher chooses; the dashboard never commits code.

**Actors.** `server/research_deck/actors.py` (core, done): `actor_of(request)` returns `human:<login>` (browser cookie from
`GET /api/session`), `agent:<claude|codex>:<id>` (MCP server with `X-RD-Actor` + `X-RD-Agent-Token`), or `agent:unknown`
(anything else; agent permissions). `is_human(actor)`. Use it in every DAG route.

**v1 scope.** Implement §2–§7 except: HMAC, merge driver and the other v2 items listed in §7; `GET /graph?at=` supports
`snap:<name>` and git commits through `git show` (read-only) — if time runs short, snapshots first; `rd_exec` ships as
`server/research_deck/dag/rd_exec/` (stdlib only) and must work locally (`python -m research_deck.dag.rd_exec --spec … -- cmd`),
remote dispatch is out of scope; `paper.py` handles `% rd:sec <id>` … `% rd:end` anchors, `{{name}}` bindings and
`paper/generated/rdvalues.tex`. `envs/<platform>.json` may be written by hand or by the experiments slice.

**Service interface for other packages** (`server/research_deck/dag/service.py`; every function takes `pid`, never raises
for a project without a DAG — it returns empty results — and is cheap thanks to the evaluation cache):

```python
def graph(pid) -> dict                       # same as GET /dag/graph: {"nodes", "eval", "lenses", "digest"}
def node(pid, node_id) -> dict | None        # same as GET /dag/nodes/{id}
def lenses(pid) -> dict                      # GET /dag/lenses
def recent_events(pid, limit=50) -> list[dict]
def experiment_freshness(pid, node_id, run_id=None, cell=None) -> dict
    # {"freshness": "fresh"|"stale"|"reusable"|"unknown", "level": <Freshness>, "reasons": [str], "cell": str|None,
    #  "footprint": [code paths of the run's trace], "run": run_id|None}
    # fresh = this run is the selected valid run of its cell; reusable = valid but not selected;
    # stale = the cell is stale/pending/orphaned; unknown = no node / no trace
def nodes_by_commit(pid) -> dict[str, list[str]]   # 7-char sha -> node ids whose history (git) or runs (git.head) cite it
def design_components(pid) -> list[dict]           # module nodes -> [{"id", "label", "node_id", "paths": globs, "description"}]
def claims_for_doc(pid, path) -> list[dict]
    # claim/section nodes tied to that file -> [{"id", "label", "text", "line", "evidence": [node ids], "freshness": <Freshness>,
    #  "values": {binding: value}}]  (line from the % rd:sec anchor or the first line containing the claim's macro/text)
def brief_data(pid) -> dict
    # {"stage", "lenses": counts, "revise": [top 10 {id, title, level, reason}], "rerun": [top 10], "confirmed": [facts],
    #  "attempts": [{alt_group, tried, chosen, dead: [{id, status, reason}]}], "open_proposals": [...], "gates": [...]}
def record_run(pid, record: dict, actor: str = "system") -> dict   # same as POST /dag/runs
```

**Experiment records ↔ runs.** `.research/experiments/<eid>.json` (experiments slice) carries `node_id` (an `exp.*` id)
and, when it finished, `run_id` (the DAG run record under `dag/runs/…`). The DAG run record carries `experiment: <eid>`.
