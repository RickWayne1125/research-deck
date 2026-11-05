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
GPU hours and cost. Cells blocked by *implement first* (the code they need is not written yet) wait. Planning queues
nothing; you queue runs.

## Resources

The **Resources** tab shows compute: platforms, machines, GPUs, quota and cost. Today it shows labeled demo data.
Experiment records name their target platform in free text; the map's experiment nodes name it in `spec.platform`, and
`.research/dag/envs/<platform>.json` holds that platform's environment fingerprint and an optional
`usd_per_gpu_hour` used in cost estimates.
