"""Experiments and resources: experiment records with their DAG freshness, their logs, and the compute they run on.

  records.py   .research/experiments/<id>.json — list / get / create / patch, logs paging, freshness from the DAG
  logstream.py a run's raw log for the terminal view: an SSE stream that follows the file as it grows, and a download
  demo.py      labeled example resources (source "demo"), served only on request (GET /api/resources?demo=1)
  api.py       routes (docs/API.md § Experiments and resources)
"""
