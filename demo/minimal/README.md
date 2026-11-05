# toycache: a Research Deck demo

**Synthetic demo. All numbers are made up.** The trace is synthetic and the result files were written by hand to tell
a short story; nothing here describes a real system, measurement or machine.

toycache simulates a small GPU-side block cache in front of host memory and compares three eviction policies: LRU
(the baseline), LFU (attempt A, refuted) and lookahead eviction (attempt B, chosen), which evicts the cached block
that the next queued requests need last.

```bash
python -m toycache.sim --config configs/base.yaml                          # LRU
python -m toycache.sim --config configs/base.yaml --set policy=lfu         # attempt A
python -m toycache.sim --config configs/base.yaml --config configs/lookahead.yaml   # attempt B
```

| Path | What it holds |
|---|---|
| `toycache/` | the trace generator, the simulator and the three policies |
| `configs/` | `base.yaml` (trace, cache size) and `lookahead.yaml` (layered over it) |
| `experiments/` | the results and logs the experiment records point to |
| `paper/main.md` | one section with three deliberate writing issues for the Writing panel's review to find |
| `figures/` | a matplotlib script with its CSV, and a draw.io diagram |
| `.research/` | Research Deck's state: project, experiment records, figure registry, glossary, research DAG |

Research Deck replays a short history when it creates this project: the LRU baseline, attempt A, attempt B with the
paper and figures, then a fix to `toycache/lookahead.py` that leaves one experiment stale while the baseline stays
reusable. One uncommitted comment in `toycache/lru.py` gives the Coding panel a working-tree diff.
