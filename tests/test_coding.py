"""Coding panel backend: git status / log / diff / show, architecture extraction, review and explain runs.

Runs against a throwaway git repository; agents are faked (RD_FAKE_AGENT=1) and never reach a real CLI.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from research_deck import config

CORE_V1 = "from pkg import util\n\n\ndef run(xs):\n    return [util.double(x) for x in xs]\n"
CORE_V2 = "from pkg import util\nfrom .util import double\n\n\ndef run(xs):\n    return [double(x) for x in xs if x]\n"
UTIL = "def double(x):\n    return 2 * x\n\n\ndef half(x):\n    return x / 2\n"
OLD = "".join(f"line {i}\n" for i in range(1, 21))
# A line that starts with "-- " so its deletion reads "--- ..." inside a hunk.
NOTES = "first note\n-- dashed note\n"


def git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com", "GIT_COMMITTER_NAME": "Ada",
           "GIT_COMMITTER_EMAIL": "ada@example.com", "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin"}
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def client(tmp_path, monkeypatch):
    local = tmp_path / "local"
    monkeypatch.setenv("RD_FAKE_AGENT", "1")
    monkeypatch.setenv("RD_LOCAL_DIR", str(local))
    monkeypatch.setattr(config, "FAKE_AGENT", True)
    monkeypatch.setattr(config, "LOCAL_DIR", local)
    monkeypatch.setattr(config, "REGISTRY_FILE", local / "projects.json")
    monkeypatch.setattr(config, "SETTINGS_FILE", local / "settings.json")
    monkeypatch.setattr(config, "DEMO_ENABLED", False)
    from research_deck.app import create_app
    return TestClient(create_app(), headers={"X-RD-Request": "1", "Sec-Fetch-Site": "same-origin"})


@pytest.fixture
def repo(tmp_path) -> dict:
    root = tmp_path / "proj"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "web").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "src" / "pkg" / "__init__.py").write_text("")
    (root / "src" / "pkg" / "core.py").write_text(CORE_V1)
    (root / "src" / "pkg" / "util.py").write_text(UTIL)
    (root / "src" / "old.py").write_text(OLD)
    (root / "notes.txt").write_text(NOTES)
    (root / "src" / "web" / "a.ts").write_text("import { b } from './b';\nimport type { C } from \"./c.js\";\nexport const a = b;\n")
    (root / "src" / "web" / "b.ts").write_text("export const b = 1;\n")
    (root / "src" / "web" / "c.ts").write_text("export interface C { x: number }\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "first: core, util, old")
    first = git(root, "rev-parse", "HEAD").strip()
    # second commit: modify core, rename old.py (one line changed), delete notes.txt
    (root / "src" / "pkg" / "core.py").write_text(CORE_V2)
    git(root, "mv", "src/old.py", "src/renamed.py")
    (root / "src" / "renamed.py").write_text(OLD.replace("line 10\n", "line ten\n"))
    git(root, "rm", "-q", "notes.txt")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "second: rename and delete")
    second = git(root, "rev-parse", "HEAD").strip()
    # dirty: one modified tracked file, one untracked file
    (root / "src" / "pkg" / "util.py").write_text(UTIL.replace("return x / 2", "return x * 0.5"))
    (root / "src" / "pkg" / "extra.py").write_text("from . import core\n\nVALUE = 3\n")
    return {"root": root, "first": first, "second": second}


def add_project(client: TestClient, root: Path) -> str:
    r = client.post("/api/projects", json={"root": str(root)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def by_path(files: list[dict]) -> dict[str, dict]:
    return {f["path"]: f for f in files}


# ------------------------------------------------------------------ git

def test_status(client, repo):
    pid = add_project(client, repo["root"])
    s = client.get(f"/api/projects/{pid}/git/status").json()
    assert s["is_repo"] is True
    assert s["branch"] == "main"
    assert s["head"] == repo["second"]
    dirty = {d["path"]: d["status"] for d in s["dirty"]}
    assert dirty["src/pkg/util.py"] == "M"
    assert dirty["src/pkg/extra.py"] == "?"
    assert s["ahead"] == 0 and s["behind"] == 0


def test_log_and_path_filter(client, repo):
    pid = add_project(client, repo["root"])
    commits = client.get(f"/api/projects/{pid}/git/log").json()
    assert [c["sha"] for c in commits] == [repo["second"], repo["first"]]
    top = commits[0]
    assert top["subject"] == "second: rename and delete"
    assert top["author"] == "Ada"
    assert repo["second"].startswith(top["short"]) and len(top["short"]) >= 7
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", top["date"])
    assert "main" in top["refs"] and "HEAD" in top["refs"]
    assert top["node_ids"] == []          # no DAG engine in this test
    only_first = client.get(f"/api/projects/{pid}/git/log", params={"path": "src/pkg/util.py"}).json()
    assert [c["sha"] for c in only_first] == [repo["first"]]
    assert len(client.get(f"/api/projects/{pid}/git/log", params={"limit": 1}).json()) == 1
    assert client.get(f"/api/projects/{pid}/git/log", params={"limit": 501}).status_code == 422


def test_diff_of_a_commit_parses_rename_delete_and_line_numbers(client, repo):
    pid = add_project(client, repo["root"])
    d = client.get(f"/api/projects/{pid}/git/diff", params={"to": repo["second"]}).json()
    assert d["to"] == repo["second"]
    files = by_path(d["files"])
    assert set(files) == {"src/pkg/core.py", "src/renamed.py", "notes.txt"}

    renamed = files["src/renamed.py"]
    assert renamed["status"] == "R" and renamed["old_path"] == "src/old.py"
    assert (renamed["additions"], renamed["deletions"]) == (1, 1)
    lines = renamed["hunks"][0]["lines"]
    deleted = next(l for l in lines if l["t"] == "-")
    added = next(l for l in lines if l["t"] == "+")
    assert deleted == {"t": "-", "old": 10, "new": None, "text": "line 10"}
    assert added == {"t": "+", "old": None, "new": 10, "text": "line ten"}
    ctx = [l for l in lines if l["t"] == " "]
    assert ctx[0]["old"] == ctx[0]["new"] == 7 and ctx[0]["text"] == "line 7"

    notes = files["notes.txt"]
    assert notes["status"] == "D" and notes["old_path"] is None
    assert notes["deletions"] == 2 and notes["additions"] == 0
    assert [(l["old"], l["new"], l["text"]) for l in notes["hunks"][0]["lines"]] == [(1, None, "first note"), (2, None, "-- dashed note")]

    core = files["src/pkg/core.py"]
    assert core["status"] == "M"
    assert core["hunks"][0]["header"].startswith("@@ -1,5 +1,6 @@")
    plus = [l for h in core["hunks"] for l in h["lines"] if l["t"] == "+"]
    assert [l["new"] for l in plus] == [2, 6]

    # the same range given explicitly
    d2 = client.get(f"/api/projects/{pid}/git/diff", params={"from": repo["first"], "to": repo["second"]}).json()
    assert by_path(d2["files"]).keys() == files.keys()


def test_working_tree_diff_includes_untracked(client, repo):
    pid = add_project(client, repo["root"])
    d = client.get(f"/api/projects/{pid}/git/diff").json()
    assert d["from"] == "HEAD" and d["to"] is None
    files = by_path(d["files"])
    util = files["src/pkg/util.py"]
    assert util["status"] == "M" and not util["untracked"]
    rows = util["hunks"][0]["lines"]
    assert next(l for l in rows if l["t"] == "-") == {"t": "-", "old": 6, "new": None, "text": "    return x / 2"}
    assert next(l for l in rows if l["t"] == "+") == {"t": "+", "old": None, "new": 6, "text": "    return x * 0.5"}
    extra = files["src/pkg/extra.py"]
    assert extra["status"] == "A" and extra["untracked"] and extra["additions"] == 3
    assert [l["new"] for l in extra["hunks"][0]["lines"]] == [1, 2, 3]
    # filtered to one path
    one = client.get(f"/api/projects/{pid}/git/diff", params={"path": "src/pkg/util.py"}).json()
    assert [f["path"] for f in one["files"]] == ["src/pkg/util.py"]


def test_root_commit_diff_against_empty_tree(client, repo):
    pid = add_project(client, repo["root"])
    d = client.get(f"/api/projects/{pid}/git/diff", params={"to": repo["first"]}).json()
    assert d["from"] is None
    assert all(f["status"] == "A" for f in d["files"])
    assert "src/old.py" in by_path(d["files"])


def test_bad_revisions_and_paths_are_refused(client, repo):
    pid = add_project(client, repo["root"])
    url = f"/api/projects/{pid}/git/diff"
    for bad in ("--output=/tmp/x", "HEAD..main", "main@{1}", "a b", "-p", "nonexistent-branch", "deadbeef"):
        r = client.get(url, params={"from": bad})
        assert r.status_code == 400, (bad, r.text)
    assert client.get(url, params={"path": "../outside"}).status_code == 400
    assert client.get(f"/api/projects/{pid}/git/show", params={"rev": "--help", "path": "src/old.py"}).status_code == 400
    assert client.get(f"/api/projects/{pid}/git/log", params={"path": "../../etc"}).status_code == 400
    # accepted forms
    assert client.get(url, params={"from": "HEAD~1", "to": "main"}).status_code == 200
    assert client.get(url, params={"from": repo["first"][:8]}).status_code == 200


def test_show_file_at_revision(client, repo):
    pid = add_project(client, repo["root"])
    r = client.get(f"/api/projects/{pid}/git/show", params={"rev": repo["first"], "path": "src/old.py"})
    assert r.status_code == 200 and r.json()["content"] == OLD
    assert client.get(f"/api/projects/{pid}/git/show", params={"path": "src/old.py"}).status_code == 404  # renamed at HEAD
    assert client.get(f"/api/projects/{pid}/git/show", params={"path": "src/renamed.py"}).json()["content"].count("line ten") == 1


def test_non_repo_project(client, tmp_path):
    root = tmp_path / "plain"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("import b\n")
    (root / "src" / "b.py").write_text("X = 1\n")
    pid = add_project(client, root)
    s = client.get(f"/api/projects/{pid}/git/status")
    assert s.status_code == 200 and s.json()["is_repo"] is False and s.json()["dirty"] == []
    assert client.get(f"/api/projects/{pid}/git/log").json() == []
    assert client.get(f"/api/projects/{pid}/git/diff").json()["files"] == []
    assert client.get(f"/api/projects/{pid}/git/show", params={"path": "src/a.py"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/coding/review", json={}).status_code == 400
    arch = client.get(f"/api/projects/{pid}/architecture").json()
    assert {"from": "src/a.py", "to": "src/b.py", "kind": "import"} in arch["edges"]


def test_subfolder_of_a_repository(client, repo):
    sub = repo["root"] / "src"
    pid = add_project(client, sub)
    s = client.get(f"/api/projects/{pid}/git/status").json()
    assert s["is_repo"] and {d["path"] for d in s["dirty"]} >= {"pkg/util.py", "pkg/extra.py"}
    d = client.get(f"/api/projects/{pid}/git/diff").json()
    assert {"pkg/util.py", "pkg/extra.py"} <= set(by_path(d["files"]))
    c = client.get(f"/api/projects/{pid}/git/diff", params={"to": repo["second"]}).json()
    assert "notes.txt" not in by_path(c["files"]) and by_path(c["files"])["renamed.py"]["old_path"] == "old.py"
    assert client.get(f"/api/projects/{pid}/git/show", params={"rev": repo["first"], "path": "old.py"}).json()["content"] == OLD


# ------------------------------------------------------------------ parser edge cases

def test_parse_diff_edge_cases():
    from research_deck.coding.git import parse_diff
    text = (
        'diff --git "a/sp\\tace.txt" "b/sp\\tace.txt"\n'
        "index 1..2 100644\n"
        '--- "a/sp\\tace.txt"\n'
        '+++ "b/sp\\tace.txt"\n'
        "@@ -1,2 +1,2 @@\n"
        "--- not a header\n"
        "+++ also content\n"
        " keep\n"
        "\\ No newline at end of file\n"
        "diff --git a/with space.txt b/with space.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/with space.txt\t\n"
        "@@ -0,0 +1 @@\n"
        "+hello\n"
        "diff --git a/img.png b/img.png\n"
        "deleted file mode 100644\n"
        "Binary files a/img.png and /dev/null differ\n"
    )
    files, truncated = parse_diff(text)
    assert not truncated
    first, second, third = files
    assert first["path"] == "sp\tace.txt" and first["status"] == "M"
    assert [(l["t"], l["old"], l["new"], l["text"]) for l in first["hunks"][0]["lines"]] == [
        ("-", 1, None, "-- not a header"), ("+", None, 1, "++ also content"), (" ", 2, 2, "keep")]
    assert second["path"] == "with space.txt" and second["status"] == "A" and second["additions"] == 1
    assert third["path"] == "img.png" and third["status"] == "D" and third["binary"]


# ------------------------------------------------------------------ architecture

def test_architecture_imports_and_components(client, repo):
    pid = add_project(client, repo["root"])
    (repo["root"] / ".research" / "architecture.yaml").write_text(
        "components:\n"
        "  - {id: engine, label: Engine, node_id: D1, paths: ['src/pkg/**'], description: the core}\n"
        "  - {id: ui, label: UI, paths: ['src/web']}\n")
    arch = client.get(f"/api/projects/{pid}/architecture").json()
    mods = {m["id"]: m for m in arch["modules"]}
    assert mods["src/pkg/core.py"]["label"] == "pkg.core" and mods["src/pkg/core.py"]["kind"] == "module"
    assert mods["src/pkg/__init__.py"]["kind"] == "package"
    assert mods["src/pkg/core.py"]["loc"] == 4           # non-blank lines
    edges = {(e["from"], e["to"]) for e in arch["edges"]}
    assert ("src/pkg/core.py", "src/pkg/util.py") in edges          # from pkg import util / from .util import double
    assert ("src/pkg/extra.py", "src/pkg/core.py") in edges         # from . import core
    assert ("src/web/a.ts", "src/web/b.ts") in edges                # './b'
    assert ("src/web/a.ts", "src/web/c.ts") in edges                # './c.js' -> c.ts
    assert mods["src/pkg/core.py"]["component"] == "engine"
    assert mods["src/web/a.ts"]["component"] == "ui"
    assert mods["src/renamed.py"]["component"] is None
    comp = next(c for c in arch["components"] if c["id"] == "engine")
    assert comp["node_id"] == "D1" and comp["label"] == "Engine"
    # cached until a file changes
    again = client.get(f"/api/projects/{pid}/architecture").json()
    assert again["generated_at"] == arch["generated_at"]
    (repo["root"] / "src" / "pkg" / "new_mod.py").write_text("from pkg.util import half\n")
    third = client.get(f"/api/projects/{pid}/architecture").json()
    assert ("src/pkg/new_mod.py", "src/pkg/util.py") in {(e["from"], e["to"]) for e in third["edges"]}


def test_dag_module_merges_into_the_component_that_links_it(client, repo, monkeypatch):
    """Regression: a module node (`mod.engine`) came back as a second component next to the declared `engine` whose
    node_id names it, so every component showed twice."""
    from research_deck.dag import service as dag
    pid = add_project(client, repo["root"])
    (repo["root"] / ".research" / "architecture.yaml").write_text(
        "components:\n  - {id: engine, label: Engine, node_id: mod.engine, paths: ['src/pkg/**']}\n")
    monkeypatch.setattr(dag, "design_components", lambda _pid: [
        {"id": "mod.engine", "label": "Engine module", "node_id": "mod.engine", "paths": ["src/pkg/**"],
         "description": "implements design.core#loop"},
        {"id": "mod.web", "label": "Web", "node_id": "mod.web", "paths": ["src/web/**"], "description": ""}])
    comps = client.get(f"/api/projects/{pid}/architecture").json()["components"]
    assert [(c["id"], c["node_id"], c["source"]) for c in comps] == [("engine", "mod.engine", "yaml"), ("mod.web", "mod.web", "dag")]
    assert comps[0]["label"] == "Engine" and comps[0]["description"] == "implements design.core#loop"


def test_architecture_with_missing_code_root(client, repo):
    pid = add_project(client, repo["root"])
    client.patch(f"/api/projects/{pid}/config", json={"code": {"roots": ["nowhere", "../escape"]}})
    arch = client.get(f"/api/projects/{pid}/architecture").json()
    assert arch["modules"] == [] and len(arch["warnings"]) == 2


# ------------------------------------------------------------------ agent runs (fake)

def wait_text(run_id: str) -> str:
    from research_deck.agents import runner
    run = runner.get(run_id)
    assert run is not None and run.wait(10)
    assert run.status == "done", run.error
    return run.text


def test_review_runs_in_the_project_conversation(client, repo):
    pid = add_project(client, repo["root"])
    r = client.post(f"/api/projects/{pid}/coding/review", json={"lang": "en"})
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["run_id"] and started["provider"] == "fake" and started["files"] >= 2
    from research_deck.agents import runner
    spec = runner.get(started["run_id"]).spec
    assert spec.panel == "project" and spec.purpose == "code-review" and spec.ephemeral and spec.permission == "read"
    assert spec.tools is True
    assert "src/pkg/util.py" in spec.prompt and ".research/" not in spec.prompt   # dashboard state is not reviewed
    text = wait_text(started["run_id"])
    block = re.search(r"```json\n(.*?)```", text, re.S).group(1)
    findings = json.loads(block)["findings"]
    assert findings and findings[0]["severity"] in ("high", "medium", "low", "info") and findings[0]["file"]

    commit = client.post(f"/api/projects/{pid}/coding/review", json={"to": repo["second"], "focus": {"path": "src/renamed.py", "start_line": 10, "end_line": 10}})
    assert commit.status_code == 200
    assert "Focus on src/renamed.py lines 10–10" in runner.get(commit.json()["run_id"]).spec.prompt
    assert client.post(f"/api/projects/{pid}/coding/review", json={"from": "HEAD", "to": "HEAD"}).status_code == 400  # empty
    assert client.post(f"/api/projects/{pid}/coding/review", json={"to": "--exec=x"}).status_code == 400


def test_explain_runs_in_the_project_conversation(client, repo):
    pid = add_project(client, repo["root"])
    r = client.post(f"/api/projects/{pid}/coding/explain", json={"path": "src/pkg/core.py", "start_line": 2, "end_line": 3, "lang": "zh"})
    assert r.status_code == 200, r.text
    started = r.json()
    from research_deck.agents import runner
    spec = runner.get(started["run_id"]).spec
    assert spec.panel == "project" and spec.purpose == "code-explain" and spec.permission == "read"
    assert "lines 2–3 of `src/pkg/core.py`" in spec.prompt and "from .util import double" in spec.prompt
    assert "Imports: src/pkg/util.py" in spec.prompt              # the architecture context
    assert "作用" in wait_text(started["run_id"])
    whole = client.post(f"/api/projects/{pid}/coding/explain", json={"path": "src/old.py", "rev": repo["first"]})
    assert whole.status_code == 200 and whole.json()["end_line"] == 20
    assert client.post(f"/api/projects/{pid}/coding/explain", json={"path": "../x.py"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/coding/explain", json={"path": "src/missing.py"}).status_code == 404
    assert client.post(f"/api/projects/{pid}/coding/explain", json={"path": "src/pkg/core.py", "start_line": 99}).status_code == 400
