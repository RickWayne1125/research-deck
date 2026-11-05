"""The writing panel's backend (docs/API.md § Writing).

  docs.py       the project's documents: .tex and .md under the paper dir, docs/ and notes/ (titles, word counts)
  store.py      .research/writing/: glossary.yaml, rules.json (learned rules), dismissed.json, reviews/<id>.json
  findings.py   the finding contract: parse an agent's answer, locate each quote in the text, validate, fingerprint
  prompts.py    the five passes of the fixed revision pipeline: instructions, efforts, output format, context blocks
  context.py    what the consistency and logic passes read besides the text: DAG claims and experiment metrics
  review.py     runs the passes one after another in a worker thread and records the ReviewResult
  versions.py   snapshots (.research/writing/snapshots/) and the file's git history
  fakes.py      deterministic answers for every pass under RD_FAKE_AGENT=1 (tests, the offline demo)
  api.py        the routes
"""
