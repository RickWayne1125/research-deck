# Research Deck — architecture

A local research dashboard over one or more project folders. It runs on the researcher's machine at
`http://127.0.0.1:8765` (loopback only) and drives the Claude Code and Codex CLIs headless inside each project.

A research project works from its **outline** (`panels/outline`, the home page): the paper's sections, each a chain
of numbered items that argue what the section makes the reader accept; the phases (idea, insight, design, evaluation)
group the sections, and the work is tasks hung on items (literature, code, figures, experiments) whose outputs come back
as the items' evidence. Above it sits what waits for the researcher (Today's list); beside it the inspector; its other
views are the task board, the research tree of every fork, and any item as the root (focus). The other views are
**Experiments**, **Paper** (`panels/writing`: the text, with the outline of the section at the cursor beside it, and
the figures from `panels/visualization`), **Code** (`panels/coding`) and Settings (with the outline templates); the
**Map** (`panels/dag`: the research DAG as a list or a graph) opens from the outline, the palette and node links. An
engineering project has **Today** (`panels/overview`) instead and no outline or map. The **project conversation** is on
the right (`agent/AgentDock.tsx`, ⌘J); ⌘K jumps anywhere (`components/Palette.tsx`).

```
research-deck/
  server/research_deck/        FastAPI backend (Python 3.12, .venv/)
    app.py                     app factory; mounts core routes + <pkg>/api.py:router for each panel package
    config.py util.py events.py projects.py system.py      core (do not change interfaces without updating docs/API.md)
    __main__.py offloaded.py   python -m research_deck; on macOS it first has files iCloud offloaded downloaded on read
    agents/   catalog.py sessions.py runner.py context.py api.py  + discover.py handoff.py brief.py transcript.py
              supervise.py (a CLI run's own process) queue.py (messages held until the answer in progress ends)
    dag/      the research DAG engine (docs/DAG.md)
    writing/  documents, the fixed AI proofreading passes, glossary, learned rules, snapshots
    coding/   git status/log/diff, architecture extraction (context for explanations), code review / explanation
    experiments/  experiment records + freshness from the DAG, their logs; /api/resources (the pools, or example data)
    pools/    resource pools: protocol.py (rd-pool/1), store.py (~/.research-deck/pools/<id>.yaml), sources.py (manual,
              this machine, command, http), service.py (background reads, platform views, prices, budgets), api.py,
              coder.py (the Coder CLI's sign-in that ssh to a Coder workspace needs), __main__.py
              (python -m research_deck.pools check)
    viz/      figure registry, matplotlib renderer, draw.io files, OmniGraffle/DataGraph adapters, the house style
    start/    new projects from an idea (folder, notes/idea.md, git init) and Settings → New projects
    survey/   the early survey: search arXiv / Semantic Scholar / OpenAlex, download open-access PDFs, BibTeX, draft nodes
    outline/  the paper outline: model.py (the outline as the page shows it), ops.py (outline ops → map ops), service.py,
              tasks.py (.research/outline/tasks.json), templates.py (+ templates/*.yaml), structure.py (a written outline
              → a draft of sections and items), doc.py (the outline as notes/outline.md, kept in step both ways)
    literature/  where a project keeps its papers: zotero.py (this computer's Zotero connection and a client for the
              app's local API and the zotero.org Web API), backend.py (files or a Zotero collection; references.bib
              exported from it), api.py
    docmost/  notes synced to a Docmost page: client.py (the site, the saved sign-in, page calls), login.swift (the
              sign-in window on macOS: the system's WebKit, built once with xcrun swiftc), login.py (the same window
              elsewhere: Chromium through Playwright), session.py (which window, building it, renewal), sync.py
              (binding, one-way sync, conflicts, the scan), api.py
    vault.py                   secrets Research Deck obtains itself, in ~/.research-deck/secrets/ (0700, files 0600)
    mcp_server.py              stdio MCP server exposing the dashboard to Codex/Claude (proxies the HTTP API)
  web/src/                     React 18 + TypeScript + Vite
    App.tsx state/ api/client.ts types.ts i18n/ styles/ components/   shell + shared (core)
    state/                     app.tsx (route, project, events), today.tsx (what needs a decision, the outline, the
                               task being worked on), stages.ts, views.ts
    agent/                     AgentDock (the project conversation), useAgentRun (core hook), parts
    start/                     the new-project dialog, the survey card (on the outline page), Settings → New projects
    pools/                     Settings → Resource pools, the add/edit wizard, price and cost formatting
    integrations/              Settings → Zotero and Settings → Docmost (sign-in, bound page, notes, conflict review)
    panels/<view>/index.tsx    one folder per view: outline (a research project's home), overview (Today; its list
                               shows on the outline page), dag (Map), experiments, writing (Paper), coding (Code),
                               settings; visualization holds the figures half of Paper
    demo.py                    materializes the demo project from demo/minimal into ~/.research-deck/demo/toycache on first start
  demo/minimal/                the demo's source files only (a toy synthetic project); history and DAG are built by demo.py
  scripts/pools/               example pool adapters: rd_pool_ssh.py (one machine over ssh), rd_pool_slurm.py (Slurm)
  tests/                       pytest (backend); RD_FAKE_AGENT=1 replaces the CLIs
  docs/                        ARCHITECTURE.md, API.md, DAG.md
```

## Projects, kinds and state folders

- A project is a folder plus a **state folder** inside it (`.research/` by default) holding project.yaml, the DAG,
  session bindings, writing rules and records. Two projects may share one workspace folder by giving the second its own
  state folder, `.research-<slug>` (registry entry `state`; `POST /api/projects {root, name, kind, state}`) — for
  example an engineering effort and a research project over the same repositories. Every package reaches the state
  folder through `projects.research_dir(pid)` / `project_state(pid)`; the DAG store takes it as `DagStore(root, state=…)`.
  Any `.research*` folder is state, never code (DAG fingerprints, traces and walks skip them).
- `kind` in project.yaml: `research` (the full pipeline: the outline, the map, stages and their gates) or
  `engineering` (code, documents, runs and figures of a non-research effort such as a PR; no outline or map, and Today
  shows repositories, commits, documents, runs and figures). `views: [...]` overrides the views a project shows
  (state/views.ts; in a research project `overview` and `dag` there mean the outline page).

## The outline

- One copy, on the map: sections are `section` nodes with an `order` facet (paper sync's sections from `% rd:sec`
  anchors are adopted), items are `claim` nodes; the structure (chains, parallel groups, notes, forks) lives in their
  facets (docs/DAG.md § The paper outline). The outline page never edits the map directly: `outline/ops.py` plans outline
  ops locally and writes one batch of map ops (the researcher's apply at once; an agent's adds apply as proposed nodes
  and anything else becomes one proposal).
- The outline file (`notes/outline.md`, `outline/doc.py`) is a view of that copy that can be edited: every map change
  rewrites it (`dag/service.publish` → `doc.sync`), and a save through PUT …/file is diffed against the text last
  synced and applied as outline changes through the same Plan. Tags at the line ends (`<!-- rd:item <id> -->`) carry
  the identity; the editor tags new lines before it saves, so no line is ever matched by its text.
- Tasks are a separate store (`.research/outline/tasks.json`); a task serves one or more items and links what it makes
  (a map node, a figure, a survey). Its shown state is derived from that link where it can be (an experiment node's
  runs, a survey). Templates are data: built-ins in `outline/templates/*.yaml`, the researcher's in
  `~/.research-deck/templates/`.
- Phases: a section belongs to one (or `summary`, which follows the items it cites); a task to the earliest phase of its
  items, and waits ("locked") while that phase is ahead of the project under the stage rules. The map's stage rules do
  not apply to the outline's own nodes (`dag/stages.py OUTLINE_KINDS`).
- The paper: `% rd:describes <item>` markers (HTML comments in Markdown) put a paragraph under an item; after a save that
  changes them the paper is synced to the map, so the item counts as written.

## Conventions every slice follows

- **Backend packages** expose `router = APIRouter(...)` in `<pkg>/api.py`; app.py includes it automatically.
  Project-scoped routes are `/api/projects/{pid}/...`. Use `projects.project_root(pid)`, `projects.research_dir(pid)`,
  `projects.project_config(pid)`, `util.safe_join(root, rel)` for every path coming from a request, `util.write_json`
  / `write_yaml` / `write_text_atomic` for writes, `events.hub.publish(pid, topic, payload)` after a change.
- **Agents**: never spawn a CLI directly. Build a `runner.RunSpec` with `agents.api.spec_for(pid, RunBody(...), system=..., tools=...)`
  (it resolves the conversation's binding, model, effort, fast and session) and call `runner.start(spec)` (returns a Run whose
  `id` the client streams at `/api/agent/runs/{id}/stream`) or `runner.run_blocking(spec)` inside a worker thread.
  One-shot checks (review passes) set `ephemeral=True` and usually `tools=False` (answer from the prompt alone).
  Register a deterministic answer for tests with `runner.register_fake(purpose, fn)`.
- **State on disk** lives in `<project>/.research/` as JSON/YAML/JSONL that git can diff and agents can read.
  Machine-local state (registry, tokens, the user's settings, the materialized demo project) lives in
  `~/.research-deck/` (`config.LOCAL_DIR`, `RD_LOCAL_DIR`), never in the repository.
- **Frontend**: every view is `export default function` in `panels/<view>/index.tsx`, wrapped in `.panel` with
  `<PanelHead>` and a `.panel-body`. Use `useApp()` (project, navigate, onEvent, askAgent), `useT()` for every
  visible string (register strings in `panels/<view>/i18n.ts` with keys prefixed by the view: `td.`/`ov.`, `dag.`,
  `ex.`, `wr.`, `vz.`, `cd.`, `st.`), the client in `api/client.ts` (`get/post/put/patch/del`, `p(pid, '/rest')`),
  `useAgentRun(projectId)` for AI actions, and components from `components/ui.tsx` + `components/icons.tsx`.
  Resizable side panes use `components/resize.tsx` (`useResizableWidth` + `ResizeHandle`: drag, keyboard, double-click
  reset, width in a CSS variable, saved per browser); which views a project shows comes from `state/views.ts`
  (its `kind` and `views`).
  Panel CSS goes in `panels/<view>/<view>.css`, classes prefixed (`.td-`, `.ov-`, `.dg-`, `.dl-`, `.ex-`, `.wr-`, `.vz-`,
  `.cd-`, `.st-`),
  colors only through the tokens in `styles/tokens.css` (light + dark).
- **Language**: the UI is fully bilingual (zh default, en). Paper text, code and labels inside figures are never
  translated by the UI.
- **Safety** (security review 2026-11-02; regression tests in tests/test_security.py):
  - loopback only; Host must be 127.0.0.1 / localhost / ::1 (DNS rebinding); mutating `/api` requests need an allowed
    Origin (when sent) and the `X-RD-Request: 1` header (api/client.ts sends it; a cross-origin page cannot without a
    preflight); GETs marked `Sec-Fetch-Site: cross-site` are refused; the Vite origins are allowed only with `RD_DEV=1`.
  - the human cookie (`GET /api/session`) is issued only to a same-origin page fetch; agents act as `agent:*`
    (MCP token) or `agent:unknown`; human-only DAG ops (lock, unlock, approve, gate pass, select/exclude run, record run)
    need the cookie. Agent permissions are judged against the batch as it evolves (no create-then-confirm in one batch);
    `config_edit` writes only YAML outside dot-folders, and an agent's only to existing keys bound by a live node.
  - Claude runs use `--restricted --strict-mcp-config` (no code-running tools or WebFetch, file tools confined to the
    project, the project's own settings/hooks not loaded, only the research-deck MCP); Codex runs use
    `--ignore-user-config` (no user MCP servers, notify hook or plugins), `read-only` sandbox unless the conversation is `write`,
    and always read-only for tool-less runs; session ids are validated before they reach argv.
  - git never runs repo-configured filter drivers; figure renders and native exports run in their own process group and
    are killed as a group on timeout; agent processes are TERM→KILLed on server shutdown; directory walks do not follow
    symlinks; YAML anchors/aliases are refused in Research Deck's own files; atomic writes keep file modes.
  - tailnet access is optional: with `tailnet {host, https_port, owners}` in ~/.research-deck/settings.json,
    `tailscale serve --bg --https=<port> http://127.0.0.1:8765` publishes the dashboard on the tailnet (never Funnel);
    every request arriving through Serve must carry a `Tailscale-User-Login` of an owner, the whole site included.
  - nothing submits jobs to remote machines or creates credentials; queued runs wait as experiment records until the
    researcher runs them; autocommit and agent queueing are off unless the user's or the project's DAG config turns
    them on.
  - what reaches the network, each only once the researcher sets it up: Zotero (`literature/`: the app's local API
    on 127.0.0.1, or api.zotero.org with a key from the Keychain; PDF uploads go to the address Zotero returns, https
    or the local app, without the key), the Docmost site the researcher names (`docmost/`: its cookies go only to that
    site, never on a redirect; http:// only on loopback or a private network; the sign-in window is a separate process
    that hands back nothing but that site's cookies; a page edited in Docmost is never overwritten), the resource
    pools (read through their command or HTTP source, § Resource pools; reads only), and the early survey (`survey/`),
    only when the researcher starts it
    (creating a project from an idea, or `POST /survey`; agents get 403). It sends the search queries to arXiv,
    Semantic Scholar and OpenAlex (public APIs, no keys, a generic `research-deck/<version>` User-Agent, nothing about
    the user; 429/503 are retried after a short wait). PDF links come from those answers and are untrusted: http(s)
    only, every redirect hop (at most 5) must resolve to public addresses only, the body must start with `%PDF`, at
    most 60 MB is written, through a temporary file next to the target. The agent requests of the survey are
    one-shot and tool-less (they read abstracts from the prompt); the agent never reaches the network itself.
  - secrets Research Deck obtains itself (the Zotero app's write key, the Docmost sign-in and its browser profile) live
    in `~/.research-deck/secrets/` (folder 0700, files 0600, `vault.py`), never in settings.json, the browser or logs;
    keys the researcher brings stay in the Keychain and are only named. Connecting, binding and syncing are human-only.
  - known limit: agent identities are self-asserted once the shared agent token matches (per-run tokens are a v2 item).

## Resource pools

The compute a researcher runs on is a set of **resource pools** (`server/research_deck/pools/`), owned by the machine
rather than a project: `~/.research-deck/pools/<id>.yaml`, whose id is the platform name records and the map already
use; a pool may also answer to other names (records that describe the machine), and each name belongs to one pool
(`service.owners`, `store.settle_names`). Every source (manual, this machine, a command, an HTTP endpoint) returns one **rd-pool/1** document, so the core
holds no vendor logic: Slurm, OpenStack or a lab's own tooling is an adapter outside it (`scripts/pools/` has two
examples). Reads run in the background when due; a failed read keeps the last good one with the reason. The pools are
read-only: nothing dispatches work. Prices (the definition's first, then the source's; own machines not billed,
otherwise unknown, never 0) feed the run plan, the impact preview and the new-experiment dialog through
`service.Pricer`; a pool's `budget.agent_gpu_hours_per_day` bounds what agents may queue there (`dag/queue.py`). All
writes, tests and read-nows are the researcher's; agents read pools through `GET /api/resources` and MCP `rd_pools`.
Credentials are names (`keychain:` / `env:`); a secret goes only to the command (`RD_POOL_SECRET`) or address
(`Authorization: Bearer`) that reads the pool and is never stored.

## Agents and context sharing

- Each project has **one conversation**, whichever view a request comes from (`agents/sessions.py`). It keeps one Claude
  session and one Codex session (`.research/sessions.json`, under `panels.project`) and an `active` backend; model,
  effort, fast and permission are per backend. A run's `panel` says which view asked (writing, coding, experiments,
  visualization), which only adds a line to the system note. Calls to one session are serialized.
- Switching backend writes a **handoff note** (`.research/context/handoffs/…md`): the gist of the conversation since the
  last handoff (an extract, or optionally a summary by the outgoing agent), plus the brief. The note is queued in
  `.research/context/pending/project-<provider>.md` and prepended once to the next prompt to that backend.
- `.research/context/BRIEF.md` is regenerated from the DAG (stage, confirmed facts, open questions, live attempts,
  stale items) so any session — dashboard-driven or the user's own terminal session in the same folder — can read the
  same picture.
- The **research-deck MCP server** (`python -m research_deck.mcp_server --project <pid>`) is passed to every
  dashboard-driven run (Claude `--mcp-config`, Codex `-c mcp_servers.research_deck.*`), so agents read the DAG, run an
  impact preview, record experiment results and propose node changes through the same API the UI uses. To use it from
  your own CLI sessions, `GET /api/mcp/config?project=<pid>` returns the `claude mcp add` / `codex mcp add` commands;
  nothing registers it by itself.
- **Runs outlive the page and the server.** `runner.start` hands each CLI run to a supervisor
  (`python -m research_deck.agents.supervise <folder>`, a session of its own) that starts the CLI, keeps its stdin and
  writes everything into `~/.research-deck/runs/<id>/` (`spec.json`, `out.jsonl`, `err.log`, `inbox/`, `stop`,
  `exit.json`); the server only follows the folder, so a redeploy leaves the run going and `runner.recover()` picks it
  up at the next start (the stream's ids carry the server's boot id: a page that reconnects gets `reset` and the
  replay). Claude takes its prompt as stream-json, so a **steered** message goes into `inbox/` and the supervisor writes
  it to the running turn (Claude reads it once the tool call it is in finishes; the supervisor marks the hand-over in
  `out.jsonl`, and Claude's echo says it was read). Codex cannot take one: steering stops its turn and continues the
  session with the message. **Stop** is an interrupt (Claude) or SIGINT (Codex), then signals if the CLI lingers. The
  conversation's **queue** (`agents/queue.py`) holds messages until the answer ends; a finish hook starts the next. The
  fake agent (RD_FAKE_AGENT=1) still runs in the server's process; tests drive the real supervisor with stand-in CLIs
  (`tests/fake_claude.py`, `tests/fake_codex.py`).
- Existing sessions are discovered from `~/.claude/projects/<cwd-slug>/*.jsonl` and `~/.codex/sessions/**/rollout-*.jsonl`
  (`session_meta.cwd`), so the conversation can continue a session the user already has (⋯ → Bind an existing session).
