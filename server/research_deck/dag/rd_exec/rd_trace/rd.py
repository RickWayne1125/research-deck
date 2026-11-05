"""`import rd; rd.cfg("sched.chunk.max")` — config reads tracked per key (docs/DAG.md §4.3). Stdlib only.

The config is the merge of $RD_CONFIG (a JSON list of YAML/JSON files under $RD_ROOT) with $RD_OVERRIDES (the spec's
overrides plus this cell's sweep values, dotted keys). Every key read is recorded, misses as ∅, so a run depends on
exactly the keys it read. rd.cfg() without a key returns a mapping that records what is accessed.
"""
import copy
import json
import os
import re

READS = {}          # dotted key -> {"v": value} | {"miss": True}
_MISSING = object()
_CACHE = []


def _scalar(s):
    s = s.strip()
    if s in ("", "~", "null", "Null", "NULL"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if s[:1] == '"':
        return json.loads(s)
    if s[:1] == "'":
        return s[1:-1].replace("''", "'")
    if s[:1] == "[" and s[-1:] == "]":
        return [_scalar(x) for x in s[1:-1].split(",") if x.strip()]
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    return s


def mini_yaml(text):
    """Block mappings, scalars, flow and block lists of scalars: enough for config files when PyYAML is absent."""
    root = {}
    stack = [(-1, root)]
    pending = None
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if not line.strip() or line.strip() in ("---", "..."):
            continue
        ind = len(line) - len(line.lstrip())
        body = line.strip()
        if pending is not None:
            p_ind, p_cont, p_key = pending
            pending = None
            if ind > p_ind:
                p_cont[p_key] = [] if body.startswith("-") else {}
                stack.append((p_ind, p_cont[p_key]))
        while len(stack) > 1 and stack[-1][0] >= ind:
            stack.pop()
        cont = stack[-1][1]
        if body.startswith("-") and isinstance(cont, list):
            cont.append(_scalar(body[1:]))
            continue
        key, _, rest = body.partition(":")
        key = key.strip().strip("\"'")
        if isinstance(cont, dict):
            if rest.strip():
                cont[key] = _scalar(rest)
            else:
                cont[key] = None
                pending = (ind, cont, key)
    return root


def load_text(text, name=""):
    if name.endswith(".json"):
        return json.loads(text)
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        return mini_yaml(text)


def set_dotted(d, key, value):
    parts = key.split(".")
    for part in parts[:-1]:
        if not isinstance(d.get(part), dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value


def merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        elif "." in str(k) and not isinstance(v, dict):
            set_dotted(base, str(k), v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def resolve(files, overrides, root="."):
    merged = {}
    for f in files or []:
        try:
            with open(os.path.join(root, f), encoding="utf-8") as fh:
                data = load_text(fh.read(), f)
        except FileNotFoundError:
            data = None
        if isinstance(data, dict):
            merge(merged, data)
    return merge(merged, overrides or {})


def _config():
    if not _CACHE:
        _CACHE.append(resolve(json.loads(os.environ.get("RD_CONFIG") or "[]"), json.loads(os.environ.get("RD_OVERRIDES") or "{}"),
                              os.environ.get("RD_ROOT") or "."))
    return _CACHE[0]


def _get(d, key):
    for part in key.split("."):
        if isinstance(d, dict) and part in d:
            d = d[part]
        else:
            return _MISSING
    return d


class _Tracked(dict):
    """A read-recording view of a config subtree."""

    def __init__(self, data, prefix):
        super().__init__(data)
        self._p = prefix

    def _key(self, k):
        return "%s.%s" % (self._p, k) if self._p else str(k)

    def __getitem__(self, k):
        if not dict.__contains__(self, k):
            READS[self._key(k)] = {"miss": True}
            raise KeyError(k)
        v = dict.__getitem__(self, k)
        if isinstance(v, dict):
            return _Tracked(v, self._key(k))
        READS[self._key(k)] = {"v": copy.deepcopy(v)}
        return v

    def get(self, k, default=None):
        try:
            return self[k]
        except KeyError:
            return default

    def __contains__(self, k):
        if dict.__contains__(self, k):
            READS[self._key(k)] = {"v": copy.deepcopy(dict.__getitem__(self, k))}
            return True
        READS[self._key(k)] = {"miss": True}
        return False

    def _all(self):
        for k in dict.keys(self):
            READS[self._key(k)] = {"v": copy.deepcopy(dict.__getitem__(self, k))}

    def __iter__(self):
        self._all()
        return dict.__iter__(self)

    def items(self):
        self._all()
        return dict.items(self)

    def keys(self):
        self._all()
        return dict.keys(self)

    def values(self):
        self._all()
        return dict.values(self)


def cfg(key=None, default=None):
    """One config value by dotted key (a miss returns `default` and is recorded), or the tracked mapping."""
    data = _config()
    if key is None:
        return _Tracked(data, "")
    v = _get(data, key)
    if v is _MISSING:
        READS[key] = {"miss": True}
        return default
    READS[key] = {"v": copy.deepcopy(v)}
    return copy.deepcopy(v)


def cell():
    """This cell's sweep values (also applied as config overrides)."""
    return json.loads(os.environ.get("RD_CELL_VALUES") or "{}")
