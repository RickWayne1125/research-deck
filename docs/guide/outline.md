# The outline

The outline is a research project's home page and its main line: the paper's sections, each a chain of items that
argue what the section makes the reader accept. Writing, experiments, design and literature all hang under its items.

## Sections, items and numbers

- A **section** (§1 Introduction, §2 Background and Motivation, …) has a role (*what it makes the reader accept*) and a
  phase. A **summary** section, such as the introduction or the conclusion, has no phase: its items cite items of the
  body and hold when those do.
- **Items** are numbered like paper sections: 2.1, 2.2 …; an item's sub-items are 3.1.1, 3.1.2 …, at any depth. Each
  sub-chain argues for the item above it. Sub-chains are folded until you open them.
- **Parallel items** are framed together: together they lead to the next item (*two measurements*, *three
  comparisons*). The frame's note says what the group is.
- An item marked **derived** is argued, not measured, and needs no task.

## Writing it

Start a new project's outline in one of three ways: paste or upload what you have (`.md`, `.tex`, `.txt`, `.pdf`), start
from a template, or let the agent draft one from the idea, the survey and the map. A pasted outline is **tidied into
chains** first (your words; only the structure changes: an item that says two things is split, parallel items are
grouped, sections are matched to the template) and nothing is written until you confirm.

Then edit it in place, like an outliner:

| Key | Does |
|---|---|
| click a selected item, or ++enter++ | edit its text |
| ++enter++ while editing | save, start the next item |
| ++alt+enter++ | save, start a parallel item |
| ++tab++ / ++shift+tab++ | put it under the item above / move it up a level |
| ++alt+up++ / ++alt+down++ | move it |
| ++up++ / ++down++ | select the item above / below |
| ++cmd+period++ | fold or unfold its sub-items |
| ++esc++ | cancel the edit, or let go of the selection |

Select a section to rename it, change its role or phase, move it, add a section after it or remove it. Removing an
item marks it abandoned on the map; nothing is deleted.

## Tasks

Each item can get tasks of four kinds: **Literature**, **Code**, **Figure** and **Experiment**. One task can serve
several items. A task is *not started*, *in progress*, *blocked* or *done*, and a task of a later phase *waits* for it.
Where it can, its state follows what it is linked to:

- an experiment task linked to a map node is done once the node has a succeeded run and is fresh, in progress when its
  results are stale, blocked when its latest run failed;
- a literature task linked to a survey follows the survey.

What a task produces (its linked node) shows as the item's evidence. An item **holds** when it is derived, or its
tasks are done, or (without tasks) its evidence is confirmed, and its sub-items hold. See
[Tasks and experiments](experiments.md) for doing the work.

## Phases and leaving one

The outline groups its sections by phase. A passed phase folds away unless something in it no longer holds; the
current one says what leaving it takes. **Leave this phase** opens a check: the phase's items that do not hold yet,
then the map's gates. Passing it saves a snapshot and moves the project on.

## Forks and the research tree

When a design question has several answers, or several problems are worth validating, **fork** the item into
directions. Each direction has its own sub-items, tasks and evidence. **Choose** one and the others are marked
abandoned (with the reason *another direction is better*), or **abandon** a direction with your own reason. The
overview folds abandoned directions into one line; the **Research tree** view shows every fork with all its
directions, what each produced and why each was given up.

## What waits for you

The strip above the outline counts the tasks by state and lists what needs you: forks to choose, items an agent added
(they stay dashed until you accept them), blocked tasks, tasks an agent suggested, agent proposals, drafts to review,
runs to start, failed runs. ++j++ / ++k++ move between them, ++y++ takes an item's first action and ++n++ its second.

## Templates

New outlines start from a template: **Systems paper**, **ML paper** and **Workshop paper** are built in. **Settings ›
Outline templates** edits them (a changed built-in is saved as your copy) or saves the current outline as a new one.
Changing a template never changes an outline made from it. See
[An outline template of your own](../examples/template.md).

## Evaluating the story

**Evaluate the story** sends the whole outline, with each item's state, to the conversation and asks whether each
chain holds together, which items lack evidence and what the weakest link is. The agent only suggests.
