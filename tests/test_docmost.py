"""Docmost: the site address, page links, the saved sign-in, the sign-in window's outcome, and the one-way note sync
against a made-up Docmost (httpx.MockTransport), including an edit made in Docmost that stops the push for review."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import uuid

import httpx
import pytest

from research_deck import vault
from research_deck.docmost import client as dm
from research_deck.docmost import session, sync

SITE = "https://docs.example.com"


class FakeDocmost:
    """Pages of one space. Docmost renders Markdown back its own way: "* " bullets come back as "- "."""

    def __init__(self):
        root = self._new("Team notes", None, "")
        self.root = root
        self.calls: list[str] = []

    pages: dict[str, dict]

    def _new(self, title: str, parent: str | None, content: str) -> dict:
        if not hasattr(self, "pages"):
            self.pages = {}
        pid = str(uuid.uuid4())
        page = {"id": pid, "slugId": uuid.uuid4().hex[:10], "title": title, "parentPageId": parent,
                "spaceId": "space-1", "content": self.render(content)}
        self.pages[pid] = page
        return page

    @staticmethod
    def render(md: str) -> str:
        return "\n".join(("- " + line[2:]) if line.startswith("* ") else line for line in md.strip().split("\n"))

    def find(self, ref: str) -> dict | None:
        return self.pages.get(ref) or next((p for p in self.pages.values() if p["slugId"] == ref), None)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        assert request.url.host == "docs.example.com" and request.method == "POST"
        if "authToken=good" not in request.headers.get("cookie", ""):
            return httpx.Response(401, json={"message": "Unauthorized", "statusCode": 401})
        body = json.loads(request.content or b"{}")
        ok = lambda data: httpx.Response(200, json={"data": data, "success": True, "status": 200})  # noqa: E731
        path = request.url.path
        if path == "/api/users/me":
            return ok({"user": {"id": "u1", "name": "Ada", "email": "ada@example.com"}, "workspace": {}})
        if path == "/api/pages/info":
            page = self.find(body["pageId"])
            if not page:
                return httpx.Response(404, json={"message": "Page not found"})
            out = {**page, "space": {"id": "space-1", "slug": "team"}}
            if body.get("format") != "markdown":
                out["content"] = {"type": "doc", "content": []}
            return ok(out)
        if path == "/api/pages/create":
            assert body["format"] == "markdown" and body["parentPageId"] in self.pages
            return ok(self._new(body["title"], body["parentPageId"], body["content"]))
        if path == "/api/pages/update":
            page = self.find(body["pageId"])
            assert body["format"] == "markdown" and body["operation"] == "replace"
            page.update(title=body["title"], content=self.render(body["content"]))
            return ok(page)
        return httpx.Response(404)

    def children(self) -> list[dict]:
        return [p for p in self.pages.values() if p["parentPageId"] == self.root["id"]]


@pytest.fixture
def docmost(monkeypatch):
    d = FakeDocmost()
    monkeypatch.setattr(dm, "TRANSPORT", httpx.MockTransport(d))
    dm.set_site(SITE)
    dm.save_session({"url": SITE, "cookies": [{"name": "authToken", "value": "good"}], "user": {"name": "Ada"}})
    return d


def as_human(client):
    assert client.get("/api/session").status_code == 200


def link(d: FakeDocmost, page: dict) -> str:
    return f"{SITE}/s/team/p/team-notes-{page['slugId']}"


def test_site_addresses_and_page_links():
    assert dm.normalize("docs.example.com") == SITE
    assert dm.normalize("https://docs.example.com/s/team/p/notes-AbCdEf1234") == SITE        # a page link pasted
    assert dm.normalize("http://192.168.1.5:3000") == "http://192.168.1.5:3000"
    for bad in ("http://docs.example.com", "ftp://docs.example.com", "https://user:pw@docs.example.com", ""):
        with pytest.raises(ValueError):
            dm.normalize(bad)
    dm.set_site(SITE)
    assert dm.page_ref(f"{SITE}/s/team/p/my-page-AbCdEf1234") == "AbCdEf1234"
    assert dm.page_ref("AbCdEf1234") == "AbCdEf1234"
    with pytest.raises(ValueError):
        dm.page_ref("https://elsewhere.example/s/team/p/my-page-AbCdEf1234")
    with pytest.raises(ValueError):
        dm.page_ref(f"{SITE}/settings/account")


def test_the_sign_in_is_private_and_belongs_to_one_site():
    dm.set_site(SITE)
    dm.save_session({"url": SITE, "cookies": [{"name": "authToken", "value": "t"}]})
    path = vault.path(*dm.SESSION)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert dm.session()
    dm.set_site("https://other.example.com")                 # another site: the old sign-in is forgotten
    assert dm.session() is None and not path.exists()


def _window_that_signs_in(seen: list):
    def fake_run(cmd, **kw):
        seen.append(cmd)
        out = cmd[cmd.index("--out") + 1]
        with open(out, "w") as f:
            json.dump({"url": SITE, "cookies": [{"name": "authToken", "value": "x"}], "user": {"name": "Ada"}}, f)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return fake_run


def test_the_playwright_window_hands_back_cookies_or_says_why(monkeypatch):
    dm.set_site(SITE)
    monkeypatch.setattr(session, "helper", lambda: "playwright")
    seen: list = []
    monkeypatch.setattr(subprocess, "run", _window_that_signs_in(seen))
    assert session._run_helper(headless=False, timeout=5) == (0, "signed in as Ada")
    assert seen[0][1:3] == ["-m", "research_deck.docmost.login"] and "--profile" in seen[0] and "--headless" not in seen[0]
    assert dm.session()["cookies"][0]["value"] == "x"
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 5, "", "missing"))
    code, msg = session._run_helper(headless=True, timeout=5)
    assert code == 5 and "install it" in msg


def test_on_a_mac_the_native_window_is_built_once_and_used(monkeypatch, tmp_path):
    dm.set_site(SITE)
    monkeypatch.setattr(session, "helper", lambda: "native")
    monkeypatch.setattr(session, "native_binary", lambda: tmp_path / "bin" / "docmost-login-abc")
    builds: list = []

    def fake_run(cmd, **kw):
        if cmd[:2] == ["xcrun", "swiftc"]:
            builds.append(cmd)
            out = cmd[cmd.index("-o") + 1]
            open(out, "w").write("binary")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return _window_that_signs_in(seen)(cmd, **kw)

    seen: list = []
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert session._run_helper(headless=False, timeout=5)[0] == 0
    assert session._run_helper(headless=True, timeout=5)[0] == 0
    assert len(builds) == 1 and builds[0][-1] == str(session.NATIVE_SOURCE)           # built once, then reused
    assert all(c[0] == str(tmp_path / "bin" / "docmost-login-abc") and "--profile" not in c for c in seen)
    assert "--headless" in seen[1] and os.access(tmp_path / "bin" / "docmost-login-abc", os.X_OK)
    # a build that fails says what to install, and nothing half-built is kept
    monkeypatch.setattr(session, "native_binary", lambda: tmp_path / "bin" / "docmost-login-def")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "error: no SDK"))
    monkeypatch.setattr(session, "playwright_installed", lambda: False)
    code, msg = session._run_helper(headless=False, timeout=5)
    assert code == 7 and "xcode-select --install" in msg and not list((tmp_path / "bin").glob("*def*"))


def test_without_any_window_the_reason_is_given(monkeypatch):
    dm.set_site(SITE)
    monkeypatch.setattr(session, "native_possible", lambda: False)
    monkeypatch.setattr(session, "playwright_installed", lambda: False)
    assert session.status()["helper"] is None
    code, msg = session._run_helper(headless=False, timeout=5)
    assert code == 2 and "xcode-select" in msg and "research-deck[docmost]" in msg


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("xcrun"), reason="the native window is macOS only")
def test_the_native_window_source_compiles():
    r = subprocess.run(["xcrun", "swiftc", "-typecheck", str(session.NATIVE_SOURCE)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr


def test_binding_a_page_pushes_the_notes_as_child_pages(client, project, docmost):
    pid, root = project
    (root / "notes").mkdir()
    (root / "notes" / "idea.md").write_text("# My idea\n\nWe cache experts.\n\n* one\n* two\n")
    (root / "notes" / "reading-list.md").write_text("Papers to read.\n")
    (root / "notes" / ".drafts").mkdir()
    (root / "notes" / ".drafts" / "hidden.md").write_text("not synced")
    assert client.put(f"/api/projects/{pid}/docmost", json={"link": link(docmost, docmost.root)}).status_code == 403
    as_human(client)
    r = client.put(f"/api/projects/{pid}/docmost", json={"link": link(docmost, docmost.root)})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["binding"]["page"] == docmost.root["id"] and st["binding"]["title"] == "Team notes"
    states = {n["path"]: n["state"] for n in st["notes"]}
    assert states == {"notes/idea.md": "synced", "notes/reading-list.md": "synced"}
    kids = {p["title"]: p for p in docmost.children()}
    assert set(kids) == {"My idea", "reading list"}
    assert kids["My idea"]["content"] == "We cache experts.\n\n- one\n- two"           # the heading became the title
    assert st["notes"][0]["url"].startswith(f"{SITE}/s/team/p/")
    # unchanged notes are not pushed again; a changed one is
    n_calls = len(docmost.calls)
    sync.sync(pid)
    assert len(docmost.calls) == n_calls
    (root / "notes" / "idea.md").write_text("# My idea\n\nWe cache and prefetch experts.\n")
    st = client.post(f"/api/projects/{pid}/docmost/sync").json()
    assert kids["My idea"]["content"] == "We cache and prefetch experts." and st["last"]["pushed"] == 1


def test_an_edit_in_docmost_stops_the_push_until_it_is_reviewed(client, project, docmost):
    pid, root = project
    as_human(client)
    (root / "notes").mkdir()
    note = root / "notes" / "idea.md"
    note.write_text("# My idea\n\nFirst version.\n")
    client.put(f"/api/projects/{pid}/docmost", json={"link": link(docmost, docmost.root)})
    page = docmost.children()[0]
    page["content"] = "First version.\n\nA colleague's comment."              # edited in Docmost
    note.write_text("# My idea\n\nSecond version.\n")
    st = client.post(f"/api/projects/{pid}/docmost/sync").json()
    assert st["notes"][0]["state"] == "conflict" and st["last"]["conflicts"] == 1
    assert page["content"] == "First version.\n\nA colleague's comment."      # not overwritten
    view = client.get(f"/api/projects/{pid}/docmost/conflict", params={"path": "notes/idea.md"}).json()
    assert {"kind": "+", "text": "A colleague's comment."} in view["diff"] and "Second version." in view["note"]
    # a later sync leaves it alone until the researcher decides
    sync.sync(pid)
    assert page["content"] == "First version.\n\nA colleague's comment."
    # take Docmost's version into the note, then edit and push normally
    st = client.post(f"/api/projects/{pid}/docmost/resolve", json={"path": "notes/idea.md", "action": "take"}).json()
    assert st["notes"][0]["state"] == "synced"
    assert note.read_text() == "# My idea\n\nFirst version.\n\nA colleague's comment.\n"
    note.write_text("# My idea\n\nFirst version.\n\nA colleague's comment.\n\nMy reply.\n")
    sync.sync(pid)
    assert page["content"].endswith("My reply.")
    # another edit there; this time the researcher merges by hand and pushes
    page["content"] = "Rewritten in Docmost."
    note.write_text("# My idea\n\nMerged by hand.\n")
    assert sync.sync(pid)["notes"][0]["state"] == "conflict"
    st = client.post(f"/api/projects/{pid}/docmost/resolve", json={"path": "notes/idea.md", "action": "push"}).json()
    assert st["notes"][0]["state"] == "synced" and page["content"] == "Merged by hand."


def test_deleted_pages_and_notes_are_never_recreated_or_deleted_silently(client, project, docmost):
    pid, root = project
    as_human(client)
    (root / "notes").mkdir()
    (root / "notes" / "a.md").write_text("A\n")
    (root / "notes" / "b.md").write_text("B\n")
    client.put(f"/api/projects/{pid}/docmost", json={"link": link(docmost, docmost.root)})
    pages = {p["title"]: p for p in docmost.children()}
    del docmost.pages[pages["a"]["id"]]                       # deleted in Docmost
    (root / "notes" / "a.md").write_text("A, edited\n")
    (root / "notes" / "b.md").unlink()                        # deleted here
    st = {n["path"]: n["state"] for n in sync.sync(pid)["notes"]}
    assert st == {"notes/a.md": "missing", "notes/b.md": "removed"} and pages["b"]["id"] in docmost.pages
    client.post(f"/api/projects/{pid}/docmost/resolve", json={"path": "notes/a.md", "action": "recreate"})
    assert any(p["title"] == "a" and p["content"] == "A, edited" for p in docmost.children())


def test_a_lapsed_sign_in_is_reported(client, project, docmost):
    pid, root = project
    as_human(client)
    (root / "notes").mkdir()
    (root / "notes" / "a.md").write_text("A\n")
    dm.save_session({"url": SITE, "cookies": [{"name": "authToken", "value": "expired"}]})
    r = client.put(f"/api/projects/{pid}/docmost", json={"link": link(docmost, docmost.root)})
    assert r.status_code == 401 and r.json()["detail"]["sign_in"]
    assert client.get("/api/settings/docmost").json()["signed_in"]          # the scan, not a click, forgets it


def test_settings_routes_are_the_researchers(client):
    assert client.patch("/api/settings/docmost", json={"url": SITE}).status_code == 403
    as_human(client)
    assert client.patch("/api/settings/docmost", json={"url": "http://docs.example.com"}).status_code == 400
    s = client.patch("/api/settings/docmost", json={"url": "docs.example.com"}).json()
    assert s["url"] == SITE and not s["signed_in"] and "cookies" not in json.dumps(s)
