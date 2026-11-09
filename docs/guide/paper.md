# The paper

**Paper** edits the project's `.tex` and `.md` files with a preview, saves as you type (with conflict detection when a
file changes on disk) and keeps snapshots you can go back to. **Figures** is its other half.

## Writing against the outline

In a research project the left pane switches between **Outline** and **Files**. The outline pane follows the cursor:
it shows the section you are in (found from its `% rd:sec` region, the heading above the cursor, or where the file's
markers point; or pick one) and, for each of its items, how far the text has got:

| State | Means |
|---|---|
| Writing | the item whose marker is nearest above the cursor |
| Written | a marker for it in this file |
| In another file | the paper covers it elsewhere |
| Not yet | nothing covers it |

Click an item to go to its paragraph in this file; an item that is not written here opens the outline file
(`notes/outline.md`, see [the outline as a Markdown file](outline.md#the-outline-as-a-markdown-file)) at its line. A
click never changes the text. To start an item's paragraph, put the cursor where it goes and click the item's **pin**:
a marker goes in at the cursor, and the paragraph under it belongs to that item.

In the outline file itself the pane is the file's contents: clicking an item or picking a section goes to its line, the
item at the cursor is highlighted, and each item shows its state on the outline instead.

```latex
% rd:sec sec.motivation
\section{Background and Motivation}

% rd:describes claim.o-motiv-lru
On-demand loading waits for experts 58% of the time ...
```

Markdown writes the markers as comments: `<!-- rd:describes claim.… -->`. After a save that changes the markers of a
`.tex` file, the paper is synced to the map, so the outline counts the item as written and the editor's gutter labels
the paragraph with the item's number.

**Draft this section** asks the agent to write the section from its items, each paragraph under its marker, using the
map's result macros instead of typed numbers. **Check against the outline** asks it which items are covered, which are
weak and what the text claims that the outline does not. Both only suggest in the conversation, unless you let the
agent write.

## Numbers that stay current

A claim on the map can bind its numbers to results (`{{name}}` in its text). `paper/generated/rdvalues.tex` defines
one macro per binding from the current results; a value whose experiment is stale is wrapped in `\rdstale{…}` and
shows in red in draft mode.

## Proofreading

**AI proofread** (++shift+cmd+k++) runs fixed passes on the selection or the whole file: typos and grammar, then your
terms (the glossary), then wording. Suggestions tint the text as each pass lands; accept with ++enter++ or reject with
++backspace++ (a rejection asks why, and the answer becomes a rule for next time). **Accept all** (++alt+cmd+k++) takes
every open suggestion as one undoable edit.

## Figures

**Paper › Figures** keeps the project's figures: draw.io in its embedded editor, matplotlib scripts with a live
preview, and OmniGraffle or DataGraph files when those apps are installed. An AI edit is shown as a diff before
anything is written. A figure can be linked to a map node, so it goes stale with the results it plots.
