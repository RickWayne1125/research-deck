"""The Zotero literature backend: settings, the local authorization, the client against a made-up Zotero
(httpx.MockTransport), references.bib exported without losing the researcher's own entries, and the whole survey
storing its papers in a collection instead of the project folder."""
from __future__ import annotations

import os
import stat

import httpx
import pytest

from research_deck import vault
from research_deck.literature import backend, zotero
from research_deck.survey import fetch, sources
from test_survey import PDF, Scholar, as_human, wait_survey


class FakeZotero:
    """One Zotero library, reachable as the desktop app (127.0.0.1:23119/api/users/0) or as zotero.org (users/42)."""

    def __init__(self):
        self.collections: dict[str, dict] = {}
        self.items: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}
        self.uploads: dict[str, str] = {}
        self.n = 0
        self.local_key = "LOCALKEY"
        self.web_key = "WEBKEY"
        self.requests: list[httpx.Request] = []

    def _key(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n:07d}"[:8].upper()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url, path, method = request.url, request.url.path, request.method
        local = url.host == "127.0.0.1"
        headers = {"Zotero-Server-ID": "srv1"} if local else {}
        if local:
            assert request.headers["zotero-allowed-request"] == "1"
            path = path.removeprefix("/api")
        if path == "/local/authorize":
            return httpx.Response(200, json={"key": self.local_key, "remember": True}, headers=headers)
        if path == "/keys/current":
            if request.headers.get("zotero-api-key") != self.web_key:
                return httpx.Response(403)
            return httpx.Response(200, json={"userID": 42, "username": "ada", "access": {"user": {"library": True, "write": True}}})
        if path.startswith("/local/uploads/") or url.host == "uploads.example":
            token = path.rsplit("/", 1)[-1]
            item = self.uploads.pop(token)
            body = request.content
            assert body.startswith(b"PRE") and body.endswith(b"SUF") and "zotero-api-key" not in request.headers
            self.files[item] = body[3:-3]
            return httpx.Response(201)
        prefix = "/users/0" if local else "/users/42"
        assert path.startswith(prefix), path
        path = path.removeprefix(prefix)
        if method != "GET":
            want = self.local_key if local else self.web_key
            if request.headers.get("zotero-api-key") != want:
                return httpx.Response(401, headers=headers)
            if local and request.headers.get("zotero-server-id") != "srv1":
                return httpx.Response(428, headers=headers)
        if path == "/collections" and method == "GET":
            body = [{"key": k, "data": c} for k, c in self.collections.items()]
            return httpx.Response(200, json=body, headers={**headers, "Total-Results": str(len(body)), "Last-Modified-Version": "7"})
        if path == "/collections" and method == "POST":
            ok = {}
            for i, c in enumerate(httpx.Response(200, content=request.content).json()):
                k = self._key("C")
                self.collections[k] = {"key": k, **c}
                ok[str(i)] = {"key": k}
            return httpx.Response(200, json={"successful": ok, "success": {}, "failed": {}}, headers=headers)
        if path == "/items" and method == "POST":
            ok, failed = {}, {}
            for i, it in enumerate(httpx.Response(200, content=request.content).json()):
                if it.get("title") == "Refused":
                    failed[str(i)] = {"code": 400, "message": "made-up refusal"}
                    continue
                k = self._key("I")
                self.items[k] = {"key": k, "dateAdded": f"2026-01-01T00:00:{self.n:02d}Z", **it}
                ok[str(i)] = {"key": k}
            return httpx.Response(200, json={"successful": ok, "success": {}, "failed": failed}, headers=headers)
        if path.startswith("/items/") and path.endswith("/file"):
            item = path.split("/")[2]
            assert request.headers.get("if-none-match") == "*"
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if "upload" in form:
                return httpx.Response(204, headers=headers)
            token = f"up{len(self.uploads) + len(self.files)}"
            self.uploads[token] = item
            target = f"/api/local/uploads/{token}" if local else f"https://uploads.example/{token}"
            return httpx.Response(200, json={"url": target, "contentType": "application/pdf", "prefix": "PRE",
                                             "suffix": "SUF", "uploadKey": token}, headers=headers)
        if path.startswith("/collections/") and path.endswith("/items/top"):
            coll = path.split("/")[2]
            body = [{"key": k, "data": it} for k, it in self.items.items()
                    if coll in (it.get("collections") or []) and it.get("itemType") != "attachment"]
            return httpx.Response(200, json=body, headers={**headers, "Total-Results": str(len(body)), "Last-Modified-Version": "9"})
        return httpx.Response(404, headers=headers)


@pytest.fixture
def fake_zotero(monkeypatch):
    z = FakeZotero()
    monkeypatch.setattr(zotero, "TRANSPORT", httpx.MockTransport(z))
    return z


@pytest.fixture
def scholar(monkeypatch):
    s = Scholar()
    monkeypatch.setattr(fetch, "_transport", httpx.MockTransport(s))
    monkeypatch.setattr(fetch, "_public", lambda host: host not in ("127.0.0.1", "localhost"))
    monkeypatch.setattr(fetch, "sleep", lambda s: None)
    monkeypatch.setattr(sources, "_last", {})
    return s


def test_settings_are_checked_and_only_the_researcher_changes_them(client):
    assert client.get("/api/settings/zotero").json()["mode"] == "local"
    assert client.patch("/api/settings/zotero", json={"mode": "web"}).status_code == 403      # no human cookie yet
    as_human(client)
    assert client.patch("/api/settings/zotero", json={"library": "users/abc"}).status_code == 400
    assert client.patch("/api/settings/zotero", json={"credential": "my key"}).status_code == 400
    s = client.patch("/api/settings/zotero", json={"mode": "web", "library": "users/42", "credential": "env:RD_ZKEY"}).json()
    assert (s["mode"], s["library"], s["credential"]) == ("web", "users/42", "env:RD_ZKEY")
    assert "WEBKEY" not in client.get("/api/settings/zotero").text


def test_the_app_grants_a_key_that_is_kept_privately(fake_zotero):
    assert zotero.authorize_local() == {"remember": True}
    path = vault.path(zotero.SECRET)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert zotero.status()["local_key"] and zotero.client().key == "LOCALKEY"


def test_web_mode_reads_its_key_from_the_environment_or_keychain(client, fake_zotero, monkeypatch):
    as_human(client)
    client.patch("/api/settings/zotero", json={"mode": "web", "library": "users/42", "credential": "env:RD_ZKEY"})
    monkeypatch.setenv("RD_ZKEY", "WEBKEY")
    s = client.post("/api/settings/zotero/check").json()
    assert s["check"]["ok"] and s["check"]["user"] == {"id": 42, "name": "ada"} and s["check"]["write"]
    monkeypatch.setenv("RD_ZKEY", "WRONG")
    s = client.post("/api/settings/zotero/check").json()
    assert not s["check"]["ok"] and "write" in s["check"]["message"]


def test_citation_keys_and_entries_from_zotero_items():
    items = [
        {"key": "A", "itemType": "journalArticle", "title": "Pinned Paper", "dateAdded": "2026-01-02",
         "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}], "date": "2021-05",
         "publicationTitle": "Journal of Things", "extra": "Citation Key: lovelace2021pinned\nother: x"},
        {"key": "B", "itemType": "preprint", "title": "An Unpinned Preprint", "dateAdded": "2026-01-01",
         "creators": [{"creatorType": "author", "name": "Grace Hopper"}], "date": "2024",
         "archiveID": "arXiv:2402.00002", "repository": "arXiv", "url": "https://arxiv.org/abs/2402.00002"},
        {"key": "C", "itemType": "thesis", "title": "A Thesis", "university": "Some University", "date": "2019",
         "dateAdded": "2026-01-03",
         "creators": [{"creatorType": "author", "firstName": "Alan", "lastName": "Turing"}]},
        {"key": "D", "itemType": "note", "note": "not a reference"},
    ]
    entries, keys = backend.render(items)
    assert keys == ["hopper2024unpinned", "lovelace2021pinned", "turing2019thesis"]          # oldest item first
    text = "".join(entries)
    assert "% zotero: B\n@misc{hopper2024unpinned," in text and "eprint = {2402.00002}" in text
    assert "@article{lovelace2021pinned," in text and "journal = {Journal of Things}" in text
    assert "@phdthesis{turing2019thesis," in text and "school = {Some University}" in text


def test_the_export_rewrites_its_block_and_keeps_the_researchers_entries():
    old = ("@book{mine2020own,\n  title = {{My Own Entry}}\n}\n\n"
           "@article{lovelace2021pinned,\n  title = {{Typed by hand}},\n  note = {x}\n}\n")
    block = f"{backend.BEGIN} c: exported\n\n% zotero: A\n@article{{lovelace2021pinned,\n  title = {{From Zotero}}\n}}\n{backend.END}\n"
    once = backend.merge_into(old, block, ["lovelace2021pinned"])
    assert once.startswith(backend.BEGIN) and "@book{mine2020own," in once
    assert "% @article{lovelace2021pinned," in once and "% lovelace2021pinned: replaced" in once   # commented, not deleted
    assert once.count("\n@article{lovelace2021pinned,") == 1
    block2 = block.replace("From Zotero", "Edited in Zotero")
    twice = backend.merge_into(once, block2, ["lovelace2021pinned"])
    assert "Edited in Zotero" in twice and "From Zotero" not in twice and twice.count(backend.BEGIN) == 1
    assert "@book{mine2020own," in twice


def test_the_survey_keeps_papers_in_zotero_and_only_references_bib_in_the_project(client, project, scholar, fake_zotero):
    pid, root = project
    as_human(client)
    r = client.put(f"/api/projects/{pid}/literature", json={"backend": "zotero"})
    assert r.status_code == 200 and r.json()["backend"] == "zotero"
    # Zotero not authorized yet: the survey refuses to start rather than lose the papers
    r = client.post(f"/api/projects/{pid}/survey", json={"idea": "Expert prefetching for MoE decoding.", "count": 4})
    assert r.status_code == 409 and "authorize" in r.json()["detail"]
    zotero.authorize_local()
    r = client.post(f"/api/projects/{pid}/survey", json={"idea": "Expert prefetching for MoE decoding.", "count": 4})
    assert r.status_code == 200, r.text
    s = wait_survey(client, pid)
    assert s["status"] == "done", s
    lit = client.get(f"/api/projects/{pid}/literature").json()
    coll = lit["collection"]
    assert coll and fake_zotero.collections[coll]["name"] == "Test Project"
    papers = {p["title"]: p for p in s["papers"]}
    items = {k: it for k, it in fake_zotero.items.items() if it["itemType"] != "attachment"}
    assert len(items) == 4 and all(coll in it["collections"] for it in items.values())
    assert all(it["extra"].startswith("Citation Key: ") for it in items.values())
    fast = papers["Fast Inference of Mixture-of-Experts Models with Offloading"]
    assert fast["status"] == "done" and fast["file"] is None and fast["zotero_pdf"]
    assert fake_zotero.files[fast["zotero_pdf"]] == PDF                       # the PDF went to Zotero as is
    assert fake_zotero.items[fast["zotero_pdf"]]["parentItem"] == fast["zotero"]
    # the project folder: references.bib only (no PDFs, no index.md)
    assert sorted(p.name for p in (root / "papers").iterdir()) == ["references.bib"]
    bibtext = (root / "papers" / "references.bib").read_text()
    assert bibtext.startswith(backend.BEGIN) and all(f"{{{p['key']}," in bibtext for p in s["papers"])
    survey_md = (root / "notes" / "survey.md").read_text()
    assert f"[PDF](zotero://open-pdf/library/items/{fast['zotero_pdf']})" in survey_md
    node = client.get(f"/api/projects/{pid}/dag/nodes/ref.{fast['key']}").json()
    assert node.get("node", node)["facets"]["citation"]["value"]["zotero"] == fast["zotero"]
    assert lit["exported"]["items"] == 4 and lit["exported"]["path"] == "papers/references.bib"


def test_a_paper_zotero_refuses_is_recorded_and_the_rest_go_on(project, fake_zotero):
    pid, _ = project
    zotero.authorize_local()
    c = zotero.client()
    made = c.create_items([zotero.item_from_paper({"title": "Refused"}, "x2020refused", None),
                           zotero.item_from_paper({"title": "Kept", "authors": ["A B"], "year": 2020}, "b2020kept", None)])
    assert made[0] == (None, "made-up refusal") and made[1][0]


def test_agents_cannot_change_the_backend_or_reach_zotero(client, project):
    pid, _ = project
    assert client.put(f"/api/projects/{pid}/literature", json={"backend": "zotero"}).status_code == 403
    assert client.get("/api/zotero/collections").status_code == 403
    assert client.get(f"/api/projects/{pid}/literature").json()["backend"] == "files"
