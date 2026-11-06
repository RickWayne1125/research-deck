"""Resource pools: the compute a researcher can run on (this machine, a GPU box, a lab server, a cluster, a cloud
allocation), each read through one protocol (rd-pool/1, protocol.py) from one of four sources (sources.py), with the
prices and budgets the run plan, the impact preview, the new-experiment dialog and the agents' queueing use
(service.py). Pools belong to the machine (~/.research-deck/pools/<id>.yaml, store.py), not to a project; a project may
limit which ones it uses (project.yaml `resources.pools`). Reading is read-only: nothing here starts work anywhere."""
