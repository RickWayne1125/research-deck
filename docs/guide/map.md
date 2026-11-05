# The research map

Underneath the outline, Research Deck keeps the project as a directed graph: **action nodes** (experiments and
scripted figures) whose runs are cached by fingerprints of what they read, and **belief nodes** (problems, references,
findings, gaps, solutions, decisions, designs, modules, claims, sections) whose edges record what they last saw. The
**Map** link on the outline page (or ⌘K) opens it; the full model is in [the DAG reference](../DAG.md).

## Status and freshness

- **Status** is what was decided: proposed, active, confirmed, locked, refuted, abandoned, superseded.
- **Freshness** is whether that still holds, derived on every evaluation: fresh, review, orphaned, pending, unbuilt,
  stale, broken. A code change that an experiment read makes it stale; a belief whose evidence changed goes to review.

## Changes and their impact

Every change previews its impact before it is applied: which cells must rerun (and their GPU hours), which are reused
and why, which beliefs go to review, which locks and gates it touches. Choosing an option of a decision, abandoning a
direction or editing a confirmed node all go through this preview.

## Agents propose

An agent creates nodes as *proposed* and may edit proposed or active nodes directly; anything touching confirmed or
locked nodes, and status verdicts beyond its own drafts, becomes a **proposal** that waits for you with its impact
attached. Locking, approving and passing gates are yours.

## Stage rules

The map grows one phase at a time. Under `strict` (the default), a node of a later phase cannot be created yet, an edge
to a node of an earlier phase needs that node confirmed, and nothing new may grow from a refuted, abandoned or
superseded node. `ahead` lets you draft later phases early; `free` turns the rules off. The outline's own sections and
items are exempt, so you can write the whole outline at once; its tasks follow the phases instead.

## Lenses

Four questions the map answers directly: what was **tried** (every attempt, dead ones included, with verdicts), what
is **confirmed** (and fresh), what to **revise** (review, orphaned, broken), and what to **rerun** (stale or unbuilt
cells, in waves).
