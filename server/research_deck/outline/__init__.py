"""The paper outline: sections and their items (on the map, as section and claim nodes), the tasks the items need
(literature reviews, coding, figures, experiments), branches (forks) for the directions tried, and templates.

  templates.py   built-in and user templates (which sections, their roles and phases, the usual tasks)
  model.py       the outline as the page shows it: numbers, states, tasks, evidence, writing, phases, what is pending
  ops.py         outline operations → map operations (one batch)
  service.py     applying ops, creating an outline from a template, saving one as a template
  tasks.py       the task store (.research/outline/tasks.json) and how a task's status follows what it is linked to
  structure.py   from a pasted outline to sections and items (the text's own structure, tidied by an agent)
  api.py         routes (docs/API.md § Outline)
"""
