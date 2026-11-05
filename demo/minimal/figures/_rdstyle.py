"""The demo's figure style: one small font, gray bars, one accent color, SVG output.

    import _rdstyle as rd
    fig, ax = rd.figure()
    rd.save(fig)          # $RD_FIG_OUT when Research Deck renders the figure, else <script>.svg
"""
import os
import sys
from pathlib import Path

import matplotlib

if not os.environ.get("MPLBACKEND"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, MUTED, ACCENT = "#202124", "#9aa0a6", "#c0392b"

plt.rcParams.update({
    "font.size": 9,
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": INK,
    "ytick.color": INK,
    "svg.fonttype": "none",
})


def figure(width: float = 3.4, height: float = 1.5):
    return plt.subplots(figsize=(width, height), constrained_layout=True)


def save(fig) -> None:
    out = os.environ.get("RD_FIG_OUT") or str(Path(sys.argv[0]).with_suffix(".svg"))
    fig.savefig(out)
