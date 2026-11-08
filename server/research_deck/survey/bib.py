"""BibTeX keys (lastname + year + first title word, e.g. xue2024moe) and entries."""
from __future__ import annotations

import re
import unicodedata

STOP = {"a", "an", "the", "on", "of", "for", "in", "to", "and", "with", "towards", "toward", "via", "is", "are", "by"}
CONFERENCE = re.compile(r"conference|symposium|proceedings|workshop|\b(isca|osdi|sosp|nsdi|mlsys|neurips|icml|iclr|asplos|"
                        r"usenix|atc|eurosys|sigcomm|micro|hpca|sc|ppopp|kdd|acl|emnlp|naacl|cvpr|iccv|eccv|aaai|ijcai)\b", re.I)


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def bibkey(p: dict, taken: set[str]) -> str:
    first = (p.get("authors") or [""])[0]
    last = re.sub(r"[^a-z]", "", _ascii(first.split()[-1] if first.split() else "")) or "anon"
    words = [w for w in re.findall(r"[a-z0-9]+", _ascii(p.get("title") or "")) if w not in STOP]
    base = f"{last}{p.get('year') or 'nd'}{words[0] if words else ''}"[:40]
    k, n = base, 0
    while k in taken:
        n += 1
        k = base + chr(ord("a") + n)
    taken.add(k)
    return k


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")


# Item types that are not papers (from a Zotero library): the BibTeX entry type and the field the venue goes to.
TYPES = {"book": ("book", "publisher"), "bookSection": ("incollection", "booktitle"), "thesis": ("phdthesis", "school"),
         "report": ("techreport", "institution")}


def entry(p: dict, k: str) -> str:
    venue = p.get("venue") or ""
    special = TYPES.get(p.get("type") or "")
    if special:
        kind, extra = special[0], ([(special[1], venue)] if venue else [])
    elif p.get("arxiv") and venue in ("", "arXiv"):
        kind, extra = "misc", [("eprint", p["arxiv"]), ("archivePrefix", "arXiv")]
    elif CONFERENCE.search(venue):
        kind, extra = "inproceedings", [("booktitle", venue)]
    elif venue:
        kind, extra = "article", [("journal", venue)]
    else:
        kind, extra = "misc", []
    fields = [("title", "{" + _esc(p.get("title") or "") + "}"), ("author", _esc(" and ".join(a for a in p.get("authors") or [] if a)))]
    if p.get("year"):
        fields.append(("year", str(p["year"])))
    fields += [(k2, _esc(v)) for k2, v in extra]
    if p.get("doi"):
        fields.append(("doi", _esc(p["doi"])))
    if p.get("url"):
        fields.append(("url", _esc(p["url"])))
    body = ",\n".join(f"  {k2} = {{{v}}}" for k2, v in fields if v)
    return f"@{kind}{{{k},\n{body}\n}}\n"
