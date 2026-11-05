# A tour of the demo

The demo project, **toycache (demo)**, is a made-up study: a small GPU block cache whose LRU eviction misses most
requests, and a *lookahead* policy that reads the serving queue to evict the block used farthest ahead. Every number in
it is invented. Its history has four commits: the LRU baseline, an LFU attempt that lost, the lookahead policy, and a
later code change that makes the lookahead result stale. Open <http://127.0.0.1:8765> and pick it from the project
menu at the top left.

## 1. The outline

The home page is the paper's outline, grouped by phase. The idea, motivation and design phases have passed; the
project is in **evaluation**.

- Each section (§1 Introduction … §7 Conclusion) is a chain of numbered items. A pill's color says whether the item
  *holds* (green), is in progress, blocked, or still needs a task.
- Under an item, its **tasks** (Literature, Code, Figure, Experiment) show their state, and its **evidence** shows the
  map nodes behind it, colored by freshness.
- **3.1** is a fork: *Which eviction policy makes use of the queue?* Direction 1 (lookahead) is chosen; the abandoned
  LFU direction is folded into one line. It is "in progress" because the lookahead experiment went stale after the
  last code change.
- **5.2** (*The gain holds for lookahead windows from 4 to 32*) has an experiment task that has not run yet.

Click an item to see it in the inspector on the right: its state, tasks, evidence, the text that covers it, and what
you can do to it. Click 3.1 to compare its directions side by side.

!!! tip "Writing items like an outliner"
    Click a selected item's text (or press ++enter++) to edit it. ++enter++ saves it and starts the next item,
    ++alt+enter++ a parallel one, ++tab++ puts it under the item above, ++shift+tab++ moves it up a level, ++cmd+period++
    folds. The [outline guide](../guide/outline.md) has the rest.

## 2. What waits for you

The strip above the outline counts the tasks by state and what needs a decision. Open **waiting for you**: here it is
the two experiments that must run or rerun. Forks without a chosen direction, items an agent drafted, blocked tasks
and agent proposals show up here too.

## 3. Tasks and the research tree

Switch the view at the top from **Outline** to **Tasks**: every task by state, each naming the items it serves. Its
button opens where the work happens. Then **Research tree**: every fork of the outline with each direction's tasks,
results and, for the LFU attempt, why it was given up.

## 4. Experiments

Click **Open experiment** on the lookahead task, or open **Experiments** in the navigation. The runs list shows
the baseline runs as fresh and the lookahead run as stale: the commit after it changed `toycache/lookahead.py`, which
the run read. The bar at the top says what to rerun; the run plan groups it into waves with an estimate. While you
work on a task, the bar above the page names it and the items it serves.

## 5. The paper

Open **Paper** and `paper/main.md`. The left pane switches between **Outline** and **Files**. With the cursor in
*4 Evaluation*, the outline pane lists §5's items and how far the text has got with each. Click an item that is not
written yet to put a marker for it at the cursor; the paragraph below it now belongs to that item.

## 6. The map and the conversation

The **Map** link on the outline page opens the research DAG: problems, findings, decisions, designs, experiments,
figures and claims, with their freshness. Press ++cmd+j++ for the project conversation and ask, for example, *"What
does the stale lookahead run invalidate?"*. Without a Claude or Codex CLI, start Research Deck with `RD_FAKE_AGENT=1`
to get canned answers.

## Next

- [Projects](../guide/projects.md): add your own project, or start one from an idea.
- [From an idea to a paper](../examples/idea-to-paper.md): the same steps on a project of your own.
