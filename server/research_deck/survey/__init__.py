"""The early survey of a new project: existing work found, ranked, read (abstracts) and drafted onto the map.

  fetch.py     outbound HTTP (the scholarly APIs and open-access PDFs) with its safety checks
  sources.py   arXiv, Semantic Scholar and OpenAlex search, normalized and merged
  bib.py       BibTeX keys and entries
  prompts.py   the two agent requests (frame the idea; pick, classify and summarize the papers) and their parsing
  job.py       the pipeline in a worker thread, its state in .research/survey/<id>.json and the `survey` events
  fakes.py     deterministic agent answers under RD_FAKE_AGENT=1
  api.py       routes (docs/API.md § Survey)

The survey never runs experiments. Only the researcher's request starts it, and nothing else in Research Deck reaches
the network.
"""
