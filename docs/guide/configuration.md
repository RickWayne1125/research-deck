# Configuration

## Machine settings: `~/.research-deck/settings.json`

Your own defaults, shared by every project on this machine. Missing keys take the built-in defaults.

```json
{
  "agent_defaults": {"claude": {"model": "claude-opus-5-5", "effort": "high"}, "codex": {"effort": "high"}},
  "dag_defaults": {"gates": {"blocking": false}, "autocommit": {"enabled": false}, "stages": {"mode": "strict"}},
  "new_projects": {"dir": "~/Research", "git_init": true,
                   "survey": {"sources": ["arxiv", "semantic_scholar", "openalex"], "count": 15,
                              "download_pdfs": true, "papers_dir": "papers"}},
  "tailnet": {"host": "<machine>.<tailnet>.ts.net", "https_port": 8765, "owners": ["you@example.com"]}
}
```

| Key | What |
|---|---|
| `agent_defaults` | model and effort per CLI for new conversations |
| `dag_defaults` | defaults for new maps: blocking gates, git autocommit of the map, stage rules (`strict`, `ahead`, `free`) |
| `new_projects` | where **New from an idea** creates folders, `git init`, and the early survey's sources, size and PDF folder |
| `tailnet` | accept requests through Tailscale Serve from these owners only (see [Installation](../getting-started/install.md)) |

Most of these are also in **Settings**.

## Resource pools: `~/.research-deck/pools/<id>.yaml`

One file per [resource pool](experiments.md#resource-pools), shared by every project on this machine. Settings writes
them; you may also write or copy one by hand (it holds no secrets).

```yaml
id: jetstream2                  # the platform name experiment records and the map use
label: Jetstream2
kind: cloud                     # local | home | lab | cluster | cloud
names: [Jetstream2 g3.large]    # other platform names it answers to (optional)
source:
  type: command                 # manual | local | command | http
  run: [rd-pool-openstack, --cloud, js2]    # command: an argument list, no shell
  every: 600                    # seconds between reads
  timeout: 30
credential: keychain:js2-reader # or env:VARIABLE; a name only
prices:                         # override what the source reports
  - {item: node_hour, match: {flavor: g3.large}, amount: 64, unit: SU}
budget:
  agent_gpu_hours_per_day: 0    # agents may not queue here
  month: {amount: 20000, unit: SU}
```

| Key | What |
|---|---|
| `id` | lowercase letters, digits and `- _ .`; matched against platform names ignoring case |
| `names` | other platform names the pool answers to, such as a record's description of the machine; matched ignoring case and extra spaces, and each name belongs to one pool ([Platform names](experiments.md#platform-names)) |
| `source.type` | `manual` (with `source.inventory.nodes`), `local`, `command` (with `source.run`) or `http` (with `source.url`: https, or http on 127.0.0.1 / localhost) |
| `source.every`, `source.timeout` | seconds between reads (10–86400; default 10 local, 600 command, 60 http) and per read (1–120, default 30) |
| `credential` | `keychain:<service>` or `env:<VARIABLE>` |
| `prices` | `{item: gpu_hour \| node_hour, match: {gpu \| flavor \| node: …}, amount, unit}` |
| `budget` | `agent_gpu_hours_per_day` (per project and day) and `month: {amount, unit}` |

The last reading of each pool is cached in `pools/.cache/<id>.json`; a removed pool's file goes to `pools/.trash/`.

## A project: `.research/project.yaml`

Name, kind (`research` or `engineering`), `views`, summary, venue, deadline, stage, language, and where the paper
(`paper.main`, `paper.dir`), code (`code.roots`), figures and experiment records live. `resources.pools: [ids]` limits
the resource pools the project uses (absent: all of them). `outline.file` moves the outline's Markdown file (default
`notes/outline.md`).

## A project's map: `.research/dag/config.yaml`

The map's policy: gates (and whether they block), autocommit, stage rules, code and config roots for fingerprints, and
`policy.agent_auto_run` (the node kinds agents may queue, and, for platforms that are no resource pool, the platforms
and their daily GPU-hour budget; a pool's own budget covers the pool).

## Outline templates: `~/.research-deck/templates/`

Your outline templates, one YAML file each; see [An outline template of your own](../examples/template.md).

## Environment variables

| Variable | Default | What |
|---|---|---|
| `RD_PORT` | `8765` | the port (the server always binds 127.0.0.1) |
| `RD_LOCAL_DIR` | `~/.research-deck` | machine state: registry, settings, templates, resource pools, demo |
| `RD_FAKE_AGENT` | unset | `1`: canned agent answers instead of the CLIs |
| `RD_NO_DEMO` | unset | `1`: do not create the demo project |
| `RD_CLAUDE_CLI`, `RD_CODEX_CLI` | found on `PATH` | paths to the CLIs |
| `RD_FIGURE_PYTHON` | the project venv's Python | the Python that renders matplotlib figures |
| `RD_EXTRA_ORIGINS` | none | extra allowed origins, comma-separated |
| `RD_NODE_BIN` | none | a folder with `node` and `pnpm` for `scripts/dev.sh` |
| `RD_POOLS_SYNC` | unset | `1`: read resource pools on the spot instead of in the background |
