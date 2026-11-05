"""rd-exec (docs/DAG.md §4.3): run a job under the tracer and write rd_run.json. Stdlib only.

    python -m research_deck.dag.rd_exec --spec spec.json --cell '{"rate": 8}' -- python bench/e2e.py
"""
