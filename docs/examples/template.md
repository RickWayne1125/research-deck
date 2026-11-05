# An outline template of your own

A template sets the sections a new outline starts with: what each makes the reader accept, its phase and the tasks it
usually needs. Three are built in (systems paper, ML paper, workshop paper). Make your own in **Settings › Outline
templates** (copy one, or save the current project's outline as a template), or write a YAML file into
`~/.research-deck/templates/`:

```yaml
# ~/.research-deck/templates/mlsys.yaml
id: mlsys                      # lowercase letters, digits and -
name: {en: MLSys submission, zh: MLSys 投稿}
description: {en: "Systems for ML: a measurement, a design, an end-to-end evaluation"}
phases:                        # display names only; the phase rules do not change
  idea: {en: Idea, zh: 想法}
  insight: {en: Measurement, zh: 测量}
  design: {en: System, zh: 系统}
  evaluation: {en: Evaluation, zh: 评估}
sections:
  - key: intro
    title: {en: Introduction, zh: 引言}
    role: {en: "The problem, the idea and the main results (cites the body)"}
    phase: summary             # a summary section: its items cite items of the body
  - key: characterization
    title: {en: Characterization, zh: 现象测量}
    role: {en: "Where the time goes today, measured"}
    phase: insight
    tasks: [exp, fig]
  - key: design
    title: {en: Design, zh: 设计}
    role: {en: "Each key decision and why"}
    phase: design
    tasks: [code, fig]
  - key: evaluation
    title: {en: Evaluation, zh: 评估}
    role: {en: "How much better, why, and at what cost"}
    phase: evaluation
    tasks: [exp, fig]
  - key: related
    title: {en: Related Work, zh: 相关工作}
    role: {en: "How this differs from each line of existing work"}
    phase: idea
    tasks: [lit]
```

| Field | Values |
|---|---|
| `phase` | `idea`, `insight`, `design`, `evaluation`, or `summary` |
| `tasks` | any of `lit`, `code`, `fig`, `exp` |
| texts | `{en, zh}`; one language is enough, it is used for both |

A file whose `id` matches a built-in template replaces it on this machine; deleting the file brings the built-in back.
Changing a template never changes an outline made from it: each project adds, renames and moves its own sections.
