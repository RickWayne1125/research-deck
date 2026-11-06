# A resource pool of your own

A [resource pool](../guide/experiments.md#resource-pools) reads its state from a source. For anything Research Deck
cannot read by itself — a GPU box over ssh, a Slurm cluster, a cloud allocation, your lab's own tooling — the source is
an **adapter**: a small program (or an HTTP endpoint) that prints one **rd-pool/1** JSON document. Research Deck holds
no vendor logic; the adapter does.

This page writes one, checks it, and adds it as a pool.

## The document

```json
{
  "protocol": "rd-pool/1",
  "as_of": "2026-11-05T22:10:41Z",
  "nodes": [{
    "id": "gpu-box", "label": "GPU box",
    "status": "online",
    "state": "running",
    "flavor": "g3.large",
    "gpus": [{"model": "RTX 5090", "count": 1, "mem_total_mib": 32607, "mem_used_mib": 20480,
              "util": 0.93, "temp_c": 71, "power_w": 410}],
    "cpu": 0.31, "ram": 0.58,
    "running": ["vllm-bench"], "queued": 1
  }],
  "quota": [{"name": "GPU SU", "used": 12400, "limit": 20000, "unit": "SU"}],
  "spend": {"amount": 132.5, "unit": "USD", "since": "2026-11-01", "kind": "billed"},
  "prices": [{"item": "gpu_hour", "match": {"gpu": "RTX 5090"}, "amount": 0.08, "unit": "USD"}],
  "credential": {"expires_at": "2026-11-25T22:30:00Z"},
  "capabilities": ["inventory", "telemetry", "quota", "spend", "prices"]
}
```

| Field | What |
|---|---|
| `protocol` | required: `"rd-pool/1"` |
| `as_of` | when it was read (UTC, ISO 8601) |
| `nodes` | the machines (`[]` when there are none): `status` online, offline or unknown; `state` a cloud machine's power state (running, stopped, …); `flavor` its size or partition, for prices matched by flavor |
| `nodes[].gpus` | one entry per GPU model with its `count`; memory in MiB, `util` 0–1, temperature °C, power W |
| `cpu`, `ram` | shares 0–1 |
| `quota` | what is used of what limit, in its own unit; no `limit` means *limit unknown*, not *no limit* |
| `spend` | what was spent since when, in a unit; `kind` billed (from a bill) or estimate |
| `prices` | `item` gpu_hour or node_hour, `match` everything or one `gpu`, `flavor` or `node`, an `amount` and a `unit` |
| `credential.expires_at` | when the credential the pool uses runs out (the pool warns 30 days ahead) |
| `capabilities` | what the source can tell; derived from the content when absent |

The rules:

- **Unknown is null, never 0.** Leave a field out or write `null`; Research Deck shows *unknown* and never counts it as
  0 in an estimate.
- **Units are explicit.** Money as a currency code (`USD`, `CNY`), quota in its own unit (`SU`, `credits`), memory MiB,
  temperature °C, power W, utilization and shares 0–1 (a percentage is read as one, with a warning).
- **Fields Research Deck does not know are ignored**, so an adapter may print more.
- **A command** runs from its argument list, without a shell, with the pool's timeout (30 s by default); it prints the
  document on stdout and exits 0. A non-zero exit and its stderr become the pool's read error. It gets `RD_POOL_ID`,
  and `RD_POOL_SECRET` when the pool names a credential; its working folder is `~/.research-deck/pools/`.
- **An HTTP endpoint** answers `GET` with the document (status 200). The credential, if any, comes as
  `Authorization: Bearer`. Only `https://` addresses, or plain `http://` on this machine; redirects are not followed.
- **Read-only.** The protocol has no way to start anything. Dispatching work would be another protocol, not a change to
  this one.

## A minimal adapter: one machine over ssh

```sh
#!/bin/sh
# rd-pool/1 for one machine: ssh there, run nvidia-smi, print the document
ssh -o BatchMode=yes gpu-box nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu \
    --format=csv,noheader,nounits |
python3 -c '
import json, sys, datetime
g = [l.strip().split(", ") for l in sys.stdin if l.strip()]
print(json.dumps({"protocol": "rd-pool/1",
  "as_of": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "nodes": [{"id": "gpu-box", "status": "online", "gpus": [
    {"model": n, "count": 1, "mem_total_mib": int(t), "mem_used_mib": int(u), "util": int(p) / 100}
    for n, t, u, p in g]}],
  "capabilities": ["inventory", "telemetry"]}))'
```

Save it as `~/bin/rd-pool-gpu-box`, make it executable, and check what it prints:

```bash
~/bin/rd-pool-gpu-box | .venv/bin/python -m research_deck.pools check --file -
```

`check` lists what is missing, wrong or in the wrong unit, and exits 0 when the document is clean, 1 with warnings,
2 when it is not rd-pool/1.

The repository ships two fuller adapters you can use as they are or start from (standard library only):

| Adapter | Reads |
|---|---|
| `scripts/pools/rd_pool_ssh.py <host>` | one machine over ssh: its GPUs, load, memory and GPU processes |
| `scripts/pools/rd_pool_slurm.py <login-node> [--partition gpu] [--user]` | a Slurm cluster's nodes, their GPUs (GRES), load, memory and running jobs, from `sinfo` and `squeue` on the login node (`--local` runs them here) |

Both use ssh in batch mode, so set up a key or an ssh-agent for the host first (`ssh <host> true` must not prompt).

## Add it as a pool

In **Settings › Resource pools › Add a pool**, choose **Command** (or a preset), and put the program and its arguments
one per box: `~/bin/rd-pool-gpu-box`. Give the pool the id your experiment records already use for that machine, choose
its kind, and **Test**: the result shows the machines, quota and prices it read, any warnings, and the raw JSON. Then
set prices and the budget and save. The same as a file, `~/.research-deck/pools/gpu-box.yaml`:

```yaml
id: gpu-box
label: GPU box
kind: home
source: {type: command, run: [~/bin/rd-pool-gpu-box], every: 30, timeout: 30}
credential: null
prices: [{item: gpu_hour, match: {}, amount: 0.08, unit: USD}]    # electricity; leave out and it is not billed
budget: {agent_gpu_hours_per_day: 8}
```

If the adapter needs a token, keep it in the keychain (`security add-generic-password -s gpu-box-reader -a $USER -w`),
set `credential: keychain:gpu-box-reader`, and read `RD_POOL_SECRET` in the adapter.
