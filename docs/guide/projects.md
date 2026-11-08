# Projects

A project is a folder on your machine plus a **state folder** inside it, `.research/` by default, where Research Deck
keeps everything it records: `project.yaml`, the outline and the map, tasks, experiment records, writing rules and the
conversation's bindings. It never writes anywhere else in the project.

## Two kinds

| Kind | For | Home page |
|---|---|---|
| **research** | a paper or a study: the full pipeline with the outline, the map, phases and their gates | the outline |
| **engineering** | a non-research effort such as a PR or an integration: code, documents, runs and figures | Today: repositories, commits, documents, runs and figures |

Choose the kind when you add a project; `kind` in `.research/project.yaml` changes it later. `views: [...]` there limits
which views a project shows.

## Add an existing folder

Project menu (top left) → **Add an existing folder…**: the folder, a name and the kind. Two projects can share one
folder by giving the second its own state folder, `.research-<slug>`; for example, an engineering effort and a
research project over the same repositories.

## Start from an idea

Project menu → **New from an idea…**: paste the idea, or upload a `.md`, `.txt` or `.pdf`. Research Deck

1. creates the project folder (`~/Research/<name>` by default; change it in **Settings › New projects**), runs
   `git init` and keeps the idea in `notes/idea.md`;
2. runs an **early survey** if you leave it on: it searches arXiv, Semantic Scholar and OpenAlex, keeps the most
   relevant papers, downloads the open-access PDFs into `papers/` (paywalled ones get a link and BibTeX), writes
   `papers/references.bib` and `notes/survey.md`, and drafts the problem and reference nodes for you to review.
   With [Zotero](zotero-docmost.md) as the literature backend, the papers and their PDFs go into the project's Zotero
   collection instead, and the project keeps only `references.bib`, exported from it.

The survey reaches the network only when you start it; it sends nothing about you and uses no keys. Apart from it,
only what you set up yourself does: the resource pools you add, and [Zotero and Docmost](zotero-docmost.md).

## Phases

A research project moves through four phases: **idea → motivation & insight → system design → evaluation**. The
outline groups its sections by phase, and the current phase's group says what leaving it takes (every item of its
sections holds) next to the map's gates. Under the stage rules (the default, `strict`), tasks of a later phase wait
until the project gets there; `ahead` lets you draft them early, and `free` turns the rules off.

## Where things live

| Path | What |
|---|---|
| `.research/project.yaml` | name, kind, stage, where the paper, code, figures and experiment records are |
| `.research/dag/` | the map: nodes, runs, proposals, its log and `config.yaml` (gates, autocommit, stage rules, agent policy) |
| `.research/outline/` | `tasks.json` and `meta.json` (the template and the phase names); the outline itself is on the map |
| `.research/experiments/` | experiment records and their logs |
| `.research/context/` | `BRIEF.md` (the project brief agents read), transcripts, handoff notes |
| `~/.research-deck/` | the project registry, `settings.json`, the agents' token, your outline templates, the demo |
