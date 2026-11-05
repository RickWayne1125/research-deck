# Research Deck — HTTP API

All JSON. Project-scoped routes start with `/api/projects/{pid}`. Types are those of `web/src/types.ts`.
Every mutating request carries `X-RD-Request: 1` (see ARCHITECTURE.md § Safety). Slice-specific extras that the
implementations added (extra fields, convenience routes) are documented in each package's api.py docstrings.
The research DAG's routes are in docs/DAG.md (§ HTTP API).

## Core (implemented: server/research_deck/{projects,system,events}.py)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/system/health | | `Health` |
| GET | /api/events?project=pid | SSE; events named by topic (`dag`, `outline` (the outline or its tasks changed), `file`, `sessions`, `agent` (a conversation run finished), `experiments`, `figures`, `writing`, `project`, `survey` (the survey's state)) | `ProjectEvent` |
| GET | /api/projects | | `ProjectSummary[]` |
| POST | /api/projects | `{root, name?, kind?: research\|engineering, state?: ".research-<slug>"}` | `ProjectSummary` (creates the state folder; `state` lets a second project share the folder) |
| DELETE | /api/projects/{pid} | | `{ok}` (forgets it; files untouched) |
| GET | /api/projects/{pid} | | `ProjectDetail` |
| PATCH | /api/projects/{pid}/config | partial `ProjectConfig` | `ProjectConfig` |
| GET | /api/projects/{pid}/tree | `?dir=&depth=` | `TreeNode[]` |
| GET | /api/projects/{pid}/file | `?path=` | `FileContent` |
| PUT | /api/projects/{pid}/file | `{path, content, base_sha?}` | `{path, sha, mtime}`; 409 `{message, sha}` if the file changed on disk |

## New projects (start/)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/settings/new-projects | | `{dir, dir_expanded, default_dir, git_init, survey: {sources, count, download_pdfs, papers_dir}, stage_mode}` |
| PATCH | /api/settings/new-projects | any of `{dir (null resets), git_init, survey: {sources, count 1–60, download_pdfs, papers_dir}, stage_mode: strict\|ahead\|free}` | the settings (writes only these keys of ~/.research-deck/settings.json; `stage_mode` is `dag_defaults.stages.mode`) |
| POST | /api/projects/new | `{name, idea?, file?: {name (.md .txt .pdf), content_base64 (≤ 20 MB)}, folder?, survey?: {enabled, count?, download_pdfs?}}` | `{project: ProjectSummary, root, created, idea_file, upload, survey: Survey \| null}` |

`folder` missing: `<dir>/<name as a folder name>` (-2, -3 … when taken); an existing folder is used as it is. The idea is
saved as `notes/idea.md` (`idea-2.md` … when one exists) and an upload is kept in `notes/` (a PDF's text is extracted
with pypdf). A folder created here gets `git init` (setting `git_init`, unless it is inside a repository) and a
`.gitignore` with `<papers_dir>/*.pdf`. Both routes that change something are the researcher's only (403 for agents).

## Survey (survey/)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/projects/{pid}/survey | | the latest `Survey` or `null` |
| POST | /api/projects/{pid}/survey | `{idea?, count?, download_pdfs?, sources?}` (idea defaults to notes/idea.md) | `Survey`; 409 while one runs; 403 for agents |
| POST | /api/projects/{pid}/survey/cancel | | `{ok}` |

`Survey` (web/src/start/api.ts) is `.research/survey/<id>.json`: `{id, status: running|done|error|cancelled, step,
steps: {frame, search, select, download, draft, write: pending|running|done|error|skipped}, queries, search: {found,
sources}, candidates, papers: [{key, title, year, venue, url, role, takeaway, delta, closes_gap, status:
pending|running|done|failed|link, file, node, existing}], nodes, files: {bib, index, survey}, warnings, error, agent}`.
It writes `<papers_dir>/<bibkey>.pdf`, `<papers_dir>/references.bib` (new keys appended), `<papers_dir>/index.md` and
`notes/survey.md` (never overwriting: `survey-2.md` …), drafts a `problem` node (unless a live one exists) and one
`reference` node per new paper as proposals (actor `agent:<provider>:survey`), adds a message to the project
conversation and a note for each backend's next turn. It runs no experiment.

## Outline (outline/)

The paper outline: sections in paper order, each a chain of numbered items (claims) with sub-chains, parallel groups
and forks, on the map (docs/DAG.md § The paper outline); tasks hung on items; templates. Types: `web/src/panels/outline/api.ts`.

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/projects/{pid}/outline | `?lang=zh\|en` | `Outline`: `{has_outline, template, phases, project_phase, stage_mode, sections: [{id, num, title, role, phase, items: Step[], counts}], groups: [{phase, sections, state: done\|current\|later\|summary, items, holds, tasks, tasks_done, missing}], tasks, counts, pending, loose}`; a step is `{items: Item[], note}`, an item `{id, num, depth, section, parent, direction, text, status, state, derived, condition, summary_of, children, fork: {directions, chosen}, tasks, suggested, evidence, written, proposals, kids, why?, why_kind?, ended_at?}` |
| POST | /api/projects/{pid}/outline/ops | `{ops: [outline op…], lang?}` (ops: outline/ops.py docstring) | `{applied, created, last, proposal?}`; an agent's batch applies directly only when it only adds (items come in `proposed`), else it is one proposal |
| POST | /api/projects/{pid}/outline/init | `{template, lang?, structure?: {sections: [{key?, title, items, notes?}]}}` | as ops; 409 when the project has an outline |
| POST | /api/projects/{pid}/outline/structure | `{text, template, lang?, agent?: true}` | a draft `{sections, changes, by: agent\|parse}` (nothing written) |
| POST | /api/projects/{pid}/outline/extract | `{name (.pdf), content_base64}` | `{text}` of a PDF outline (422 without a text layer) |
| POST | /api/projects/{pid}/outline/save-template | `{id, name}` | the new user template |
| GET | /api/projects/{pid}/tasks | | the tasks as stored |
| POST | /api/projects/{pid}/tasks | `{type: lit\|code\|fig\|exp, title, items: [item id], status?, note?, assignee?: me\|agent\|"", links?: {node, figure, survey, branch, path}}` | the task (`t-…`); an agent's is a suggestion (`status: sugg`) |
| PATCH / DELETE | /api/projects/{pid}/tasks/{tid} | any of those fields | the task / `{ok}` |
| GET | /api/outline/templates[/{id}] | | every template (built-ins first; `builtin`, `overrides`) / one |
| PUT / DELETE | /api/outline/templates/{id} | `{name, description, phases, sections: [{key, title, role, phase, tasks}]}` | the user template / `{ok}` (a built-in cannot be removed; a user copy of one can) |

In the outline JSON a task carries what the outline shows: `status` derived from what it is linked to (an experiment
node's runs: done when one succeeded and the node is fresh, blocked when the latest failed; a survey's state) and
`locked` while its phase (the earliest of its items') is ahead of the project under the stage rules; `reason`
(run_failed, stale, survey_<state>) says why it differs from `set_status`; `nums` and `abandoned` (it serves only
abandoned items). An item's state: holds (derived, or its tasks done, or without tasks its evidence confirmed, and its
live sub-items hold), doing, todo, blocked, locked, needs_tasks, choose (a fork without a chosen direction), pending (a
summary item whose items do not hold), proposed, abandoned. `evidence` lists the nodes its edges point at and, with
`rel: "task"`, what its tasks produce. Changing the outline, tasks or templates is the researcher's (403 for agents),
except outline ops and new tasks as above.

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
| `outline/tasks.json` | outline | `{"version": 1, "tasks": [{"id": "t-…", "type": "lit\|code\|fig\|exp", "title", "items": ["claim.…"], "status": "todo\|doing\|blocked\|done\|sugg", "note", "assignee", "links": {"node", "figure", "survey", "branch", "path"}, "by", "created_at", "updated_at"}]}` |
| `outline/meta.json` | outline | `{"template": "<id>", "phases": {"idea": {"zh", "en"}, …}}` (the outline itself is on the map) |
| `dag/…` | dag | docs/DAG.md |
| `context/…` | agents | docs/ARCHITECTURE.md § Agents and context sharing |
