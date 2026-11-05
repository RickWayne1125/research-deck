"""Starting a project from an idea: the machine-local settings for new projects and POST /api/projects/new.

  settings.py  ~/.research-deck/settings.json `new_projects` (default folder per OS, git init, survey defaults) and the
               `dag_defaults.stages.mode` that Settings edits; only those keys are ever written
  create.py    the new project: its folder, git init, the idea saved under notes/, .research/, the registry entry,
               then the survey (research_deck.survey) when asked
  api.py       routes (docs/API.md § Projects)
"""
