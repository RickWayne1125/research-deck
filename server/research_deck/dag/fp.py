"""Content fingerprints (docs/DAG.md §4.2). Stdlib only: rd_exec imports this module on the host that ran a job.

A fingerprint depends on content, never on commit SHAs or paths:
  s:  canonical JSON / prose / text value          p:  token-normalized Python (comments and layout never count)
  j:  JSON file, whitespace-normalized              g:  any other file (git blob sha prefix)
  d:  the names in a directory                       t:  an output table (cell -> anchor fp)
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import tokenize
import unicodedata
from collections.abc import Iterable
from typing import Any

FP_ALGO = "rd/1"
MISSING = "∅"


class _Unknown:
    """A predicted fingerprint (impact previews): never equal to anything, itself included."""
    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return False

    def __ne__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 0

    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN: Any = _Unknown()


def show(fp: Any) -> str | None:
    """A fingerprint as JSON shows it."""
    return "UNKNOWN" if fp is UNKNOWN else fp


def H(tag: str, b: bytes | str) -> str:
    if isinstance(b, str):
        b = b.encode("utf-8")
    return f"{tag}:" + hashlib.sha256(b"rd/1\0" + b).hexdigest()[:12]


def _norm(v: Any, t: str) -> Any:
    if isinstance(v, str):
        s = unicodedata.normalize("NFC", v).replace("\r\n", "\n").replace("\r", "\n")
        if t == "prose":
            return re.sub(r"\s+", " ", s).strip()
        if t == "text":
            return "\n".join(line.rstrip() for line in s.split("\n")).rstrip()
        return s
    if isinstance(v, dict):
        return {unicodedata.normalize("NFC", str(k)): _norm(x, t) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x, t) for x in v]
    return v


def canon(v: Any, t: str = "json") -> str:
    """Sorted keys, compact separators, NFC strings, floats via repr; prose collapses whitespace, text rstrips."""
    return json.dumps(_norm(v, t), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fp_json(v: Any, t: str = "json") -> str:
    return H("s", canon(v, t))


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _span(lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> str:
    (r0, c0), (r1, c1) = start, end
    if r0 == r1:
        return lines[r0 - 1][c0:c1]
    return lines[r0 - 1][c0:] + "".join(lines[r0:r1 - 1]) + lines[r1 - 1][:c1]


def py_tokens(data: bytes) -> str:
    """Token stream without COMMENT/NL: comments, blank lines and indentation width never count; docstrings do.
    f-strings (split into parts since Python 3.12) are re-joined into one STRING so the stream is version-stable."""
    out: list[str] = []
    lines: list[str] = []
    depth, start = 0, (0, 0)
    for tok in tokenize.tokenize(io.BytesIO(data).readline):
        name = tokenize.tok_name.get(tok.type, str(tok.type))
        if name == "ENCODING":
            lines = data.decode(tok.string, errors="replace").splitlines(keepends=True)
            continue
        if name in ("COMMENT", "NL", "ENDMARKER", "TYPE_COMMENT"):
            continue
        if name.endswith("STRING_START"):            # FSTRING_START (3.12+), TSTRING_START (3.14+)
            if depth == 0:
                start = tok.start
            depth += 1
            continue
        if name.endswith("STRING_END"):
            depth -= 1
            if depth == 0:
                out.append("STRING " + _span(lines, start, tok.end))
            continue
        if depth:
            continue
        out.append(name if name in ("NEWLINE", "INDENT", "DEDENT") else f"{name} {tok.string}")
    return "\n".join(out)


def fp_file(path: str, data: bytes) -> str:
    if path.endswith(".py"):
        try:
            return H("p", py_tokens(data))
        except (tokenize.TokenError, SyntaxError, UnicodeDecodeError, IndexError):
            pass
    elif path.endswith(".json"):
        try:   # key order is kept (a program may iterate it); only layout is dropped
            return H("j", json.dumps(json.loads(data), separators=(",", ":"), ensure_ascii=False))
        except (ValueError, UnicodeDecodeError):
            pass
    return "g:" + git_blob_sha(data)[:12]


def fp_dir(names: Iterable[str]) -> str:
    return H("d", "\n".join(sorted(names)))


def fp_table(cells: Iterable[tuple[str, Any]]) -> str:
    return H("t", canon(sorted([cid, show(fp)] for cid, fp in cells)))


def spec_fp(spec: dict) -> str:
    """The action's own definition. Overrides, sweep and cell values reach a run through cfg:, the platform through
    env:; tolerances and est_hours never count."""
    s = spec or {}
    return fp_json({k: s.get(k) for k in ("command", "config", "replicates", "gpus", "datasets", "env_keys", "code_inputs")}
                   | {"algo": FP_ALGO})


def quantize(v: Any, sig: int = 4) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return float(f"{v:.{sig}g}")
    if isinstance(v, (list, tuple)):
        return [quantize(x, sig) for x in v]
    if isinstance(v, dict):
        return {k: quantize(x, sig) for k, x in v.items()}
    return v


# ---------------------------------------------------------------- cells and globs (shared with rd_exec)

def fmt_value(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v)


def cell_id(values: dict | None) -> str:
    """{"system": "ours", "rate": 8} -> "rate=8,system=ours"; no sweep -> "_"."""
    if not values:
        return "_"
    return ",".join(f"{k}={fmt_value(values[k])}" for k in sorted(values))


def parse_cell(cid: str) -> dict:
    if not cid or cid == "_":
        return {}
    out: dict[str, Any] = {}
    for part in cid.split(","):
        k, _, raw = part.partition("=")
        try:
            out[k] = json.loads(raw)
        except ValueError:
            out[k] = raw
    return out


_GLOB_CACHE: dict[str, re.Pattern] = {}


def glob_re(pattern: str) -> re.Pattern:
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        i, out = 0, []
        while i < len(pattern):
            c = pattern[i]
            if pattern.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
            i += 1
        rx = _GLOB_CACHE[pattern] = re.compile("".join(out) + r"\Z")
    return rx


def glob_match(path: str, pattern: str) -> bool:
    """`**` crosses directories, `*` and `?` do not; a bare directory pattern matches everything under it."""
    pattern = pattern.rstrip("/")
    if not any(ch in pattern for ch in "*?["):
        return path == pattern or path.startswith(pattern + "/")
    return bool(glob_re(pattern).match(path))
