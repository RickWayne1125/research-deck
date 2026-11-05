# Why a result goes stale

The demo has one stale result on purpose. Following it shows how Research Deck decides what to rerun.

## The story in four commits

| Commit | What changed |
|---|---|
| c1 | the LRU baseline: simulator, synthetic trace, configs; the baseline run |
| c2 | an LFU attempt; its run (0.37 at 64 blocks, below LRU) and its abandonment |
| c3 | lookahead eviction (`toycache/lookahead.py`); its run raises the hit rate |
| c4 | a change to `toycache/lookahead.py` after the lookahead run |

## What each run read

`rd_exec` runs an experiment under a tracer that records what the program read: source files, config keys, datasets,
the environment. The lookahead run's trace includes `toycache/lookahead.py`; the baseline runs' traces do not.

## What the change invalidates

After c4, the lookahead run's fingerprint of `toycache/lookahead.py` no longer matches the file, so:

- the lookahead experiment is **stale** (open the run in **Experiments**: the reason names the file and the two
  fingerprints);
- the baseline runs stay **fresh**: c4 did not touch anything they read, and a comment-only change would not count
  either;
- the claim that cites the lookahead result shows it may be out of date, and the outline item backed by it (3.1's
  chosen direction) is *in progress* rather than holding;
- **waiting for you** and the run plan list the lookahead cell to rerun, with an estimate.

The sensitivity sweep (5.2) has never run, so it is *unbuilt*: also in the plan, as a first run rather than a rerun.

## The rules behind it

- A run is reused when everything it read is unchanged. Unchanged facets of a node mean reuse, too: editing one design
  decision only touches what read that decision.
- What a run cannot see (compiled code, a JIT) is declared on its module node as *opaque*, so changes there count.
- Nothing reruns by itself. The plan says what is stale and why; you (or, within the project's policy, an agent)
  queue the runs.

The details, including how fingerprints are taken and compared, are in
[the DAG reference](../DAG.md) (sections 4 and 5).
