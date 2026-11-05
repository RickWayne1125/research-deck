# Installation

Research Deck runs on macOS or Linux. It is a Python server that also serves a prebuilt web app; you build the web app
once with Node.js.

## Requirements

| What | Version | Why |
|---|---|---|
| Python | 3.12 or later | the server |
| Node.js and pnpm | Node 20+, pnpm through `corepack enable` | building the web app |
| git | any recent | project history, the map's code fingerprints, the demo |
| Claude Code and/or Codex CLI | signed in | the AI conversation, reviews, drafting (optional: everything else works without) |
| draw.io, OmniGraffle, DataGraph | — | editing native figures (optional) |

## Install

```bash
git clone https://github.com/RickWayne1125/research-deck.git
cd research-deck
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
scripts/dev.sh
```

`scripts/dev.sh` installs the web app's dependencies on first run (`pnpm install --frozen-lockfile`), builds it and
serves everything at <http://127.0.0.1:8765>. If pnpm is not on your `PATH`, point `RD_NODE_BIN` at a folder that holds
`node` and `pnpm`.

On first start, Research Deck creates a demo project, `toycache` (a made-up cache-eviction study with an outline, a
small map, runs, a paper and two figures), in `~/.research-deck/demo/`. The [tour](quickstart.md) walks through it.

!!! tip "Trying it without an AI CLI"
    `RD_FAKE_AGENT=1 scripts/dev.sh` answers every agent request with canned replies, so you can explore the whole UI
    offline.

## Run it as a service (macOS)

```bash
scripts/launchd.sh install     # start at login, restart if it exits
scripts/launchd.sh status      # loaded? answering?
scripts/launchd.sh restart     # after an update
scripts/launchd.sh uninstall
```

The agent logs to `~/.research-deck/logs/server.log`. The server still listens on 127.0.0.1 only.

## Open it from your other devices (optional)

With [Tailscale](https://tailscale.com), publish it to your tailnet only (never Funnel):

1. Add the tailnet block to `~/.research-deck/settings.json`:
   ```json
   {"tailnet": {"host": "<machine>.<tailnet>.ts.net", "https_port": 8765, "owners": ["you@example.com"]}}
   ```
2. Restart Research Deck.
3. Run `tailscale serve --bg --https=8765 http://127.0.0.1:8765`.

Requests that come through Serve are accepted only from the listed owners.

## Update

```bash
git pull
.venv/bin/pip install -e '.[test]'
(cd web && pnpm install --frozen-lockfile && pnpm build)
scripts/launchd.sh restart     # or stop and start scripts/dev.sh again
```

An open browser tab picks up the new version when you reload it.

## Develop

```bash
scripts/dev.sh --vite             # backend + Vite dev server with hot reload on http://127.0.0.1:5173
.venv/bin/pip install -e '.[dev]' # pytest and ruff, as CI runs them
```

See [Contributing](../contributing.md) for the checks and the workflow.

## Uninstall

Remove the clone, `~/.research-deck/` (the registry, settings and the demo) and, on macOS,
`scripts/launchd.sh uninstall` first. Each project keeps its own `.research/` folder; delete it if you no longer want
Research Deck's records for that project.
