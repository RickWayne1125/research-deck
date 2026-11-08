"""A project's literature backend and references.bib exported from its Zotero collection.

project.yaml  literature: {backend: files | zotero, collection: <key>, collection_name: <name>, bib: papers/references.bib}

  files   (the default) the survey keeps PDFs in <papers_dir>/, appends to references.bib and writes papers/index.md
  zotero  the survey makes each kept paper an item of the project's collection (created on first use, named after the
          project) with its open-access PDF attached; the project keeps only references.bib, exported here

The export owns one block of references.bib, between "% >>> zotero" and "% <<< zotero", and rewrites only that block.
Entries outside it are the researcher's and stay as they are, except one with the same key as an exported entry,
which is commented out (not deleted) so the file never defines a key twice. Each entry's key is the item's own
citation key (Zotero's field, or "Citation Key: …" in Extra as Better BibTeX pins it), or else lastname+year+word.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import projects
from ..events import hub
from ..survey import bib
from ..util import now_iso, read_json, rel_to, safe_join, write_json, write_text_atomic
from . import zotero

BACKENDS = ("files", "zotero")
DEFAULT_BIB = "papers/references.bib"
BEGIN, END = "% >>> zotero", "% <<< zotero"
SKIP_TYPES = {"attachment", "note", "annotation"}


def config_of(pid: str) -> dict:
    cfg = projects.project_config(pid).get("literature") or {}
    cfg = cfg if isinstance(cfg, dict) else {}
    bib_rel = cfg.get("bib") if isinstance(cfg.get("bib"), str) and cfg.get("bib", "").endswith(".bib") else DEFAULT_BIB
    return {"backend": cfg.get("backend") if cfg.get("backend") in BACKENDS else "files",
            "collection": cfg.get("collection") or None, "collection_name": cfg.get("collection_name") or None,
            "bib": bib_rel}


def set_config(pid: str, **change) -> dict:
    cfg = {**config_of(pid), **change}           # a change to None removes that key
    cfg = {k: v for k, v in cfg.items() if v is not None}
    projects.patch_config(pid, {"literature": cfg})
    return config_of(pid)


def uses_zotero(pid: str) -> bool:
    return config_of(pid)["backend"] == "zotero"


def ensure_collection(pid: str, client: zotero.Client) -> str:
    """The project's collection, created (named after the project) the first time it is needed."""
    cfg = config_of(pid)
    if cfg["collection"]:
        return cfg["collection"]
    name = projects.project_config(pid).get("name") or pid
    key = client.create_collection(name)
    set_config(pid, collection=key, collection_name=name)
    return key


def bib_path(pid: str) -> Path:
    return safe_join(projects.project_root(pid), config_of(pid)["bib"])


def _state_path(pid: str) -> Path:
    return projects.research_dir(pid) / "literature.json"


def view(pid: str) -> dict:
    cfg = config_of(pid)
    st = read_json(_state_path(pid), {}) or {}
    return {**cfg, "exported": st.get("exported"), "zotero": zotero.status()}


# ---------------------------------------------------------------- references.bib

def render(items: list[dict]) -> tuple[list[str], list[str]]:
    """BibTeX entries (each after a "% zotero: <item key>" line) and their keys, oldest item first."""
    papers = [(it, zotero.citation_key(it)) for it in items if it.get("itemType") not in SKIP_TYPES]
    taken = {k for _, k in papers if k}
    entries, keys = [], []
    for it, pinned in sorted(papers, key=lambda x: (x[0].get("dateAdded") or "", x[0].get("key") or "")):
        p = zotero.paper_from_item(it)
        key = pinned or bib.bibkey(p, taken)
        entries.append(f"% zotero: {it.get('key')}\n" + bib.entry(p, key))
        keys.append(key)
    return entries, keys


ENTRY_START = re.compile(r"^@\s*(\w+)\s*\{\s*([^,\s]+)\s*,", re.M)


def merge_into(old: str, block: str, keys: list[str]) -> str:
    """The new file: the export block first, then everything outside the old block, with an outside entry whose key
    the block now defines commented out."""
    outside = re.sub(rf"(?ms)^{re.escape(BEGIN)}.*?^{re.escape(END)}[^\n]*\n?", "", old)
    wanted = set(keys)
    lines, out, i = outside.split("\n"), [], 0
    while i < len(lines):
        m = ENTRY_START.match(lines[i])
        if m and m.group(1).lower() not in ("comment", "string", "preamble") and m.group(2) in wanted:
            depth, j = 0, i
            while j < len(lines):            # the entry ends where its braces balance
                depth += lines[j].count("{") - lines[j].count("}")
                if depth <= 0 and j >= i:
                    break
                j += 1
            out.append(f"% {m.group(2)}: replaced by the entry exported from Zotero above")
            out += ["% " + line for line in lines[i:j + 1]]
            i = j + 1
            continue
        out.append(lines[i])
        i += 1
    rest = "\n".join(out).strip("\n")
    return block + ("\n" + rest + "\n" if rest else "")


def export_bib(pid: str, client: zotero.Client | None = None) -> dict:
    """Rewrite the Zotero block of references.bib from the project's collection."""
    cfg = config_of(pid)
    if cfg["backend"] != "zotero":
        raise zotero.ZoteroError("this project keeps its literature as files, not in Zotero")
    c = client or zotero.client()
    collection = ensure_collection(pid, c)
    items, version = c.items(collection)
    entries, keys = render(items or [])
    name = cfg["collection_name"] or collection
    path = bib_path(pid)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    block = (f"{BEGIN} {name}: exported by Research Deck on {now_iso()[:10]}. Edit these entries in Zotero; this block "
             f"is rewritten on every export.\n\n" + "\n".join(entries) + f"{END}\n")
    write_text_atomic(path, merge_into(old, block, keys))
    rel = rel_to(projects.project_root(pid), path)
    exported = {"at": now_iso(), "items": len(keys), "path": rel, "version": version, "collection": collection}
    st = read_json(_state_path(pid), {}) or {}
    st["exported"] = exported
    write_json(_state_path(pid), st)
    hub.publish(pid, "file", {"path": rel})
    hub.publish(pid, "literature", {"exported": exported})
    return exported
