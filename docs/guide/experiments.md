# Tasks and experiments

Tasks hang on outline items; the work happens in its own view. A task's button opens it there, and a bar above
Experiments, Code and Paper names the task you are working on and the items it serves (mark it in progress or done,
or go back to the outline).

| Task | Opens | Can make |
|---|---|---|
| Experiment | its node's latest run, or a new run of its node | an experiment node at its phase's stage (idea S1, insight S2, design S5, evaluation S6) |
| Figure | its figure in **Paper › Figures** | — |
| Code | **Code** | — |
| Literature | the survey's notes | a survey of the task's topic (the task and the items it serves) |

## Experiment records and runs

An **experiment record** (`.research/experiments/<id>.json`) is a planned or finished run: title, map node, command,
config, target machine and GPUs, metrics, logs. Research Deck never submits, cancels or dispatches a run: a queued run
waits as a record until something outside Research Deck runs it, and its results come back as a record.

Each record shows its **freshness** from the map:

| Freshness | Means |
|---|---|
| fresh | this run is the current result of its cell |
| reusable | still valid, but another run is the current one |
| stale | something it read changed since (code, config, data, environment, an upstream result): rerun it |
| unknown | no map node, or no trace of what it read |

Open a run to see why it is stale (which file or value changed, from what to what) and to follow its log in a
read-only terminal.

## The run plan

**Experiments › Plan** lists the stale and not-yet-run cells of live experiments in dependency waves, with estimated
GPU hours and what they cost on each platform's [resource pool](#resource-pools). Cells blocked by *implement first*
(the code they need is not written yet) wait. Planning queues nothing; you queue runs.

## Resource pools

A **resource pool** is compute you can run on: this computer, a GPU box you reach over ssh, a lab server, a Slurm
cluster, a cloud allocation. **Experiments › Resources** shows each pool's machines, GPUs (utilization, memory,
temperature, power when the source reads them), quota, spend, price and what the agents may still queue there today.
Research Deck only reads pools: nothing here starts, stops or dispatches work.

Pools belong to the computer, not to a project: one file each in `~/.research-deck/pools/<id>.yaml`, which you can copy
to someone else (it holds no secrets). A pool's **id is the platform name** that experiment records (`target.platform`)
and the map's experiment nodes (`spec.platform`) already use, so names you wrote before match by themselves; names no
pool answers to are listed with a button to register them.

### Adding, changing and removing a pool

**Settings › Resource pools** lists the pools. A new user starts with none: **Add this computer** makes a pool that
reads this machine (not billed; agents may not queue there), and **Add a pool** opens a three-step wizard:

1. **Source**: where the pool's state comes from.

    | Source | Reads |
    |---|---|
    | Manual | the machines and GPUs you type in; no live data (a lab server you cannot read, a cloud machine not yet up) |
    | This machine | this computer: its NVIDIA GPUs (nvidia-smi), CPU load and memory |
    | Command | a local program that prints one [rd-pool/1](../examples/pool-adapter.md) document, run from its argument list, without a shell |
    | HTTP endpoint | an address that returns the same document: `https://`, or plain `http://` on this machine only |

    Presets fill in the bundled example adapters, which you can change: one machine over ssh (`scripts/pools/rd_pool_ssh.py`)
    and a Slurm cluster read on its login node (`scripts/pools/rd_pool_slurm.py`).

2. **Fill in and test**: the name, the id, the kind (this machine, home, lab, cluster, cloud), the command or address, a
   credential, how often to read it. **Test** reads it once and saves nothing: what it found, what was wrong with the
   document (a percentage where a share was expected, a quota without a limit), and the raw JSON.

3. **Prices and budget**, then **Save**. A command source is shown in full before it is saved: it runs with your
   permissions.

**Edit**, **Refresh** (read now) and **Remove** sit on each pool. Removing moves the file to
`~/.research-deck/pools/.trash/`; experiment records keep the platform name, and the credential stays in the keychain.
**Import a pool file** reads a pool file someone gave you and opens it in the wizard, to review and test before saving.

Only you add, change, test or refresh pools. Agents see them (`rd_pools`) and cannot change them.

### Credentials

A pool names its credential, never holds it: `keychain:<name>` (a macOS keychain item you add yourself, e.g.
`security add-generic-password -s js2-reader -a $USER -w`) or `env:<VARIABLE>`. When the pool is read, Research Deck
takes the secret out and hands it to that one command as `RD_POOL_SECRET`, or sends it to that one address as
`Authorization: Bearer`. It is never written to a file or a log. A source can report when its credential expires; the
pool then warns 30 days ahead.

### Reading, and what a failed read shows

Each pool is read at its own interval (this machine every 10 s, a command every 10 minutes by default), in the
background, while a page that shows it is open. When a read fails, the pool keeps showing its last good reading with
the reason (the command's exit status and stderr, the address's answer) instead of going blank.

### Prices and estimates

A price is per GPU-hour or per machine-hour, matched to everything or to one GPU model, flavor or machine, in a unit:
money as a currency code (`USD`, `CNY`) or a quota unit of your own (`SU`, `credits`).

- What you write in the pool comes first, then what the source reports; the most specific match wins.
- Your own machines (this machine, home, lab) with no price are not billed. A cluster or cloud with no price shows
  **price unknown**, and an estimate never counts it as 0.
- A machine-hour price is spread over the machine's GPUs.
- Different units are never added: the run plan totals each unit separately (`0.58 USD + 128 SU`).

Estimates appear in **New experiment** (estimated hours × GPUs × the price there), the run plan (per platform, per wave,
in total) and the map's impact preview. Estimated GPU-hours come from the map: the median of the cell's last 3
successful runs, then the node's median, then the node spec's `est_hours` × `gpus`. A platform with no pool falls back
to `usd_per_gpu_hour` in the map's `.research/dag/envs/<platform>.json`. When a plan would go past a pool's quota or its
monthly budget in that unit, the plan says so first; it never stops you.

### Budgets and agents

- `budget.agent_gpu_hours_per_day`: the GPU-hours agents may queue on this pool by themselves, per project and day
  (0 or unset: never). Past it they stop and ask you.
- `budget.month`: a monthly cap in one unit, checked by the run plan.

Agents may queue runs by themselves only on pools the project uses whose budget gives them GPU-hours. A platform with
no pool keeps the project's `policy.agent_auto_run` (see [Configuration](configuration.md)).

### Which pools a project uses

Every project uses every pool by default. Untick **Used by this project** on a pool in Settings to leave it out: the
Resources tab then shows it under **All** only, the new-experiment dialog stops suggesting it, and agents may not
queue there. The choice is `resources.pools` in `.research/project.yaml`.

### Checking a pool from the terminal

```bash
.venv/bin/python -m research_deck.pools list
.venv/bin/python -m research_deck.pools check <id>
.venv/bin/python -m research_deck.pools check --file out.json
```

`check` reads the pool once (or checks a document an adapter printed) and lists what is missing, wrong or in the wrong
unit; it exits 0 when the document is clean, 1 with warnings, 2 when it is not rd-pool/1 at all.
