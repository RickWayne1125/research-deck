# From an idea to a paper

This walks through a project of your own, from a paragraph of an idea to a written section. The idea here is made up.

## 1. Start the project

Project menu → **New from an idea…**, and paste:

> Small GPU block caches in LLM serving evict with LRU and miss most requests when the hot set moves. The serving queue
> already knows which blocks the next requests need. Can the cache read the queue and evict the block used farthest
> ahead?

Keep the early survey on. Research Deck creates the folder, keeps the idea in `notes/idea.md` and searches for related
work. While it runs, the outline page shows its progress; when it is done, `notes/survey.md` and
`papers/references.bib` are in the project, and the drafted problem and reference nodes wait for you under **waiting
for you**.

## 2. Write the outline

The new project's outline page offers three ways in. Choose **Paste or upload** and write what you have; any
style works (numbers, Markdown lists, LaTeX `\section`s):

```text
1 Introduction
- Small block caches miss most requests when the hot set moves
- The serving queue already knows the next requests
- Lookahead eviction reads the queue and beats LRU at 64 blocks
2 Background and Motivation
- LRU hits only 0.41 of the requests at 64 blocks
- The queue knows the next requests; LRU ignores them
3 Design
- Evict the block whose next queued use is farthest away
  - Ties go to LRU order
4 Evaluation
- Hit rate against LRU at 64 blocks
- The gain holds for windows from 4 to 32
```

**Tidy into chains** turns it into numbered sections and items (the agent keeps your words and only restructures; *Without
the agent* uses the text's own structure). Check the result on the right (which template section each one landed in,
what was split or grouped) and **Confirm and create the outline**.

## 3. Hang the work on the items

Select 2.1 (*LRU hits only 0.41*) and **Assign a task**: an *Experiment*, "LRU baseline at 64 blocks". Open the task:
**New experiment node (S2)** creates the map node it will produce, at the stage of the item's phase. Give the design
items *Code* tasks and the evaluation items *Experiment* and *Figure* tasks. The template added an empty §6 Related
Work: write its items and give them *Literature* tasks; **Run a survey** on such a task searches for its topic.

The strip above the outline now counts the tasks by state; each item's pill turns green when its tasks are done.

## 4. Branch when a design question has several answers

Select 3.1 and **Fork…** it into directions, say *lookahead* and *LFU*. Each direction gets its own tasks. When the LFU
results come in below LRU, **abandon** that direction with the reason (*LFU hits 0.37, below LRU*) and **choose**
lookahead. The research tree keeps the LFU attempt with its reason; the outline shows only the chosen path.

## 5. Write the section

Open **Paper**, create `paper/sections/motivation.tex`, and switch the left pane to **Outline**. Put the cursor where
the section's text starts and click 2.1: a marker with the item's id goes in, and you write the paragraph under it.

```latex
% rd:sec sec.motivation
\section{Background and Motivation}

% rd:describes claim.i5c2e9a07
At 64 blocks, LRU hits only 0.41 of the requests ...
```

Save. The paper is synced to the map, 2.1 shows as written, and the editor's gutter labels the paragraph *2.1*. When
the section is drafted, **Check against the outline** asks the agent which items are covered and which are weak.

## 6. Move on

When every item of the current phase's sections holds, **Leave this phase** on the outline shows what is left on the
map's gates and moves the project to the next phase.
