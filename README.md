# Research Deck

A local research dashboard over your project folders. It keeps a **research map** — what you tried, what is
confirmed, what a change invalidates, which experiments must be rerun — and one **AI conversation per project**,
backed by the Claude Code or Codex CLI, next to your paper, your experiments and your code. Chinese and English UI.

本地运行的科研工作台：用一张「研究地图」管理想法、证据和实验之间的依赖（尝试过什么、哪些已确认、改动之后哪些要复核或重跑），
每个项目一个 AI 对话（Claude Code 或 Codex），旁边是稿件、实验和代码。界面支持中文和英文。


## What it does

| View | |
|---|---|
| **Today** | What needs you now, each with the action that settles it: agent proposals, drafted nodes to review, open decisions, experiments to run, failed runs. Above it, the stage the project is in and how many checks stand before the next one. |
| **Map** | The research DAG as a list grouped by stage (or as a graph). Rows show only exceptions; one opens in place with what it rests on, what depends on it, and the options of a decision — choosing one previews its impact first. Review drafts with J / K / Y / N. |
| **Experiments** | Runs with their freshness from the map, the log in a read-only terminal that follows the file, the run plan for what must be rerun, and a resources tab (demo data). |
| **Paper** | Edit `.tex` / `.md` with preview; **AI proofread** runs fixed passes (typos → terminology → wording) and shows suggestions in the text to accept or reject. Figures: draw.io in the official embedded editor, matplotlib with live preview, OmniGraffle / DataGraph when installed; an AI edit is shown as a diff before anything is written. |
| **Code** | Git history and diffs of the project's repositories, AI code review and explanations. |
| **Conversation** (⌘J) | One thread per project, whichever view you ask from; what you are looking at is attached. Switch between Claude and Codex and the context is handed over. Model, effort and Fast sit behind one button. |

Agents never change the map directly: what they draft is *proposed* until you accept it, and every change shows its
impact (which nodes need a review, which experiments a rerun) before it is applied. ⌘K jumps anywhere.


## Quick start

Requirements: macOS or Linux, Python 3.12+, Node.js 20+ with pnpm (`corepack enable`), git. For the AI parts, the
[Claude Code](https://docs.claude.com/en/docs/claude-code) and/or [Codex](https://github.com/openai/codex) CLI, signed
in. Optional: draw.io, OmniGraffle or DataGraph for native figures.

```bash
git clone https://github.com/RickWayne1125/research-deck.git && cd research-deck
python3.12 -m venv .venv && .venv/bin/pip install -e '.[test]'
scripts/dev.sh                    # installs and builds the web app, then serves http://127.0.0.1:8765
```

On first start a demo project (`toycache`, a made-up cache-eviction study with a small DAG, runs, a paper and two
figures) is created in `~/.research-deck/demo/`. Add your own project from the project menu: pick its folder and its
kind — **research** (the full pipeline) or **engineering** (code, documents, runs and figures, without the map).
Research Deck keeps its state in a `.research/` folder inside the project and never touches anything else.

```bash
RD_FAKE_AGENT=1 scripts/dev.sh    # try the UI without calling Claude or Codex (canned answers)
scripts/dev.sh --vite             # backend + Vite dev server with hot reload on http://127.0.0.1:5173
.venv/bin/python -m pytest -q     # backend tests
(cd web && pnpm test)             # frontend tests
```

## Configuration

Machine-local state lives in `~/.research-deck/` (`RD_LOCAL_DIR`): the project registry, the agents' token and
`settings.json` with your own defaults:

```json
{
  "agent_defaults": {"claude": {"model": "claude-opus-5-5", "effort": "high"}, "codex": {"effort": "high"}},
  "dag_defaults": {"gates": {"blocking": false}, "autocommit": {"enabled": false}}
}
```

Each project's `.research/project.yaml` holds its name, kind, stage and where the paper, code, figures and experiment
records live; `.research/dag/config.yaml` holds the map's policy (gates, autocommit, what agents may queue).

**Run it as a service (macOS).** `scripts/launchd.sh install` adds a launchd user agent: it starts at login, restarts
if it exits and logs to `~/.research-deck/logs/server.log`. `restart` after an update, `status`, `uninstall`.

**Open it from your other devices (optional, Tailscale).** Add
`"tailnet": {"host": "<machine>.<tailnet>.ts.net", "https_port": 8765, "owners": ["you@example.com"]}` to
`settings.json`, restart, then `tailscale serve --bg --https=8765 http://127.0.0.1:8765` (tailnet only, never Funnel).
Requests through Serve are accepted only from the listed owners.

## Safety

The server listens on 127.0.0.1 only and refuses requests from other origins (a CSRF header is required for every
change, DNS rebinding is blocked). Agents run headless in the project folder: Claude Code restricted to the project
with only Research Deck's MCP server; Codex in a read-only sandbox unless you allow writes for the conversation.
Nothing submits jobs to remote machines or creates credentials. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (Safety).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the pieces fit, conventions, safety, agents and context sharing
- [docs/API.md](docs/API.md): the HTTP API and on-disk formats
- [docs/DAG.md](docs/DAG.md): the research map's model — nodes, edges, freshness, impact preview, gates

## License

[MIT](LICENSE)
