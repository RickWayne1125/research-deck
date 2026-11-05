"""Search arXiv, Semantic Scholar and OpenAlex (public APIs, no keys) and merge what they find.

A paper is a dict: {title, authors, year, venue, abstract, doi, arxiv, url, pdf_url, citations, sources, score}.
merge() keys papers by arXiv id, then DOI, then normalized title, and scores each by where it appeared in each
result list (1 / (1 + rank)) plus a little for its citations.
"""
from __future__ import annotations

import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any

from . import fetch

ARXIV = "https://export.arxiv.org/api/query"
S2 = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX = "https://api.openalex.org/works"
SOURCES = ("arxiv", "semantic_scholar", "openalex")
LABELS = {"arxiv": "arXiv", "semantic_scholar": "Semantic Scholar", "openalex": "OpenAlex"}
# Seconds between two requests to one source: arXiv asks for three; Semantic Scholar's keyless pool is shared by
# everyone and answers 429 to bursts.
PAUSE_S = {"arxiv": 3.0, "semantic_scholar": 1.5}

_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_WS = re.compile(r"\s+")
_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$")
_last: dict[str, float] = {}
_pace_locks: dict[str, threading.Lock] = {s: threading.Lock() for s in SOURCES}


def _pace(source: str) -> None:
    """Wait until PAUSE_S[source] has passed since the last request to that source (across surveys; each source has
    its own lock, so one source's pause never holds up another)."""
    with _pace_locks[source]:
        wait = PAUSE_S.get(source, 0.0) - (time.monotonic() - _last.get(source, -1e9))
        if wait > 0:
            fetch.pause(wait)                   # ends early when the survey is cancelled
        _last[source] = time.monotonic()


def _clean(s: Any) -> str:
    return _WS.sub(" ", str(s or "")).strip()


def _year(v: Any) -> int | None:
    try:
        y = int(str(v)[:4])
        return y if 1900 < y < 2200 else None
    except (TypeError, ValueError):
        return None


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", t.lower())


STOP = {"a", "an", "the", "of", "for", "in", "on", "to", "and", "or", "with", "by", "from", "at", "as", "via", "is",
        "are", "using", "based", "toward", "towards", "into", "over", "under"}


def query_words(query: str, limit: int = 6) -> list[str]:
    """The words worth searching for: no stop words, one form of each word (expert / experts)."""
    out: list[str] = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", query):
        k = w.lower().rstrip("s") if len(w) > 3 else w.lower()
        if w.lower() in STOP or any((x.lower().rstrip("s") if len(x) > 3 else x.lower()) == k for x in out):
            continue
        out.append(w)
    return out[:limit]


def arxiv(query: str, limit: int) -> list[dict]:
    """All the query's words first (precise); when that finds fewer than three papers, any of them (arXiv ranks
    those by relevance)."""
    words = query_words(query)
    if not words:
        return []
    root = None
    for op in (" AND ", " OR "):
        _pace("arxiv")
        text = fetch.get_text(ARXIV, {"search_query": op.join(f"all:{w}" for w in words), "start": 0,
                                      "max_results": limit, "sortBy": "relevance"})
        root = ET.fromstring(text)
        if len(root.findall("a:entry", _NS)) >= min(3, limit) or len(words) == 1:
            break
    out = []
    for e in root.findall("a:entry", _NS):
        abs_url = _clean(e.findtext("a:id", "", _NS))
        m = _ARXIV_ID.search(abs_url)
        aid = m.group(1) if m else None
        pdf = next((ln.get("href") for ln in e.findall("a:link", _NS) if ln.get("title") == "pdf"), None)
        out.append({
            "title": _clean(e.findtext("a:title", "", _NS)),
            "authors": [_clean(a.findtext("a:name", "", _NS)) for a in e.findall("a:author", _NS)],
            "year": _year(e.findtext("a:published", "", _NS)),
            "venue": _clean(e.findtext("arxiv:journal_ref", "", _NS)) or "arXiv",
            "abstract": _clean(e.findtext("a:summary", "", _NS)),
            "doi": _clean(e.findtext("arxiv:doi", "", _NS)) or None,
            "arxiv": aid,
            "url": abs_url.replace("http://", "https://"),
            "pdf_url": (pdf or (f"https://arxiv.org/pdf/{aid}" if aid else None) or "").replace("http://", "https://") or None,
            "citations": None,
        })
    return out


def semantic_scholar(query: str, limit: int) -> list[dict]:
    _pace("semantic_scholar")
    data = fetch.get_json(S2, {"query": query, "limit": limit,
                               "fields": "title,abstract,year,venue,authors,externalIds,openAccessPdf,citationCount,url"})
    out = []
    for p in (data or {}).get("data") or []:
        ext = p.get("externalIds") or {}
        aid = ext.get("ArXiv")
        out.append({
            "title": _clean(p.get("title")),
            "authors": [_clean(a.get("name")) for a in p.get("authors") or []],
            "year": _year(p.get("year")),
            "venue": _clean(p.get("venue")) or None,
            "abstract": _clean(p.get("abstract")),
            "doi": ext.get("DOI"),
            "arxiv": aid,
            "url": p.get("url") or None,
            "pdf_url": ((p.get("openAccessPdf") or {}).get("url")) or (f"https://arxiv.org/pdf/{aid}" if aid else None),
            "citations": p.get("citationCount"),
        })
    return out


def _abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    words: list[tuple[int, str]] = []
    for w, positions in inverted.items():
        words += [(i, w) for i in positions]
    return " ".join(w for _, w in sorted(words))


def openalex(query: str, limit: int) -> list[dict]:
    data = fetch.get_json(OPENALEX, {
        "search": query, "per-page": limit,
        "select": "id,title,publication_year,primary_location,best_oa_location,open_access,authorships,cited_by_count,doi,abstract_inverted_index",
    })
    out = []
    for w in (data or {}).get("results") or []:
        doi = str(w.get("doi") or "").replace("https://doi.org/", "") or None
        aid = doi[len("10.48550/arxiv."):] if doi and doi.lower().startswith("10.48550/arxiv.") else None
        best = w.get("best_oa_location") or {}
        oa = (w.get("open_access") or {}).get("oa_url")
        pdf = best.get("pdf_url") or (oa if oa and oa.lower().endswith(".pdf") else None)
        source = ((w.get("primary_location") or {}).get("source") or {})
        out.append({
            "title": _clean(w.get("title")),
            "authors": [_clean((a.get("author") or {}).get("display_name")) for a in w.get("authorships") or []],
            "year": _year(w.get("publication_year")),
            "venue": _clean(source.get("display_name")) or None,
            "abstract": _abstract(w.get("abstract_inverted_index")),
            "doi": doi,
            "arxiv": aid,
            "url": (f"https://doi.org/{doi}" if doi else w.get("id")) or None,
            "pdf_url": pdf,
            "citations": w.get("cited_by_count"),
        })
    return out


SEARCH = {"arxiv": arxiv, "semantic_scholar": semantic_scholar, "openalex": openalex}


def key(p: dict) -> str:
    if p.get("arxiv"):
        return "arxiv:" + p["arxiv"]
    if p.get("doi"):
        return "doi:" + str(p["doi"]).lower()
    return "t:" + norm_title(p.get("title") or "")


def merge(results: list[tuple[str, int, dict]]) -> list[dict]:
    """(source, rank in its list, paper) → unique papers with their sources and a score, best first."""
    by: dict[str, dict] = {}
    titles: dict[str, str] = {}
    for source, rank, p in results:
        if not p.get("title"):
            continue
        t = "t:" + norm_title(p["title"])
        k = titles.get(t) or key(p)              # the same title from another source is the same paper
        cur = by.get(k)
        if cur is None:
            cur = {**p, "sources": [], "score": 0.0}
            by[k] = cur
        else:
            for f in ("abstract", "doi", "arxiv", "url", "venue", "year"):
                if not cur.get(f) and p.get(f):
                    cur[f] = p[f]
            if p.get("pdf_url") and (not cur.get("pdf_url") or "arxiv.org" in str(p["pdf_url"])):
                cur["pdf_url"] = p["pdf_url"]
            if p.get("authors") and not cur.get("authors"):
                cur["authors"] = p["authors"]
            cur["citations"] = max(cur.get("citations") or 0, p.get("citations") or 0) or None
        titles.setdefault(t, k)
        if source not in cur["sources"]:
            cur["sources"].append(source)
        cur["score"] += 1.0 / (1 + rank)
    papers = list(by.values())
    for p in papers:
        p["score"] = round(p["score"] + 0.1 * math.log10(1 + (p.get("citations") or 0)), 4)
    return sorted(papers, key=lambda p: (-p["score"], p.get("title") or ""))
