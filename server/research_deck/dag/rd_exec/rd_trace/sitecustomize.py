"""rd-exec tracer, loaded by every Python process of a job through PYTHONPATH (docs/DAG.md §4.3).

Records, line-buffered into $RD_TRACE_DIR/trace.<pid>.jsonl so os._exit (fork children) loses nothing:
  ["R", path] / ["W", path]   files opened for reading / writing
  ["L", path]                 directories listed by user code (not by the import machinery)
  ["X", argv-json]            subprocesses
and at exit {"modules", "cfg_reads", "pkgs", "python"}. Chains to any pre-existing sitecustomize. Stdlib only.
"""
import atexit
import json
import os
import sys

_DIR = os.environ.get("RD_TRACE_DIR")
_HERE = os.path.dirname(os.path.abspath(__file__))
_IMPORT_MACHINERY = ("importlib", "zipimport", "pkgutil", "site", "sysconfig", "pkg_resources", "_distutils_hack",
                     "linecache", "inspect", "traceback", "encodings", "codecs", "tokenize", "sitecustomize")
_WRAPPERS = ("os", "glob", "pathlib", "posixpath", "fnmatch", "shutil", "genericpath")


def _install():
    sys._rd_trace_installed = True
    fh = open(os.path.join(_DIR, "trace.%d.jsonl" % os.getpid()), "a", buffering=1, encoding="utf-8")
    seen = set()
    busy = [False]
    realpath = os.path.realpath
    skip = (realpath(_DIR), _HERE)

    def emit(kind, value):
        if (kind, value) not in seen:
            seen.add((kind, value))
            fh.write(json.dumps([kind, value]) + "\n")

    def caller_module():
        f = sys._getframe(2)
        while f is not None and str(f.f_globals.get("__name__", "")).split(".")[0] in _WRAPPERS:
            f = f.f_back
        return str(f.f_globals.get("__name__", "")) if f is not None else ""

    def hook(event, args):
        if busy[0]:
            return
        busy[0] = True
        try:
            if event == "open" and args and isinstance(args[0], (str, bytes)):
                p = realpath(os.fsdecode(args[0]))
                if p.startswith(skip) or ("/__pycache__/" in p and p.endswith(".pyc")):
                    return
                mode, flags = (list(args[1:3]) + [None, None])[:2]
                if isinstance(mode, str):
                    writing = any(c in mode for c in "wax+")
                else:
                    writing = isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC))
                emit("W" if writing else "R", p)
            elif event in ("os.listdir", "os.scandir", "glob.glob"):
                target = args[0] if args else None
                if isinstance(target, int):
                    return
                target = os.fsdecode(target) if target is not None else "."
                if event == "glob.glob":            # the static prefix of the pattern
                    parts = []
                    for part in target.split("/"):
                        if any(c in part for c in "*?["):
                            break
                        parts.append(part)
                    target = "/".join(parts) or "."
                if caller_module().split(".")[0] in _IMPORT_MACHINERY:
                    return
                emit("L", realpath(target))
            elif event == "subprocess.Popen" and len(args) > 1:
                argv = args[1] if isinstance(args[1], (list, tuple)) else [args[1]]
                emit("X", json.dumps([os.fsdecode(a) if isinstance(a, (str, bytes, os.PathLike)) else str(a) for a in argv]))
        except Exception:
            pass
        finally:
            busy[0] = False

    def dump():
        busy[0] = True
        try:
            import platform
            mods = sorted({realpath(m.__file__) for m in list(sys.modules.values())
                           if isinstance(getattr(m, "__file__", None), str)})
            rd = sys.modules.get("rd")
            pkgs = {}
            try:
                from importlib import metadata
                tops = metadata.packages_distributions()
                for m in mods:
                    for marker in ("/site-packages/", "/dist-packages/"):
                        if marker in m:
                            top = m.split(marker, 1)[1].split("/")[0]
                            top = top[:-3] if top.endswith(".py") else top
                            for dist in tops.get(top, []):
                                if dist not in pkgs:
                                    try:
                                        pkgs[dist] = metadata.version(dist)
                                    except Exception:
                                        pass
            except Exception:
                pass
            fh.write(json.dumps({"modules": mods, "cfg_reads": getattr(rd, "READS", None) if rd else None, "pkgs": pkgs,
                                 "python": platform.python_version()}) + "\n")
            fh.flush()
        except Exception:
            pass

    atexit.register(dump)
    sys.addaudithook(hook)


def _chain():
    """Run the sitecustomize this one shadows, if any."""
    try:
        import importlib.machinery
        import importlib.util
        spec = importlib.machinery.PathFinder.find_spec("sitecustomize", [p for p in sys.path if os.path.abspath(p or ".") != _HERE])
        if spec and spec.loader and spec.origin and os.path.dirname(os.path.abspath(spec.origin)) != _HERE:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
    except Exception:
        pass


if _DIR and not getattr(sys, "_rd_trace_installed", False):
    _install()
_chain()
