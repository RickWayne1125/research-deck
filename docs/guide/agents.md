# Agents and the conversation

Each project has **one conversation** (⌘J), whichever view you ask from; what you are looking at (the item, the file
and selection, the run) is attached. It is backed by the Claude Code or the Codex CLI, signed in on your machine;
switch between them and the context is handed over. Model, effort and Fast mode sit behind one button.

## What agents can and cannot do

- Runs are headless in the project folder. Claude Code runs restricted to the project, with only Research Deck's MCP
  server; Codex runs in a read-only sandbox unless you allow writes for the conversation.
- Agents read the map, the outline and the brief, preview impacts and **propose**: new map nodes come in proposed,
  new outline items come in dashed, tasks they suggest wait for you to take them, and anything else becomes a proposal
  under **waiting for you**.
- Agents may queue runs only on the platforms and within the daily GPU-hour budget of the project's policy
  (`agent_auto_run` in `.research/dag/config.yaml`; none by default).

## The project brief

`.research/context/BRIEF.md` is regenerated as the project changes: stage, the paper outline, what needs revising or
rerunning, confirmed facts, live attempts, open proposals and gates. Any session in the project folder, including your
own terminal sessions, can read the same picture.

## The MCP server

The **research-deck MCP server** (`python -m research_deck.mcp_server --project <id>`) is passed to every run the
dashboard starts. Its tools:

| Tool | Does |
|---|---|
| `rd_brief` | the project brief |
| `rd_outline` | the outline as numbered lines with states and ids |
| `rd_outline_ops` | change the outline (adds come in proposed; anything else becomes one proposal) |
| `rd_suggest_task` | suggest a task for outline items |
| `rd_lenses`, `rd_graph`, `rd_node`, `rd_explain` | read the map and why something is not fresh |
| `rd_impact` | preview a change |
| `rd_apply`, `rd_propose`, `rd_attest` | change the map within an agent's permissions, or propose |
| `rd_plan_runs`, `rd_queue_runs`, `rd_experiments` | plan reruns, queue within the policy, list records |
| `rd_handoff_note` | leave a note for the other backend (Claude ↔ Codex) |

To use it from your own Claude Code or Codex sessions, see
[The MCP server in your own terminal](../examples/mcp-terminal.md). Nothing registers it by itself.
