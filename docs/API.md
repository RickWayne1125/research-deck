# Research Deck — HTTP API

All JSON. Project-scoped routes start with `/api/projects/{pid}`. Types are those of `web/src/types.ts`.
Every mutating request carries `X-RD-Request: 1` (see ARCHITECTURE.md § Safety). Slice-specific extras that the
implementations added (extra fields, convenience routes) are documented in each package's api.py docstrings.
The research DAG's routes are in docs/DAG.md (§ HTTP API).

## Core (implemented: server/research_deck/{projects,system,events}.py)

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/system/health | | `Health` |
| GET | /api/events?project=pid | SSE; events named by topic (`dag`, `outline` (the outline or its tasks changed), `file`, `sessions`, `agent` (a run ended; or a conversation answer started: `{run_id, status: "running", purpose: "chat", queued?}`), `queue` (`{panel, items}`: the conversation's queue changed), `experiments`, `figures`, `writing`, `project`, `survey` (the survey's state)); `hello` on every connection and `ping` at least every 15 s (a page reopens a stream quiet for longer) | `ProjectEvent` |
| GET | /api/projects | | `ProjectSummary[]` |
| POST | /api/projects | `{root, name?, kind?: research\|engineering, state?: ".research-<slug>"}` | `ProjectSummary` (creates the state folder; `state` lets a second project share the folder) |
| DELETE | /api/projects/{pid} | | `{ok}` (forgets it; files untouched) |
| GET | /api/projects/{pid} | | `ProjectDetail` |
| PATCH | /api/projects/{pid}/config | partial `ProjectConfig` | `ProjectConfig` |
| GET | /api/projects/{pid}/tree | `?dir=&depth=` | `TreeNode[]` |
| GET | /api/projects/{pid}/file | `?path=` | `FileContent` |
| GET | /api/projects/{pid}/raw | `?path=` | the file itself, for links and pictures in documents: PDFs and PNG/JPEG/GIF/WebP/SVG pictures open in the browser, other UTF-8 text as plain text, anything else downloads. Never served as a page of the dashboard: nosniff, and a `sandbox` CSP on everything but PDFs |
| PUT | /api/projects/{pid}/file | `{path, content, base_sha?}` | `{path, sha, mtime, content?, outline?}`; 409 `{message, sha}` if the file changed on disk. For the outline file (§ Outline file) `outline: {applied, proposal?, error?, warnings}` says what the save did to the outline, and `content` is the file as it is now when that differs from what was sent (numbers brought up to date) |

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
| GET | /api/projects/{pid}/outline | `?lang=zh\|en` | `Outline`: `{has_outline, template, phases, project_phase, stage_mode, file, sections: [{id, num, title, role, phase, items: Step[], counts}], groups: [{phase, sections, state: done\|current\|later\|summary, items, holds, tasks, tasks_done, missing}], tasks, counts, pending, loose}`; a step is `{items: Item[], note}`, an item `{id, num, depth, section, parent, direction, text, status, state, derived, condition, summary_of, children, fork: {directions, chosen}, tasks, suggested, evidence, written, proposals, kids, why?, why_kind?, ended_at?}` |
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

### Outline file

The outline as a Markdown file in the project (`outline/doc.py`): `notes/outline.md`, or project.yaml `outline.file`
(when a file of the researcher's own already has the default name, the next free one, `notes/outline-2.md`). The GET
above adds `file: {path, error, warnings}` once it exists. A `## ` heading is a section (`<!-- rd:sec <id> -->` at its
end), `>` lines under it its role, every other line an item (`- **<num>** [‖ ]<text>[ (derived)] <!-- rd:item <id> -->`,
indented under its parent; `‖` joins the step before, `> ‖ …` names the group below it, `- ↳ Direction <k>: …` is a
fork's direction).

- **Map → file:** after every change to the map, and when the outline or the documents are read, the file is written
  again from the outline (the text before its first section is kept). Edits made to it outside Research Deck are
  imported first, as `agent:unknown`: one proposal; the file shows the map until the proposal is approved.
- **File → map:** a PUT of the file is a three-way diff, from the text last synced (`.research/outline/file.json`) to
  the saved text, applied to the map as it is now. It covers text and `(derived)`, new items and sections (a line
  without a tag gets one), removed items and sections (abandoned, except what moved elsewhere), moves, indents,
  parallel groups and their notes, the order of sections, and the revival of an abandoned item whose tag comes back.
  Forks are made, chosen and given up through outline ops. The researcher's save applies at once; an agent's becomes
  one proposal and the file is written again from the map. When a save cannot be applied, the text stays as saved,
  `error` says why and the file is not rewritten until a save applies.
- Docmost receives notes without Research Deck's `<!-- rd:… -->` tags, and the outline file cannot take Docmost's
  version (it follows the outline).

## Agents (agents/)

A project has one conversation; `{panel}` in the routes below is `project` (the older view names `writing`, `coding`,
`experiments`, `visualization` are accepted and mean the same conversation).

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/agents/catalog | | `AgentCatalog` |
| GET | /api/projects/{pid}/sessions | | `SessionsDoc` |
| PUT | /api/projects/{pid}/sessions/{panel} | `{provider?, model?, effort?, fast?, permission?, session_id?, new_session?, title?}` | `PanelBinding` |
| POST | /api/projects/{pid}/agent/run | `RunRequest` | `RunStarted` (`steerable`: a message can reach the running turn); a `chat` run while the conversation's answer is in progress: 409 `{message, run_id}` (steer or queue instead) |
| GET | /api/agent/runs?project= | | run summaries (`steerable` too) |
| GET | /api/agent/runs/{run_id} | | summary + `text` |
| GET | /api/agent/runs/{run_id}/stream | SSE, event name `agent`, `id` = `<server>:<index>`; `Last-Event-ID` (or `?last=` for a page that reopens the stream itself) resumes after it; an id from another server process (a restart) gets `{"type": "reset"}` and the run from the start; `ping` at least every 15 s | `AgentEvent` … `done` |
| POST | /api/agent/runs/{run_id}/cancel | | `{ok}` (stops the answer; the next message, or Resume, continues the same session) |
| POST | /api/agent/runs/{run_id}/steer | `{text}` (researcher only) | `{run_id, mode: steered\|restart, id}`: Claude reads it once the tool call it is in finishes (its `steer` and `user` events carry `id`); Codex cannot, so its turn stops and the session continues with the message (`restart`). 409 if the run has ended |
| GET | /api/projects/{pid}/agent/queue | `?panel=` | `{items: QueueItem[]}` (`{id, text, context, at, now}`) |
| POST | /api/projects/{pid}/agent/queue | `{text, context?, panel?}` (researcher only) | `{items, started}`: held until the answer in progress ends; with none in progress it starts at once (`started`: `RunStarted`) |
| DELETE | /api/projects/{pid}/agent/queue/{item_id} | `?panel=` (researcher only) | `{items}` |
| POST | /api/projects/{pid}/agent/queue/{item_id}/send | `?panel=` (researcher only) | `{items, mode: steered\|restart\|started, id?, run_id, started}`: steered into the answer in progress, or started |
| GET | /api/projects/{pid}/sessions/discover | `?provider=claude|codex` | `DiscoveredSession[]` (existing sessions whose cwd is the project root) |
| GET | /api/projects/{pid}/transcript/{panel} | `?limit=` | `TranscriptEntry[]` (dashboard record; plus imported tail of a bound session when available) |
| POST | /api/projects/{pid}/handoff | `{panel, to, smart?: bool}` | `{file, summary, pending: true}`; switches the conversation's active backend to `to` |
| GET | /api/projects/{pid}/brief | | `{markdown, generated_at}` (regenerates `.research/context/BRIEF.md`) |
| GET | /api/mcp/config | `?project=` | `{claude: {...}, codex: {...}, commands: {claude: "claude mcp add …", codex: "codex mcp add …"}}` (to register the MCP server in your own CLI; never registers by itself) |

A conversation answer outlives the page and the server. Each CLI run has a supervisor of its own
(`agents/supervise.py`) that keeps the CLI's stdin and writes its output to `~/.research-deck/runs/<id>/`; the server
follows that folder, so a reload reconnects to the stream and a restart (a redeploy) picks every unfinished run up
again (`runner.recover()`). One answer runs at a time per conversation: while it runs, a message is steered into it or
queued (`~/.research-deck/queues/`). When an answer finishes, the first queued message starts; when it was stopped,
the queue waits for the researcher (except a message steered into a Codex run, which stops to take it). A steered
message Claude never read (handed over too late, or dropped by Stop) goes back to the front of the queue. The
transcript records a steered message (`steer: true`) once Claude has read it, and a cut-short answer with `status`
(`cancelled` | `error`).

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
| GET | /api/resources | `?project=&demo=` | `Resources`: every [resource pool](#resource-pools-pools) as a platform (`source: "pools"`), with `selection` and `unmatched` for the project; `?demo=1` = the labeled example data (`source: "demo"`) |

## Resource pools (pools/)

Pools belong to the machine (`~/.research-deck/pools/<id>.yaml`). Every write, test and read-now is the researcher's
(403 for agents): a pool's source runs a command or calls an address with the researcher's credentials.

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/pools | `?project=` | `{pools: [{def, platform}], selection, unmatched, broken: [{file, error}], clashes: [{name, pool, owner}], dir, adapters, python}`; `clashes`: a name two pool files list, kept by `owner` |
| GET | /api/pools/{id} | `?project=` | `{def, platform, yaml}` (the file as written) |
| PUT | /api/pools/{id} | a definition (the YAML's fields; `id` must match) | `{def, platform}`; starts a first read. 409 when its id or one of its `names` is already another pool's |
| DELETE | /api/pools/{id} | | `{trashed}` (the file moved to `pools/.trash/`) |
| POST | /api/pools/{id}/refresh | `?project=` | `{def, platform}` after reading now |
| POST | /api/pools/test | a definition | `{ok, duration_s, error?, needs?, warnings, doc, raw, platform}`: one read, nothing saved. `needs: {kind: "coder-login", host}` when it failed because the Coder CLI is signed out (the pool's view carries the same `needs`) |
| POST | /api/pools/parse | `{text}` (a pool file) | `{def, exists}` (validated, not saved) |
| GET | /api/pools/coder/status | `?host=` (a Coder workspace host) | `{installed, cli, folder, managed, host, url, signed_in, user, error}`: the Coder CLI's sign-in in the folder ssh to that host reads (`ssh -G`), else the CLI's default folder (researcher only) |
| POST | /api/pools/coder/login | `{url, token, host?}` (researcher only) | the status after `coder --global-config <folder> login <url>`; the token goes to the CLI's prompt on stdin and is kept only by the CLI. 400 when Coder refuses the token |
| PUT | /api/projects/{pid}/pools | `{pools: [ids] \| null}` | `{selection}` (project.yaml `resources.pools`; null = all) |

A platform name (`target.platform`, `spec.platform`) belongs to the pool whose id or one of whose `names` it is,
ignoring case and extra spaces; `unmatched` lists the project's names no pool answers to. A platform from a pool
carries, besides the `Platform` fields, `pool`: `{state: ok | stale | failed | reading, here, names, source, read_at, age_s, error, warnings, capabilities, credential: {ref, expires_at, days_left, state}, billed,
prices: [{item, match, amount, unit, from}], rate: {state: known | free | unknown | varies, amount, unit, item},
budget: {agent_gpu_hours_per_day, agent_used_today, month}}`; each node carries `flavor` and `price`. The document a
source returns is [rd-pool/1](examples/pool-adapter.md#the-document).

`POST /dag/runs/plan` prices each cell (`cost: {state, amount, unit, rate, item, pool, why}`) and returns `cost`
(per unit, never summed across units), `unpriced: {cells, gpu_h}` and `limits` (where the plan would go past a pool's
quota or monthly budget); `usd` stays the USD total. The impact preview's summary carries `cost.rerun` and
`unpriced.rerun` the same way.

## Literature (literature/)

Where a project keeps its papers: files in the project (the default) or a Zotero collection. This computer reaches
Zotero through the desktop app's local API (`http://127.0.0.1:23119/api/`, Zotero 10+ for writes) or the zotero.org Web
API; settings.json `zotero: {mode: local | web, library: users/<id> | groups/<id>, credential: keychain:<item> | env:<VAR>}`.
The app's write key is kept in `~/.research-deck/secrets/zotero.json`; a zotero.org key stays in the Keychain. Every
change and every request that reaches Zotero is the researcher's (403 for agents); no route returns a key.

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/settings/zotero | | `{mode, library, credential, local_key, local_remember, connect: {state, message}, check: {ok, at, message?, user?, write?, version?} \| null}` |
| PATCH | /api/settings/zotero | any of `{mode, library, credential}` (null or "" removes the last two) | the status; 400 on a malformed value |
| POST | /api/settings/zotero/connect | | the status. The app: shows its Allow / Always Allow / Deny dialog (`connect.state` waiting → done \| error); zotero.org: checks the key |
| POST | /api/settings/zotero/check | | the status with a fresh `check` |
| DELETE | /api/settings/zotero/key | | the status (the app's key forgotten) |
| GET | /api/zotero/collections | | `{collections: [{key, name, parent}]}` |
| GET | /api/projects/{pid}/literature | | `{backend: files \| zotero, collection, collection_name, bib, exported: {at, items, path, version, collection} \| null, zotero}` |
| PUT | /api/projects/{pid}/literature | `{backend, collection?, create?}` | the project's literature (project.yaml `literature`); `create`: a new collection named after the project |
| POST | /api/projects/{pid}/literature/export | | `{at, items, path, version, collection}`: references.bib's Zotero block rewritten |

With Zotero, the survey (§ Survey) makes each kept paper an item of the project's collection (its citation key in
Extra as `Citation Key: …`) with its open-access PDF as a stored attachment, writes no PDF or `index.md` into the
project, and exports references.bib; a survey refuses to start (409) while Zotero does not answer. The export owns
the block between `% >>> zotero` and `% <<< zotero` and keeps every entry outside it, commenting out (not deleting) one
whose key the block now defines. A paper carries `zotero` (the item) and `zotero_pdf` (the attachment); notes link
them as `zotero://select/…` and `zotero://open-pdf/…`.

## Docmost (docmost/)

This computer signs in to one Docmost site (settings.json `docmost: {url}`); a project binds one page and its notes
(`notes/**/*.md`) become child pages of it, one way. Signing in opens a window on the computer running Research Deck:
on macOS a Mac window with the system's WebKit (`docmost/login.swift`, built once with `xcrun swiftc`), elsewhere
Chromium through Playwright (`pip install 'research-deck[docmost]'`). The site's cookies are kept in
`~/.research-deck/secrets/docmost/session.json` and sent only to that site, never on a redirect. Reading the state is
open; signing in, binding, syncing and resolving are the researcher's (403 for agents).

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | /api/settings/docmost | | `{url, signed_in, user, at, login: {state, message, code?, phase?: build \| window}, install: {state, message}, playwright, helper: native \| playwright \| null}` |
| PATCH | /api/settings/docmost | `{url}` (null forgets it) | the status; another site forgets the sign-in. http:// only on this computer or a private network |
| POST | /api/settings/docmost/login | | the status; `login.state` waiting → done \| error (code 2 no sign-in window here, 3 window closed, 4 timed out, 5 no Playwright browser, 6 site unreachable, 7 the native window could not be built) |
| POST | /api/settings/docmost/logout | | the status (the sign-in, and the window's own cookies and profile, deleted) |
| POST | /api/settings/docmost/browser | | the status; `install.state` running → done \| error (Playwright's Chromium, once) |
| GET | /api/projects/{pid}/docmost | | `{binding: {page, slug_id, space, space_slug, title, url} \| null, site, signed_in, running, last: {at, pushed, conflicts, errors}, notes: [{path, title, state, at, error, url}]}` |
| PUT | /api/projects/{pid}/docmost | `{link}` (a page link, its slug id or its id) | binds the page (project.yaml `docmost`) and syncs once; 401 `{message, sign_in}` when Docmost wants a new sign-in |
| DELETE | /api/projects/{pid}/docmost | | unbound (the pages stay in Docmost) |
| POST | /api/projects/{pid}/docmost/sync | | syncs now; the project's status |
| GET | /api/projects/{pid}/docmost/conflict | `?path=` | `{path, title, at, url, diff: [{kind: + \| - \| " " \| @, text}], remote, note}`: what changed in Docmost since the last push |
| POST | /api/projects/{pid}/docmost/resolve | `{path, action: push \| take \| recreate \| forget}` | the project's status |

A note's state: `synced`, `pending` (changed since its last push), `conflict` (the page was edited in Docmost since
the last push: nothing is pushed until `push` replaces the page with the note or `take` writes Docmost's version into
the note), `missing` (the page was deleted in Docmost: `recreate` or `forget`), `removed` (the note was deleted; its
page stays), `error`. A note's first `# ` heading is the page's title and is left out of the page's text. While a
sign-in is saved, every bound project is synced each minute; a note saved in the last 10 seconds waits a round.
Sync state: `.research/docmost.json`.

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
