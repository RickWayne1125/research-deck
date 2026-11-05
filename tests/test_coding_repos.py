"""A research workspace with several repositories side by side (code.repos)."""
import yaml

from conftest import git


def make_workspace(root):
    for name in ("impl", "upstream"):
        repo = root / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "core.py").write_text(f"NAME = {name!r}\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", f"{name}: first")
    (root / "impl" / "core.py").write_text("NAME = 'impl, edited'\n")
    cfg_path = root / ".research" / "project.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["code"] = {"roots": ["impl"], "repos": ["impl", "upstream"]}
    cfg_path.write_text(yaml.safe_dump(cfg))


def test_repos_are_listed_and_paths_stay_project_relative(client, project):
    pid, root = project
    make_workspace(root)
    base = f"/api/projects/{pid}"
    listing = client.get(f"{base}/git/repos").json()
    assert [r["repo"] for r in listing] == ["impl", "upstream"] and listing[0]["dirty"] == 1
    # no ?repo: the workspace root is not a repository, so the first listed one is used
    st = client.get(f"{base}/git/status").json()
    assert st["is_repo"] and st["repo"] == "impl" and [d["path"] for d in st["dirty"]] == ["impl/core.py"]
    diff = client.get(f"{base}/git/diff", params={"repo": "impl"}).json()
    assert [f["path"] for f in diff["files"]] == ["impl/core.py"]
    assert client.get(f"{base}/git/status", params={"repo": "upstream"}).json()["dirty"] == []
    shown = client.get(f"{base}/git/show", params={"repo": "impl", "path": "impl/core.py", "rev": "HEAD"}).json()
    assert shown["content"] == "NAME = 'impl'\n"
    assert len(client.get(f"{base}/git/log", params={"repo": "upstream"}).json()) == 1


def test_unlisted_repos_and_foreign_paths_are_refused(client, project):
    pid, root = project
    make_workspace(root)
    base = f"/api/projects/{pid}"
    assert client.get(f"{base}/git/status", params={"repo": "../elsewhere"}).status_code == 400
    assert client.get(f"{base}/git/show", params={"repo": "impl", "path": "upstream/core.py"}).status_code == 400
    r = client.post(f"{base}/coding/review", json={"repo": "impl"})
    assert r.status_code == 200 and r.json()["run_id"]
