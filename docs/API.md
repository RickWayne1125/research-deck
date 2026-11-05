# Research Deck — HTTP API

All JSON. Project-scoped routes start with `/api/projects/{pid}`. Types are those of `web/src/types.ts`.
Every mutating request carries `X-RD-Request: 1` (see ARCHITECTURE.md § Safety). Slice-specific extras that the
implementations added (extra fields, convenience routes) are documented in each package's api.py docstrings.
The research DAG's routes are in docs/DAG.md (§ HTTP API).

## Core (implemented: server/research_deck/{projects,system,events}.py)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/system/health | | `Health` |
| GET | /api/events?project=pid | SSE; events named by topic (`dag`, `file`, `sessions`, `agent` (a conversation run finished), `experiments`, `figures`, `writing`, `project`) | `ProjectEvent` |
| GET | /api/projects | | `ProjectSummary[]` |
| POST | /api/projects | `{root, name?, kind?: research\|engineering, state?: ".research-<slug>"}` | `ProjectSummary` (creates the state folder; `state` lets a second project share the folder) |
| DELETE | /api/projects/{pid} | | `{ok}` (forgets it; files untouched) |
| GET | /api/projects/{pid} | | `ProjectDetail` |
| PATCH | /api/projects/{pid}/config | partial `ProjectConfig` | `ProjectConfig` |
| GET | /api/projects/{pid}/tree | `?dir=&depth=` | `TreeNode[]` |
| GET | /api/projects/{pid}/file | `?path=` | `FileContent` |
| PUT | /api/projects/{pid}/file | `{path, content, base_sha?}` | `{path, sha, mtime}`; 409 `{message, sha}` if the file changed on disk |

## Agents (agents/)

A project has one conversation; `{panel}` in the routes below is `project` (the older view names `writing`, `coding`,
`experiments`, `visualization` are accepted and mean the same conversation).

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/agents/catalog | | `AgentCatalog` |
| GET | /api/projects/{pid}/sessions | | `SessionsDoc` |
| PUT | /api/projects/{pid}/sessions/{panel} | `{provider?, model?, effort?, fast?, permission?, session_id?, new_session?, title?}` | `PanelBinding` |
| POST | /api/projects/{pid}/agent/run | `RunRequest` | `RunStarted` |
| GET | /api/agent/runs?project= | | run summaries |
| GET | /api/agent/runs/{run_id} | | summary + `text` |
| GET | /api/agent/runs/{run_id}/stream | SSE, event name `agent`, `id` = index (Last-Event-ID resumes) | `AgentEvent` … `done` |
| POST | /api/agent/runs/{run_id}/cancel | | `{ok}` |
| GET | /api/projects/{pid}/sessions/discover | `?provider=claude|codex` | `DiscoveredSession[]` (existing sessions whose cwd is the project root) |
| GET | /api/projects/{pid}/transcript/{panel} | `?limit=` | `TranscriptEntry[]` (dashboard record; plus imported tail of a bound session when available) |
| POST | /api/projects/{pid}/handoff | `{panel, to, smart?: bool}` | `{file, summary, pending: true}`; switches the conversation's active backend to `to` |
| GET | /api/projects/{pid}/brief | | `{markdown, generated_at}` (regenerates `.research/context/BRIEF.md`) |
| GET | /api/mcp/config | `?project=` | `{claude: {...}, codex: {...}, commands: {claude: "claude mcp add …", codex: "codex mcp add …"}}` (to register the MCP server in your own CLI; never registers by itself) |

## Writing (writing/)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /writing/docs | | `WritingDoc[]` (.tex and .md under the paper dir and docs/notes) |
| POST | /writing/review | `{path, passes: ReviewPass[], text?: string, range?: {start_line, end_line}}` | `ReviewResult` (status running); progress via topic `writing` and GET below |
| GET | /writing/review/{review_id} | | `ReviewResult` |
| POST | /writing/findings/{review_id}/{finding_id} | `{status: 'accepted'|'rejected', reason?}` | `Finding`; a rejection with a reason becomes a learned rule |
| GET / PUT | /writing/glossary | `{terms: GlossaryTerm[]}` | same |
| GET / PUT | /writing/rules | `{rules: LearnedRule[]}` | same |
| GET | /writing/versions | `?path=` | `DocVersion[]` (snapshots + git history of the file) |
| POST | /writing/versions | `{path, label?}` | `DocVersion` (snapshot of the current file) |
| GET | /writing/versions/{version_id} | `?path=` | `{content}` |
| GET | /writing/claims | `?path=` | `{claims: [{id, label, text, line, evidence: [node ids], freshness}]}` from the DAG (claim nodes bound to this doc) |

Review passes run in this fixed order, each its own ephemeral request on the conversation's backend:
`typo` (typos, grammar, punctuation, mistyped LaTeX; effort low/medium) → `terminology` (glossary + one term written
two ways; medium) → `wording` (plain research writing: clarity and compression; high) → `consistency` (numbers,
notation, claims vs. DAG evidence; high) → `logic` (claim chain, unsupported claims; xhigh). The Paper view's
"AI proofread" asks for the first three.
Every finding quotes the exact text to change (`quote` + `before` disambiguate the location).

## Coding (coding/)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /git/status | | `GitStatus` |
| GET | /git/log | `?limit=&path=` | `GitCommit[]` (with `node_ids` of DAG nodes whose versions pin that commit) |
| GET | /git/diff | `?from=&to=&path=` (no from/to: working tree vs HEAD) | `DiffResult` |
| GET | /git/show | `?rev=&path=` | `{content}` (file at a revision) |
| GET | /architecture | | `Architecture` (modules/imports from the code roots + components mapped to DAG design nodes; the context of explanations) |
| POST | /coding/review | `{from?, to?, paths?}` | `RunStarted`; final answer is JSON `{findings: CodeFinding[]}` (parse with extractJson) |
| POST | /coding/explain | `{path, start_line, end_line}` | `RunStarted` (markdown answer) |

## Experiments and resources (experiments/)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /experiments | | `Experiment[]` (records + DAG freshness) |
| GET | /experiments/{eid} | | `Experiment` |
| POST | /experiments | `{title, node_id?, config, target, command?}` | `Experiment` (status planned) |
| PATCH | /experiments/{eid} | partial | `Experiment` |
| GET | /experiments/{eid}/logs | `?offset=` (byte offset; < 0 = tail) | `{lines, next, size, eof, source, …}` complete lines, ANSI stripped (for agents and summaries) |
| GET | /experiments/{eid}/logs/stream | `?offset=` (< 0 = last 256 KB); `Last-Event-ID` resumes | SSE: `meta`, `data {data, offset}` (raw text: ANSI, `\r` redraws), `reset`, `notice`, `eof` — the panel's terminal |
| GET | /experiments/{eid}/logs/raw | | the log as a text/plain attachment (last 20 MB) |
| GET | /api/resources | | `Resources` (platforms, nodes, GPU telemetry, quota and cost; `source: "demo"` = labeled demo data) |

## Visualization (viz/)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/style | `?project=` | `StyleTokens` (the built-in house style + project `.research/style.json`) |
| GET | /figures | | `Figure[]` |
| POST | /figures | `{kind, title, node_id?}` | `Figure` (created from a template) |
| PATCH | /figures/{fid} | partial | `Figure` |
| POST | /figures/{fid}/render | `{source?: string}` (unsaved script to render) | `RenderResult` (matplotlib → SVG; drawio: client-side export saved via PUT preview) |
| PUT | /figures/{fid}/preview | `{svg?: string, png_base64?: string}` | `Figure` |
| GET | /figures/{fid}/preview | | the image |
| POST | /figures/{fid}/ai-edit | `{instruction, source?}` | `RunStarted`; the answer holds the complete new source in one fenced block; the client shows a diff and saves on accept |
| POST | /figures/{fid}/open-native | | opens the file in OmniGraffle / DataGraph / draw.io desktop if installed (`{ok, app}`) |
| POST | /figures/{fid}/export-native | | exports PDF/PNG through the native app or CLI when installed |

## On-disk formats shared between slices (all under `<project>/.research/`)

| File | Owner | Shape |
|---|---|---|
| `project.yaml` | core | `ProjectConfig` |
| `sessions.json` | agents | `SessionsDoc` |
| `experiments/<id>.json` | experiments | an `Experiment` without the derived `freshness` / `stale_reasons`; `logs` = project-relative log path, e.g. (the demo's) `{"id": "lookahead", "node_id": "exp.lookahead", "cell": null, "title": "...", "status": "succeeded", "target": {"platform": "workstation", "node": "workstation", "gpus": 1, "gpu_type": "GPU-24GB"}, "config": {...}, "command": "python -m toycache.sim --config configs/base.yaml --config configs/lookahead.yaml", "code": {"commit": "<sha it ran on>", "footprint": ["toycache/sim.py", ...]}, "dataset": "synthetic trace (seed 7)", "env": "python 3.12", "metrics": {"hit_rate": 0.58}, "started_at": "...", "finished_at": "...", "run_id": "r-20261019-1430-957a", "logs": "experiments/logs/lookahead.log", "artifacts": ["experiments/results/lookahead.csv"]}` |
| `figures.json` | viz | `{"version": 1, "figures": [{"id", "title", "kind", "source", "data": [], "node_id", "caption", "updated_at"}]}`; previews at `figures/previews/<id>.svg` (or `.png`) |
| `writing/glossary.yaml` | writing | `{"terms": [{"term", "preferred", "avoid": [], "note"}]}` |
| `writing/rules.json` | writing | `{"rules": LearnedRule[]}` |
| `writing/reviews/<review_id>.json` | writing | `ReviewResult` |
| `writing/snapshots/<path-slug>/<ts>.txt` + `index.json` | writing | snapshots of a document |
| `architecture.yaml` | coding | `{"components": [{"id", "label", "node_id", "paths": [globs], "description"}]}` (optional; components also come from DAG design nodes) |
| `style.json` | viz | optional overrides of `StyleTokens` (`active_palette`, `font`, `series`) |
| `dag/…` | dag | docs/DAG.md |
| `context/…` | agents | docs/ARCHITECTURE.md § Agents and context sharing |
