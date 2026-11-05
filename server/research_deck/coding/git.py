"""Read-only git for the Coding panel: status, log, parsed diffs and files at a revision.

Every call is `git -C <project root> ...` without a shell, with a timeout, no prompts, no pager, no external diff or
textconv drivers and no fsmonitor hook, so a repository's own config cannot make the dashboard run commands.
A project folder inside a larger repository works too: status and log are limited to the folder, diffs use
--relative, and every path is reported relative to the project root.

Diffs are parsed from `git diff -U3 -M` into DiffFile / DiffHunk / DiffLine (web/src/types.ts). The working-tree diff
also lists untracked files as additions, synthesized in the same unified format so one parser handles both.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from ..util import git_filter_overrides, rel_to, safe_join

GIT = shutil.which("git")
TIMEOUT_S = 20
MAX_DIFF_BYTES = 12 * 1024 * 1024     # beyond this a diff is cut at a file boundary (DiffResult.truncated)
MAX_LINES_PER_FILE = 6000             # rows kept per file; additions/deletions still count the whole file
MAX_UNTRACKED_FILES = 200
MAX_UNTRACKED_BYTES = 256 * 1024
MAX_SHOW_BYTES = 4 * 1024 * 1024
MAX_DIRTY = 2000

# Revisions accepted from requests: hex shas, HEAD, HEAD~N / HEAD^, branch and tag names. Never an option ("-..."),
# a range ("a..b"), a reflog selector ("@{...}"), a pathspec or anything with spaces.
_REV_RE = re.compile(r"^(?![-/.])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}(?:[~^][0-9]{0,4})*$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_SAFE_CONFIG = ["-c", "core.quotepath=off", "-c", "core.fsmonitor=false", "-c", "color.ui=never",
                "-c", "log.showSignature=false", "-c", "core.pager=cat"]
_LOG_FORMAT = "%H%x1f%h%x1f%s%x1f%an%x1f%aI%x1f%D%x1e"


class GitError(Exception):
    """git exited non-zero (the message is its stderr)."""


def _run(cwd: Path, args: list[str], *, timeout: float = TIMEOUT_S, stdin: bytes | None = None) -> bytes:
    if not GIT:
        raise GitError("git is not installed")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat", "PAGER": "cat"}
    io = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        filters = git_filter_overrides(GIT, cwd)   # repo-configured filter drivers would run commands
        proc = subprocess.run([GIT, "-C", str(cwd), *_SAFE_CONFIG, *filters, *args], capture_output=True, timeout=timeout,
                              env=env, **io)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"git {args[0]} timed out after {timeout:.0f}s")
    except OSError as e:
        raise GitError(str(e))
    if proc.returncode != 0:
        raise GitError(_text(proc.stderr).strip() or f"git {args[0]} exited with {proc.returncode}")
    return proc.stdout


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


@dataclass(frozen=True)
class Repo:
    root: Path          # the project root; git runs here
    prefix: str         # the project root relative to the repository's top level: "" or "sub/dir/"
    head: str | None    # the commit HEAD points at; None in a repository without commits

    def git(self, *args: str, **kw) -> bytes:
        return _run(self.root, list(args), **kw)


def open_repo(root: Path) -> Repo | None:
    """The repository that contains the project root, or None (not a repository, git missing, unsafe ownership)."""
    try:
        out = _text(_run(root, ["rev-parse", "--is-inside-work-tree", "--show-prefix"], timeout=5)).splitlines()
    except GitError:
        return None
    if not out or out[0].strip() != "true":
        return None
    prefix = out[1].strip() if len(out) > 1 else ""
    return Repo(root, prefix, _verify_commit(root, "HEAD"))


def require_repo(root: Path) -> Repo:
    repo = open_repo(root)
    if not repo:
        raise HTTPException(400, "this project is not a git repository")
    return repo


def _verify_commit(root: Path, rev: str) -> str | None:
    """The full sha of rev's commit, or None if it does not name one."""
    try:
        return _text(_run(root, ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], timeout=5)).strip() or None
    except GitError:
        return None


def check_rev(repo: Repo, rev: str) -> str:
    """Refuse anything that is not a plain revision of this repository (400)."""
    if not isinstance(rev, str) or not _REV_RE.match(rev):
        raise HTTPException(400, f"invalid revision: {rev!r}")
    if not _verify_commit(repo.root, rev):
        raise HTTPException(400, f"unknown revision: {rev}")
    return rev


def project_rel(root: Path, path: str) -> str:
    """A request path as a path relative to the project root (refuses paths that escape it)."""
    return rel_to(root, safe_join(root, path))


def _empty_tree(repo: Repo) -> str:
    # Computed rather than hard-coded so SHA-256 repositories work too.
    return _text(repo.git("hash-object", "-t", "tree", "--stdin", stdin=b"")).strip()


# ------------------------------------------------------------------ status and log

def status(root: Path) -> dict:
    repo = open_repo(root)
    if not repo:
        return {"is_repo": False, "branch": None, "head": None, "dirty": [], "ahead": 0, "behind": 0, "upstream": None}
    out = _text(repo.git("status", "--porcelain=v2", "--branch", "-z", "--untracked-files=normal", "--", "."))
    branch, upstream, ahead, behind = None, None, 0, 0
    dirty: list[dict] = []
    tokens = out.split("\0")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if not tok:
            continue
        if tok.startswith("# "):
            key, _, value = tok[2:].partition(" ")
            if key == "branch.head":
                branch = None if value == "(detached)" else value
            elif key == "branch.upstream":
                upstream = value
            elif key == "branch.ab":
                m = re.match(r"\+(\d+) -(\d+)", value)
                if m:
                    ahead, behind = int(m.group(1)), int(m.group(2))
            continue
        kind = tok[0]
        if kind == "1":
            fields = tok.split(" ", 8)
        elif kind == "2":
            fields = tok.split(" ", 9)
            i += 1                      # with -z the original path of a rename follows as its own field
        elif kind == "u":
            fields = tok.split(" ", 10)
        elif kind == "?":
            fields = ["?", "??", tok[2:]]
        else:                           # "!" (ignored) entries are not requested; skip anything unknown
            continue
        xy, path = fields[1], fields[-1]
        rel = path[len(repo.prefix):] if repo.prefix and path.startswith(repo.prefix) else (None if repo.prefix else path)
        if not rel or len(dirty) >= MAX_DIRTY:
            continue
        dirty.append({"path": rel, "status": _status_letter(kind, xy), "staged": kind in "12" and xy[0] != "."})
    return {"is_repo": True, "branch": branch, "head": repo.head, "dirty": dirty, "ahead": ahead, "behind": behind,
            "upstream": upstream}


def _status_letter(kind: str, xy: str) -> str:
    """One letter relative to HEAD: A new, D deleted, R renamed, M modified, U conflicted, ? untracked."""
    if kind == "?":
        return "?"
    if kind == "u":
        return "U"
    for letter in ("R", "A", "D"):
        if letter in xy:
            return letter
    return "M"


def log(root: Path, limit: int = 100, path: str | None = None) -> list[dict]:
    repo = open_repo(root)
    if not repo or not repo.head:
        return []
    spec = f":(literal){project_rel(root, path)}" if path else "."
    out = _text(repo.git("log", f"--max-count={int(limit)}", f"--format={_LOG_FORMAT}", "--", spec))
    commits = []
    for record in out.split("\x1e"):
        fields = record.strip("\n").split("\x1f")
        if len(fields) < 6:
            continue
        sha, short, subject, author, date, refs = fields[:6]
        commits.append({"sha": sha, "short": short, "subject": subject, "author": author, "date": date,
                        "refs": _parse_refs(refs)})
    return commits


def _parse_refs(decoration: str) -> list[str]:
    """%D ("HEAD -> main, origin/main, tag: v1") -> ["HEAD", "main", "origin/main", "tag: v1"]."""
    refs: list[str] = []
    for part in decoration.split(", "):
        part = part.strip()
        if " -> " in part:
            refs.extend(part.split(" -> ", 1))
        elif part:
            refs.append(part)
    return refs


# ------------------------------------------------------------------ diffs

@dataclass
class RawDiff:
    text: str
    frm: str | None             # what the diff compares from (None: the empty tree)
    to: str | None              # what it compares to (None: the working tree)
    truncated: bool
    untracked: list[str]


def resolve_range(repo: Repo, frm: str | None, to: str | None) -> tuple[list[str], str | None, str | None]:
    """The `git diff` revisions for a request, and the labels reported back.

    nothing      working tree (staged + unstaged) vs HEAD
    from         working tree vs from
    to           the changes `to` introduced (vs its first parent; vs the empty tree for a root commit)
    from + to    from vs to
    """
    frm = check_rev(repo, frm) if frm else None
    to = check_rev(repo, to) if to else None
    if to and not frm:
        parent = f"{to}~1"
        if _verify_commit(repo.root, parent):
            return [parent, to], parent, to
        return [_empty_tree(repo), to], None, to
    if frm and to:
        return [frm, to], frm, to
    if frm:
        return [frm], frm, None
    if repo.head:
        return ["HEAD"], "HEAD", None
    return [_empty_tree(repo)], None, None


def raw_diff(repo: Repo, frm: str | None = None, to: str | None = None, paths: list[str] | None = None,
             exclude: tuple[str, ...] = ()) -> RawDiff:
    """The unified diff text for a range (untracked files included when the range ends at the working tree)."""
    revs, frm_label, to_label = resolve_range(repo, frm, to)
    specs = [f":(literal){project_rel(repo.root, p)}" for p in paths] if paths else ["."]
    specs += [f":(exclude){e}" for e in exclude]
    out = repo.git("diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U3", "-M", "--src-prefix=a/",
                   "--dst-prefix=b/", "--relative", *revs, "--", *specs)
    truncated = False
    if len(out) > MAX_DIFF_BYTES:
        cut = out.rfind(b"\ndiff --git ", 0, MAX_DIFF_BYTES)
        out = out[: cut + 1] if cut > 0 else out[:MAX_DIFF_BYTES]
        truncated = True
    text = _text(out)
    untracked: list[str] = []
    if to_label is None and not truncated:
        listing = _text(repo.git("ls-files", "--others", "--exclude-standard", "-z", "--", *specs))
        names = [n for n in listing.split("\0") if n]
        if len(names) > MAX_UNTRACKED_FILES:
            names, truncated = names[:MAX_UNTRACKED_FILES], True
        for name in names:
            patch = _new_file_patch(repo.root, name)
            if patch:
                text += patch
                untracked.append(name)
    return RawDiff(text, frm_label, to_label, truncated, untracked)


def diff(root: Path, frm: str | None = None, to: str | None = None, path: str | None = None) -> dict:
    repo = open_repo(root)
    if not repo:
        return {"from": frm, "to": to, "files": [], "truncated": False, "is_repo": False}
    raw = raw_diff(repo, frm, to, [path] if path else None)
    files, cut = parse_diff(raw.text)
    untracked = set(raw.untracked)
    for f in files:
        f["untracked"] = f["status"] == "A" and f["path"] in untracked
    return {"from": raw.frm, "to": raw.to, "files": files, "truncated": raw.truncated or cut}


def show(root: Path, rev: str | None, path: str) -> dict:
    """A file's text at a revision."""
    repo = require_repo(root)
    rev = check_rev(repo, rev or "HEAD")
    rel = project_rel(root, path)
    spec = f"{rev}:./{rel}"
    try:
        size = int(_text(repo.git("cat-file", "-s", spec)).strip() or 0)
    except (GitError, ValueError):
        raise HTTPException(404, f"{rel} does not exist at {rev}")
    if size > MAX_SHOW_BYTES:
        raise HTTPException(413, "file too large to show here")
    try:
        data = repo.git("cat-file", "blob", spec)
    except GitError:
        raise HTTPException(404, f"{rel} is not a file at {rev}")
    if b"\0" in data[:8000]:
        raise HTTPException(415, "not a text file")
    return {"path": rel, "rev": rev, "content": _text(data)}


def _new_file_patch(root: Path, rel: str) -> str:
    """An untracked file as a `new file` patch, the way `git diff` would print it after `git add -N`."""
    try:
        target = safe_join(root, rel)
    except HTTPException:
        return ""
    if not target.is_file():
        return ""
    try:
        with target.open("rb") as fh:
            data = fh.read(MAX_UNTRACKED_BYTES + 1)
    except OSError:
        return ""
    old_name, new_name = _quote("a/" + rel), _quote("b/" + rel)
    head = f"diff --git {old_name} {new_name}\nnew file mode 100644\n"
    if b"\0" in data[:8000]:
        return head + f"Binary files /dev/null and {new_name} differ\n"
    if not data:
        return head
    text = data[:MAX_UNTRACKED_BYTES].decode("utf-8", "replace")
    lines = text.split("\n")
    no_eol = not text.endswith("\n")
    if not no_eol:
        lines.pop()
    if len(data) > MAX_UNTRACKED_BYTES:        # keep whole lines only
        lines.pop()
        no_eol = False
    body = "".join(f"+{line}\n" for line in lines)
    patch = f"{head}--- /dev/null\n+++ {new_name}\n@@ -0,0 +1,{len(lines)} @@\n{body}"
    return patch + ("\\ No newline at end of file\n" if no_eol else "")


def parse_diff(text: str) -> tuple[list[dict], bool]:
    """Parse `git diff` output into DiffFile dicts. Returns (files, truncated) — truncated if a file hit the row cap."""
    files: list[dict] = []
    cur: dict | None = None
    hunk: dict | None = None
    old_left = new_left = old_no = new_no = kept = 0
    truncated = False
    for raw in text.split("\n"):
        if cur is not None and hunk is not None and (old_left > 0 or new_left > 0) and not raw.startswith("\\"):
            # Inside a hunk every line is content, whatever it looks like ("--- x" can be a deleted "-- x").
            tag = raw[0] if raw else " "
            if tag == "-":
                entry = {"t": "-", "old": old_no, "new": None, "text": raw[1:]}
                old_no, old_left = old_no + 1, old_left - 1
                cur["deletions"] += 1
            elif tag == "+":
                entry = {"t": "+", "old": None, "new": new_no, "text": raw[1:]}
                new_no, new_left = new_no + 1, new_left - 1
                cur["additions"] += 1
            else:
                entry = {"t": " ", "old": old_no, "new": new_no, "text": raw[1:]}
                old_no, new_no, old_left, new_left = old_no + 1, new_no + 1, old_left - 1, new_left - 1
            if kept < MAX_LINES_PER_FILE:
                hunk["lines"].append(entry)
                kept += 1
            elif not cur["truncated"]:
                cur["truncated"] = truncated = True
            continue
        if raw.startswith("\\"):                       # "\ No newline at end of file"
            continue
        if raw.startswith("diff --git "):
            a, b = _header_paths(raw[len("diff --git "):])
            cur = {"path": b or a or "", "old_path": None, "status": "M", "additions": 0, "deletions": 0, "hunks": [],
                   "binary": False, "truncated": False, "_a": a, "_b": b}
            files.append(cur)
            hunk, kept = None, 0
            continue
        if cur is None:
            continue
        m = _HUNK_RE.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(3))
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_left = int(m.group(4)) if m.group(4) is not None else 1
            hunk = {"header": raw, "lines": []}
            if kept < MAX_LINES_PER_FILE:
                cur["hunks"].append(hunk)
            continue
        # extended header lines of the current file
        if raw.startswith("new file mode"):
            cur["status"] = "A"
        elif raw.startswith("deleted file mode"):
            cur["status"] = "D"
        elif raw.startswith("rename from ") or raw.startswith("copy from "):
            cur["_a"] = _unquote(raw.split(" from ", 1)[1])
            cur["status"] = "R" if raw.startswith("rename") else "A"
        elif raw.startswith("rename to ") or raw.startswith("copy to "):
            cur["_b"] = _unquote(raw.split(" to ", 1)[1])
        elif raw.startswith("--- "):
            side = _side_path(raw[4:])
            if side is None:
                cur["status"] = "A"
            else:
                cur["_a"] = side
        elif raw.startswith("+++ "):
            side = _side_path(raw[4:])
            if side is None:
                cur["status"] = "D"
            else:
                cur["_b"] = side
        elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            cur["binary"] = True
            if raw.startswith("Binary files /dev/null and "):
                cur["status"] = "A"
            elif raw.endswith(" and /dev/null differ"):
                cur["status"] = "D"
    for f in files:
        a, b = f.pop("_a"), f.pop("_b")
        f["path"] = (a or b or f["path"]) if f["status"] == "D" else (b or a or f["path"])
        f["old_path"] = a if f["status"] == "R" and a != f["path"] else None
    return files, truncated


def _side_path(value: str) -> str | None:
    """The path on a ---/+++ line ("a/x", "b/x", quoted, or /dev/null). git appends a tab to names with spaces."""
    value = _unquote(value) if value.startswith('"') else value.split("\t", 1)[0]
    if value == "/dev/null":
        return None
    return value[2:] if value[:2] in ("a/", "b/") else value


def _header_paths(rest: str) -> tuple[str | None, str | None]:
    """The two paths of a `diff --git a/X b/Y` line (only a fallback: ---/+++ and rename lines are authoritative)."""
    if '"' in rest:
        tokens: list[str] = []
        s = rest
        while s and len(tokens) < 2:
            s = s.lstrip(" ")
            if s.startswith('"'):
                end = 1
                while end < len(s) and (s[end] != '"' or s[end - 1] == "\\"):
                    end += 1
                tokens.append(_unquote(s[: end + 1]))
                s = s[end + 1:]
            else:
                cut = s.find(' "')
                tokens.append(s if cut < 0 else s[:cut])
                s = "" if cut < 0 else s[cut:]
        a, b = (tokens + [None, None])[:2]
    elif rest.startswith("a/"):
        # Unquoted names may contain spaces; with equal names (no rename) the line splits exactly in the middle.
        half = (len(rest) - 1) // 2
        if len(rest) % 2 == 1 and rest[half] == " " and rest[:half][2:] == rest[half + 1:][2:]:
            a, b = rest[:half], rest[half + 1:]
        else:
            cut = rest.find(" b/")
            a, b = (rest[:cut], rest[cut + 1:]) if cut > 0 else (rest, None)
    else:
        return None, None
    strip = lambda p: p[2:] if p and p[:2] in ("a/", "b/") else p  # noqa: E731
    return strip(a), strip(b)


_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
_ESCAPE_OF = {chr(code): letter for letter, code in _ESCAPES.items()}


def _unquote(value: str) -> str:
    """git's C-style quoting ("a/caf\\303\\251") back to text."""
    if not (len(value) >= 2 and value[0] == '"' and value[-1] == '"'):
        return value
    body, out, i = value[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            octal = body[i + 1:i + 4]
            if len(octal) == 3 and all(ch in "01234567" for ch in octal):
                out.append(int(octal, 8) & 0xFF)          # one byte of a UTF-8 sequence
                i += 4
                continue
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
            else:
                out.extend(nxt.encode("utf-8"))
            i += 2
            continue
        out.extend(c.encode("utf-8"))
        i += 1
    return out.decode("utf-8", "replace")


def _quote(path: str) -> str:
    """Quote a path the way git does when it holds quotes, backslashes or control characters."""
    def plain(ch: str) -> bool:
        return 32 <= ord(ch) != 127 and ch not in _ESCAPE_OF
    if all(plain(ch) for ch in path):
        return path
    out = []
    for ch in path:
        if ch in _ESCAPE_OF:
            out.append("\\" + _ESCAPE_OF[ch])
        elif not plain(ch):
            out.append(f"\\{ord(ch):03o}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'
