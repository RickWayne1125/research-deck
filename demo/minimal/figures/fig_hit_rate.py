"""Figure 1: hit rate of each eviction policy at 64 blocks (figures/data/hit_rate.csv, copied from experiments/results/)."""
import csv
from pathlib import Path

import _rdstyle as rd

with open(Path(__file__).parent / "data" / "hit_rate.csv", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
policies = [r["policy"] for r in rows]
rates = [float(r["hit_rate"]) for r in rows]

fig, ax = rd.figure()
ax.barh([{"lru": "LRU", "lfu": "LFU"}.get(p, p) for p in policies], rates, color=[rd.ACCENT if p == "lookahead" else rd.MUTED for p in policies])
for y, v in enumerate(rates):
    ax.text(v + 0.01, y, f"{v:.2f}", va="center")
ax.invert_yaxis()
ax.set_xlim(0, 1)
ax.set_xlabel("hit rate at 64 blocks")
rd.save(fig)
