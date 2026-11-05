"""Figure style tokens: one built-in house style for every figure kind, which a project can override in
<project>/.research/style.json: {active_palette, font, series, roles}.

The house style: Helvetica with Chinese fallbacks, ONE final font size for every label (9 pt), flat semantic fills for
diagrams (process / data / emphasis / neutral), an 8 px grid and 1.2 px strokes, and three two-ink palettes (a
structure ink plus one focal accent). The same tokens style draw.io templates, matplotlib previews, the native-app
adapters and the agents' figure prompts (summary()).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..util import read_json

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# ---------------------------------------------------------------- the house style

FALLBACK_DRAWIO = {
    "typography": {"font_family": "Helvetica", "font_size_px": 12, "final_font_pt": 9,
                   "cjk_fallbacks": ["PingFang SC", "Noto Sans CJK SC"]},
    "palette": {
        "ink": {"fill": "#20242B", "stroke": "#30343B"},
        "line": {"stroke": "#59616C"},
        "process": {"fill": "#E6EEF7", "stroke": "#6D8FAC"},
        "data": {"fill": "#E7F1ED", "stroke": "#7FA591"},
        "emphasis": {"fill": "#F6E6E2", "stroke": "#B67C73"},
        "neutral": {"fill": "#F4F5F6", "stroke": "#A3A8AE"},
        "canvas": {"fill": "#FFFFFF"},
    },
    "geometry": {"grid_px": 8, "stroke_width": 1.2},
}

FALLBACK_OMNIGRAFFLE = {
    "typography": {"family": "Helvetica", "bold_family": "Helvetica-Bold", "size": 16,
                   "cjk_fallbacks": ["PingFang SC", "Noto Sans CJK SC"]},
    "layout": {"grid": 4},
    "card": {"corner_radius_range": [5, 6], "border": False, "shadow": False},
    "lines": {"main_width_range": [1.5, 2], "secondary_width_range": [0.7, 1],
              "axis_width_range": [0.6, 0.8], "curve_width_range": [0.9, 1.2]},
    "default_palette_id": "palette_charcoal_signal_red",
    "background": "#FFFFFF",
}

# The inks and the three two-ink palettes.
FALLBACK_CATALOG = {
    "inks": [
        {"id": "ink_charcoal", "name": "Charcoal", "hex": "#30343A"},
        {"id": "ink_signal_red", "name": "Signal Red", "hex": "#C83232"},
        {"id": "ink_cobalt", "name": "Cobalt", "hex": "#2148B8"},
        {"id": "ink_terracotta", "name": "Terracotta Orange", "hex": "#C65F38"},
        {"id": "ink_mint_green", "name": "Mint Green", "hex": "#5EB783"},
        {"id": "ink_mint_charcoal", "name": "Warm Charcoal", "hex": "#302D2E"},
    ],
    "palettes": [
        {"id": "palette_charcoal_signal_red", "mode": "chromatic + black", "ink_ids": ["ink_charcoal", "ink_signal_red"]},
        {"id": "palette_cobalt_terracotta", "mode": "complementary duotone", "ink_ids": ["ink_cobalt", "ink_terracotta"]},
        {"id": "palette_mint_charcoal", "mode": "chromatic + black", "ink_ids": ["ink_mint_green", "ink_mint_charcoal"]},
    ],
}

FALLBACK_DATAGRAPH = {"series": ["#C83232", "#30343A", "#787B7F", "#CBCCCE"], "font_pt": 16}

# The palettes as (id, structure ink, accent ink, text ink); their roles are derived below (tints over white,
# WCAG contrast for the accent's foreground).
WORKFLOW_PALETTES = [
    ("palette_charcoal_signal_red", "ink_charcoal", "ink_signal_red", "ink_charcoal"),
    ("palette_cobalt_terracotta", "ink_cobalt", "ink_terracotta", "ink_charcoal"),
    ("palette_mint_charcoal", "ink_mint_charcoal", "ink_mint_green", "ink_mint_charcoal"),
]
PALETTE_TEXT = {
    "palette_charcoal_signal_red": {
        "label": "Charcoal + Signal Red", "label_zh": "炭黑 + 信号红",
        "note": "Restrained default; strong focal contrast", "note_zh": "克制的默认方案，重点路径对比鲜明",
    },
    "palette_cobalt_terracotta": {
        "label": "Cobalt + Terracotta", "label_zh": "钴蓝 + 陶土橙",
        "note": "Two distinct chromatic identities", "note_zh": "两种色相区分明确，浅色节点底保证文字清晰",
    },
    "palette_mint_charcoal": {
        "label": "Mint + Charcoal", "label_zh": "薄荷绿 + 炭黑",
        "note": "Softer; small mint marks need dark text/keylines", "note_zh": "更柔和；小面积薄荷绿需要深色文字和边线",
    },
}
# The exact auxiliary grays of the charcoal / red palette.
CHARCOAL_AUX = {"muted": "#787B7F", "light": "#CBCCCE"}


# ---------------------------------------------------------------- color helpers

def _rgb(value: str) -> list[int]:
    return [int(value[i:i + 2], 16) for i in (1, 3, 5)]


def tint(ink: str, density: float, background: str = "#FFFFFF") -> str:
    """Precompose ink over a flat background: result = density * ink + (1 - density) * background."""
    return "#" + "".join(f"{round(density * a + (1 - density) * b):02X}" for a, b in zip(_rgb(ink), _rgb(background)))


def contrast(a: str, b: str) -> float:
    def lum(color: str) -> float:
        ch = [v / 255 for v in _rgb(color)]
        lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return sum(v * w for v, w in zip(lin, (0.2126, 0.7152, 0.0722)))
    x, y = sorted((lum(a), lum(b)))
    return round((y + 0.05) / (x + 0.05), 2)


# ---------------------------------------------------------------- the tokens

def _hex(value: Any, default: str) -> str:
    return value.upper() if isinstance(value, str) and HEX.match(value) else default


def _palettes() -> list[dict]:
    inks = {i["id"]: i["hex"] for i in FALLBACK_CATALOG["inks"]}
    modes = {p["id"]: p["mode"] for p in FALLBACK_CATALOG["palettes"]}
    out = []
    for pid, structure_id, accent_id, text_id in WORKFLOW_PALETTES:
        structure, accent, text = inks[structure_id], inks[accent_id], inks[text_id]
        foreground = "#FFFFFF" if contrast("#FFFFFF", accent) >= 4.5 else text
        accent_fill = accent if contrast(foreground, accent) >= 4.5 else tint(accent, 0.11)
        aux = CHARCOAL_AUX if pid == "palette_charcoal_signal_red" else {
            "muted": tint(structure, 0.65), "light": tint(structure, 0.24)}
        roles = {
            "text": text, "structure": structure, "accent": accent, "muted": aux["muted"], "light": aux["light"],
            "surface": tint(structure, 0.06), "accent_surface": tint(accent, 0.11), "accent_fill": accent_fill,
            "accent_text": foreground, "accent_keyline": structure if contrast(accent, "#FFFFFF") < 3 else accent,
            "background": "#FFFFFF",
        }
        text_meta = PALETTE_TEXT[pid]
        out.append({
            "id": pid, "label": text_meta["label"], "label_zh": text_meta["label_zh"],
            "note": text_meta["note"], "note_zh": text_meta["note_zh"],
            "source": "built-in", "mode": modes.get(pid),
            "inks": {"structure": structure_id, "accent": accent_id, "text": text_id},
            "colors": [{"role": r, "hex": roles[r]} for r in
                       ("text", "structure", "accent", "muted", "light", "surface", "accent_surface")],
            "roles": roles,
            "series": [accent, structure, aux["muted"], aux["light"]],
            "recommended": pid == "palette_charcoal_signal_red",
        })
    return out


def builtin_tokens() -> dict:
    """The house style alone (no project override)."""
    typo = FALLBACK_DRAWIO["typography"]
    pal = FALLBACK_DRAWIO["palette"]
    geometry = FALLBACK_DRAWIO["geometry"]
    final_pt = typo["final_font_pt"]
    omni = FALLBACK_OMNIGRAFFLE
    palettes = _palettes()
    datagraph = FALLBACK_DATAGRAPH

    def role(entry: Any) -> dict:
        entry = entry if isinstance(entry, dict) else {}
        return {"fill": _hex(entry.get("fill"), "none"), "stroke": _hex(entry.get("stroke"), "none")}
    roles = {name: role(pal.get(name)) for name in ("process", "data", "emphasis", "neutral", "ink", "line", "canvas")}
    omni_typo = omni["typography"]
    lines = omni["lines"]
    default_palette = omni["default_palette_id"]

    return {
        "font": {"family": typo.get("font_family") or "Helvetica",
                 "fallback": ["Helvetica Neue", "Arial"],
                 "cjk": list(typo.get("cjk_fallbacks") or FALLBACK_DRAWIO["typography"]["cjk_fallbacks"]),
                 "size_pt": float(final_pt)},
        "palettes": palettes,
        "default_palette": default_palette,
        "drawio_roles": roles,
        "datagraph_series": datagraph["series"],
        "geometry": {"grid_px": geometry.get("grid_px", 8), "stroke_width": geometry.get("stroke_width", 1.2)},
        "tools": {
            "drawio": {"font_px": typo.get("font_size_px", 12), "font_pt": float(final_pt),
                       "grid_px": geometry.get("grid_px", 8), "stroke_width": geometry.get("stroke_width", 1.2)},
            "omnigraffle": {"font_pt": omni_typo.get("size", 16), "bold_family": omni_typo.get("bold_family"),
                            "grid_pt": (omni.get("layout") or {}).get("grid", 4),
                            "corner_radius": (omni.get("card") or {}).get("corner_radius_range", [5, 6]),
                            "main_line": lines.get("main_width_range"), "secondary_line": lines.get("secondary_width_range")},
            "datagraph": {"font_pt": datagraph["font_pt"], "series": datagraph["series"], "error_bars": "native"},
            "matplotlib": {"font_pt": float(final_pt), "width_in": 3.35, "height_in": 2.2,
                           "line_width": lines.get("curve_width_range", [0.9, 1.2])[-1],
                           "axis_width": lines.get("axis_width_range", [0.6, 0.8])[0]},
        },
    }


# ---------------------------------------------------------------- the project's view

def override_path(research_dir: Path) -> Path:
    return research_dir / "style.json"


def load_override(research_dir: Path) -> dict:
    data = read_json(override_path(research_dir), None)
    return data if isinstance(data, dict) else {}


def tokens(research_dir: Path | None = None) -> dict:
    """StyleTokens (web/src/types.ts) plus extra detail: the house style merged with the project's .research/style.json."""
    base = builtin_tokens()
    override = load_override(research_dir) if research_dir else {}
    palettes = base["palettes"]
    ids = {p["id"] for p in palettes}
    active = override.get("active_palette") if override.get("active_palette") in ids else base["default_palette"]
    palette = next(p for p in palettes if p["id"] == active)

    font = {**base["font"]}
    for key in ("family", "size_pt", "cjk", "fallback"):
        if (override.get("font") or {}).get(key) not in (None, "", []):
            font[key] = override["font"][key]
    font["size_pt"] = float(font["size_pt"])

    # Diagram roles: the drawio semantic roles, plus the active palette's structure and focal accent.
    pr = palette["roles"]
    roles = {**base["drawio_roles"],
             "structure": {"fill": pr["surface"], "stroke": pr["structure"]},
             "accent": {"fill": pr["accent_surface"], "stroke": pr["accent"]}}
    for name, value in (override.get("roles") or {}).items():
        if isinstance(value, dict):
            roles[name] = {"fill": _hex(value.get("fill"), roles.get(name, {}).get("fill", "none")),
                           "stroke": _hex(value.get("stroke"), roles.get(name, {}).get("stroke", "none"))}

    series = [s.upper() for s in override.get("series") or [] if isinstance(s, str) and HEX.match(s)] or palette["series"]
    return {
        "font": font,
        "palettes": palettes,
        "active_palette": active,
        "roles": roles,
        "series": series,
        "geometry": base["geometry"],
        "tools": base["tools"],
        "datagraph_series": base["datagraph_series"],
        "override": override,
    }


def summary(tok: dict) -> str:
    """The style in a few lines, for agent prompts."""
    font = tok["font"]
    palette = next(p for p in tok["palettes"] if p["id"] == tok["active_palette"])
    pr = palette["roles"]
    roles = ", ".join(f"{k} {v['fill']}/{v['stroke']}" for k, v in tok["roles"].items()
                      if k in ("process", "data", "emphasis", "neutral", "accent"))
    return "\n".join([
        f"- Font: {font['family']} (fallback {', '.join(font.get('fallback') or [])}; Chinese: {', '.join(font['cjk'])}). "
        f"ONE uniform size for every label, tick, legend and annotation: {font['size_pt']:g} pt at final size "
        f"(draw.io fontSize={tok['tools']['drawio']['font_px']}). Hierarchy through weight and position, never size.",
        f"- Palette {palette['id']} ({palette['label']}): text {pr['text']}, structure {pr['structure']}, "
        f"accent {pr['accent']} (only the focal path / the proposed method), muted {pr['muted']}, light {pr['light']}, "
        f"pale surfaces {pr['surface']} / {pr['accent_surface']}.",
        f"- Data series colors in order: {', '.join(tok['series'])} (first = the proposed method).",
        f"- Diagram roles (fill/stroke): {roles}; connectors {tok['roles'].get('line', {}).get('stroke', '#59616C')}.",
        f"- Geometry: {tok['geometry']['grid_px']} px grid, stroke {tok['geometry']['stroke_width']}, flat fills, "
        "no shadows or gradients, white background, mildly rounded blocks, short noun-phrase labels.",
        "- Data plots: native error bars, thin spines, light or no grid, data stays in the data files (never invent values).",
    ])
