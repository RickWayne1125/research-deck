"""Where a project keeps its literature: files in the project (papers/, the default) or a Zotero collection.

  zotero.py   this computer's Zotero connection (settings.json "zotero", its key) and a small client for Zotero's
              HTTP API: the desktop app's local API or the zotero.org Web API (collections, items, PDF attachments)
  backend.py  a project's backend (project.yaml "literature"), what the survey asks of it, and references.bib exported
              from the project's collection
  api.py      routes (docs/API.md § Literature)

With Zotero, the survey stores each kept paper as an item in the project's collection and its open-access PDF as an
attachment; the project keeps only references.bib, so a LaTeX paper still builds.
"""
