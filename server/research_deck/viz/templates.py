"""Starting points for new figures, built from the project's style tokens.

  drawio      a native, uncompressed draw.io file: input -> process -> store on the 8 px grid, Helvetica, the semantic roles
  matplotlib  figures/<id>.py that imports the generated helper figures/_rdstyle.py and reads figures/data/<id>.csv
  _rdstyle.py the style helper itself (fonts, sizes, series colors, thin spines, white background, save to RD_FIG_OUT)
"""
from __future__ import annotations

import json
from xml.sax.saxutils import quoteattr

HELPER_NAME = "_rdstyle.py"
# The first line of a generated helper. A helper without it was edited by hand and is never regenerated.
HELPER_MARKER = "# research-deck: generated style helper"


def _drawio_style(**kv: object) -> str:
    return ";".join(f"{k}={v}" for k, v in kv.items()) + ";"


def drawio_template(tok: dict, title: str, diagram_id: str) -> str:
    """input -> process -> store, as native cells a person can keep editing in draw.io."""
    roles, font = tok["roles"], tok["font"]
    px = tok["tools"]["drawio"]["font_px"]
    stroke = tok["geometry"]["stroke_width"]
    ink = roles.get("ink", {}).get("fill", "#20242B")
    line = roles.get("line", {}).get("stroke", "#59616C")
    family = font["family"]

    def node(role: str, **extra: object) -> str:
        r = roles.get(role) or roles["neutral"]
        return _drawio_style(rounded=1, arcSize=12, whiteSpace="wrap", html=1, fillColor=r["fill"], strokeColor=r["stroke"],
                             strokeWidth=stroke, fontFamily=family, fontSize=px, fontColor=ink, **extra)

    def edge(color: str) -> str:
        return _drawio_style(edgeStyle="orthogonalEdgeStyle", rounded=0, html=1, endArrow="block", endFill=1, endSize=6,
                             strokeColor=color, strokeWidth=stroke, fontFamily=family, fontSize=px, fontColor=ink)

    # 8 px grid: three 112 x 48 blocks, 56 px apart; the store is a cylinder.
    cells = [
        ("in", "Input", node("data"), (40, 40, 112, 48)),
        ("proc", "Process", node("process"), (208, 40, 112, 48)),
        ("store", "Store", node("neutral", shape="cylinder3", boundedLbl=1, backgroundOutline=1, size=8), (376, 32, 112, 64)),
    ]
    xml = [
        '<mxfile host="Research Deck" type="device">',
        f'  <diagram id={quoteattr(diagram_id)} name={quoteattr(title or "Page-1")}>',
        '    <mxGraphModel dx="800" dy="400" grid="1" gridSize="8" guides="1" tooltips="1" connect="1" arrows="1" '
        'fold="1" page="0" pageScale="1" pageWidth="827" pageHeight="1169" math="0" shadow="0" background="#FFFFFF">',
        '      <root>',
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]
    for cid, label, style, (x, y, w, h) in cells:
        xml.append(f'        <mxCell id="{cid}" value="{label}" style="{style}" vertex="1" parent="1">')
        xml.append(f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />')
        xml.append('        </mxCell>')
    # The focal edge carries the active palette's accent; everything else stays neutral.
    accent = roles.get("accent", {}).get("stroke", "#C83232")
    for eid, src, dst, color in (("e1", "in", "proc", line), ("e2", "proc", "store", accent)):
        xml.append(f'        <mxCell id="{eid}" style="{edge(color)}" edge="1" parent="1" source="{src}" target="{dst}">')
        xml.append('          <mxGeometry relative="1" as="geometry" />')
        xml.append('        </mxCell>')
    xml += ['      </root>', '    </mxGraphModel>', '  </diagram>', '</mxfile>', '']
    return "\n".join(xml)


def sample_csv() -> str:
    """Tiny sample data (made up, clearly labeled as such in the script) so a new plot renders immediately."""
    rows = ["batch,method,throughput,std"]
    values = {"Ours": [118, 226, 431, 802, 1430], "Baseline A": [104, 190, 342, 590, 960], "Baseline B": [96, 171, 298, 501, 790]}
    stds = {"Ours": [4, 7, 12, 21, 35], "Baseline A": [5, 8, 13, 20, 31], "Baseline B": [4, 6, 11, 17, 26]}
    for method, ys in values.items():
        for i, (b, y) in enumerate(zip((1, 2, 4, 8, 16), ys)):
            rows.append(f"{b},{method},{y},{stds[method][i]}")
    return "\n".join(rows) + "\n"


def matplotlib_template(title: str, data_rel: str) -> str:
    """data_rel is relative to the script's folder (the data/ folder next to it)."""
    return f'''"""{title}

Rendered by Research Deck on every edit (the preview is the SVG at $RD_FIG_OUT). Run it yourself with
`python <this file>` to write the paper PDF next to it. Style: figures/_rdstyle.py (the project's figure style).
The sample data in {data_rel} is made up; replace it with your results.
"""
import csv
from collections import defaultdict
from pathlib import Path

import _rdstyle as rd

DATA = Path(__file__).resolve().parent / {json.dumps(data_rel)}

series = defaultdict(list)
with DATA.open(newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        series[row["method"]].append((float(row["batch"]), float(row["throughput"]), float(row["std"])))

fig, ax = rd.figure()
for i, (method, points) in enumerate(series.items()):
    x, y, err = zip(*sorted(points))
    ax.errorbar(x, y, yerr=err, label=method, **rd.error_style(i))

ax.set_xscale("log", base=2)
ax.set_xticks([1, 2, 4, 8, 16], labels=["1", "2", "4", "8", "16"])
ax.set_xlabel("Batch size")
ax.set_ylabel("Throughput (tok/s)")
rd.legend(ax)
rd.save(fig)
'''


def helper_source(tok: dict) -> str:
    """figures/_rdstyle.py: the project's figure style for matplotlib, generated from the style tokens."""
    font = tok["font"]
    mpl = tok["tools"]["matplotlib"]
    families = [font["family"], *font.get("fallback", []), *font.get("cjk", []), "DejaVu Sans"]
    families = list(dict.fromkeys(families))   # keep order, drop duplicates
    palette = next(p for p in tok["palettes"] if p["id"] == tok["active_palette"])
    pr = palette["roles"]
    return f'''{HELPER_MARKER} (palette {tok["active_palette"]}). Change the style in the
# Visualization panel or .research/style.json; delete the line above to keep hand edits from being regenerated.
"""Research Deck figure style for matplotlib: one font and size everywhere, the project's series colors, thin spines,
white background, vector output. Usage:

    import _rdstyle as rd
    fig, ax = rd.figure()                 # final paper size (inches)
    ax.plot(x, y, **rd.series_style(0))   # series 0 = the proposed method (accent color)
    rd.legend(ax)
    rd.save(fig)                          # $RD_FIG_OUT when the dashboard renders, else <script>.pdf
"""
import logging
import os
import sys
from pathlib import Path

import matplotlib

if not os.environ.get("MPLBACKEND"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

FONT_FAMILY = {json.dumps(families)}
FONT_SIZE = {font["size_pt"]:g}            # pt at final size, for every text element
SERIES = {json.dumps(tok["series"])}
MARKERS = ["o", "s", "^", "D", "v", "P"]
INK = {json.dumps(pr["text"])}
MUTED = {json.dumps(pr["muted"])}
LIGHT = {json.dumps(pr["light"])}
ACCENT = {json.dumps(pr["accent"])}
LINE_WIDTH = {mpl["line_width"]:g}
AXIS_WIDTH = {mpl["axis_width"]:g}
SIZE = ({mpl["width_in"]:g}, {mpl["height_in"]:g})   # one column of a two-column paper

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # missing fallbacks are expected

plt.rcParams.update({{
    "font.family": "sans-serif",
    "font.sans-serif": FONT_FAMILY,
    "font.size": FONT_SIZE,
    "axes.titlesize": FONT_SIZE,
    "axes.labelsize": FONT_SIZE,
    "xtick.labelsize": FONT_SIZE,
    "ytick.labelsize": FONT_SIZE,
    "legend.fontsize": FONT_SIZE,
    "legend.title_fontsize": FONT_SIZE,
    "figure.titlesize": FONT_SIZE,
    "axes.prop_cycle": matplotlib.cycler(color=SERIES),
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "axes.linewidth": AXIS_WIDTH,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "grid.color": LIGHT,
    "grid.linewidth": AXIS_WIDTH,
    "xtick.color": INK,
    "ytick.color": INK,
    "xtick.major.width": AXIS_WIDTH,
    "ytick.major.width": AXIS_WIDTH,
    "xtick.major.size": 3,
    "ytick.major.size": 3,
    "xtick.minor.visible": False,
    "ytick.minor.visible": False,
    "lines.linewidth": LINE_WIDTH,
    "lines.markersize": 4,
    "errorbar.capsize": 2,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "svg.fonttype": "none",       # keep text as text in SVG
    "pdf.fonttype": 42,           # embed TrueType in PDF (editable, accepted by publishers)
    "ps.fonttype": 42,
}})


def figure(width=None, height=None, **kw):
    """A figure at final size (inches) with one axes; pass nrows/ncols for small multiples."""
    return plt.subplots(figsize=(width or SIZE[0], height or SIZE[1]), **kw)


def series_style(i, hollow=False):
    """Color, marker and line width of series i (0 = the proposed method)."""
    color = SERIES[i % len(SERIES)]
    style = {{"color": color, "marker": MARKERS[i % len(MARKERS)], "linewidth": LINE_WIDTH, "markeredgewidth": AXIS_WIDTH}}
    if hollow:
        style["markerfacecolor"] = "white"
    return style


def error_style(i, hollow=False):
    """series_style plus native error-bar widths, for ax.errorbar(x, y, yerr=..., **rd.error_style(i))."""
    return {{**series_style(i, hollow), "elinewidth": AXIS_WIDTH, "capthick": AXIS_WIDTH}}


def legend(ax, outside=False, **kw):
    """A compact legend without a frame; outside=True puts it above the axes."""
    if outside:
        kw.setdefault("loc", "lower left")
        kw.setdefault("bbox_to_anchor", (0, 1.02, 1, 0.2))
        kw.setdefault("mode", "expand")
        kw.setdefault("ncol", max(1, len(ax.get_legend_handles_labels()[0])))
        kw.setdefault("borderaxespad", 0)
    kw.setdefault("handlelength", 1.6)
    return ax.legend(**kw)


def save(fig, path=None):
    """Save to $RD_FIG_OUT (the dashboard's preview), else to path, else next to the script as <name>.pdf."""
    out = os.environ.get("RD_FIG_OUT") or path or str(Path(sys.argv[0] or "figure").with_suffix(".pdf"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    return out
'''
