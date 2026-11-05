"""The early survey and new projects from an idea: parsing, merging, BibTeX, the PDF download's safety checks and the
whole pipeline against made-up scholarly APIs (httpx.MockTransport) with the fake agent."""
from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from research_deck.start import create as start_create
from research_deck.start import settings as start_settings
from research_deck.survey import bib, fetch, job, prompts, sources

PDF = b"%PDF-1.7\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <published>2024-01-02T00:00:00Z</published>
    <title>Fast Inference of Mixture-of-Experts Models with Offloading</title>
    <summary>We offload experts to host memory and cache the hot ones on the GPU. Decoding is 2x faster.</summary>
    <author><name>Ada Lovelace</name></author><author><name>Alan Turing</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v2"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00002v1</id>
    <published>2024-02-03T00:00:00Z</published>
    <title>Expert Prefetching from the Request Queue</title>
    <summary>Requests waiting in the queue tell which experts the next layers need. We prefetch them.</summary>
    <author><name>Grace Hopper</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2402.00002v1"/>
  </entry>
</feed>"""

S2_JSON = {"data": [
    {"title": "Fast inference of mixture-of-experts models with offloading", "abstract": "Offloading experts.",
     "year": 2024, "venue": "MLSys", "authors": [{"name": "Ada Lovelace"}], "citationCount": 120,
     "externalIds": {"DOI": "10.1/fast"}, "openAccessPdf": None, "url": "https://www.semanticscholar.org/p/1"},
    {"title": "Paywalled Expert Caching", "abstract": "A cache of experts behind a paywall.", "year": 2023,
     "venue": "Proceedings of the Symposium on Things", "authors": [{"name": "Edsger Dijkstra"}], "citationCount": 40,
     "externalIds": {"DOI": "10.1/paywall"}, "openAccessPdf": None, "url": "https://publisher.example/paywall"},
    {"title": "A Redirect to Nowhere", "abstract": "Its PDF link redirects to a private address.", "year": 2022,
     "venue": "", "authors": [{"name": "Barbara Liskov"}], "citationCount": 3, "externalIds": {},
     "openAccessPdf": {"url": "https://files.example/trap.pdf"}, "url": "https://www.semanticscholar.org/p/3"},
]}

OPENALEX_JSON = {"results": [
    {"display_name": "Expert prefetching from the request queue", "publication_year": 2024,
     "authorships": [{"author": {"display_name": "Grace Hopper"}}], "cited_by_count": 9,
     "abstract_inverted_index": {"Requests": [0], "tell": [1], "experts": [2]},
     "doi": "https://doi.org/10.1/queue", "ids": {}, "primary_location": {"source": {"display_name": "arXiv"}},
     "best_oa_location": {"pdf_url": "https://arxiv.org/pdf/2402.00002v1"}, "id": "https://openalex.org/W1"},
    {"display_name": "An HTML page pretending to be a PDF", "publication_year": 2021,
     "authorships": [{"author": {"display_name": "Donald Knuth"}}], "cited_by_count": 1,
     "abstract_inverted_index": {"Not": [0], "a": [1], "PDF": [2]}, "doi": None, "ids": {},
     "primary_location": {"source": {"display_name": "Some Journal"}},
     "best_oa_location": {"pdf_url": "https://files.example/page.pdf"}, "id": "https://openalex.org/W2"},
]}


class Scholar:
    """The scholarly APIs and file hosts the survey talks to, made up; records every request."""

    def __init__(self):
        self.calls: list[str] = []
        self.s2_limited = 1                 # the first Semantic Scholar call is rate-limited (429)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        assert request.headers["user-agent"].startswith("research-deck/")
        assert "@" not in request.headers["user-agent"]
        host, path = request.url.host, request.url.path
        if host == "export.arxiv.org":
            return httpx.Response(200, text=ATOM)
        if host == "api.semanticscholar.org":
            if self.s2_limited:
                self.s2_limited -= 1
                return httpx.Response(429, headers={"retry-after": "1"})
            return httpx.Response(200, json=S2_JSON)
        if host == "api.openalex.org":
            return httpx.Response(200, json=OPENALEX_JSON)
        if host == "arxiv.org" and path.startswith("/pdf/"):
            return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
        if host == "files.example" and path == "/trap.pdf":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8765/api/projects"})
        if host == "files.example" and path == "/page.pdf":
            return httpx.Response(200, text="<html>not a pdf</html>")
        return httpx.Response(404)


@pytest.fixture
def scholar(monkeypatch):
    s = Scholar()
    monkeypatch.setattr(fetch, "_transport", httpx.MockTransport(s))
    monkeypatch.setattr(fetch, "_public", lambda host: host not in ("127.0.0.1", "localhost"))
    monkeypatch.setattr(fetch, "sleep", lambda s: None)
    monkeypatch.setattr(sources, "_last", {})
    return s


def as_human(client):
    assert client.get("/api/session").status_code == 200


def wait_survey(client, pid: str, sid: str | None = None, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get(f"/api/projects/{pid}/survey").json()
        if s and s["status"] != "running" and (sid is None or s["id"] == sid):
            return s
        time.sleep(0.05)
    raise AssertionError("the survey did not finish")


# ---------------------------------------------------------------- pieces

def test_parse_frame_and_select():
    framed = prompts.parse_frame('Sure.\n```json\n{"title": "T", "summary": "S", "queries": ["a b", " ", "c"],'
                                 ' "problem": {"statement": "x", "metric": "tok/s"}}\n```')
    assert framed["queries"] == ["a b", "c"] and framed["problem"]["metric"] == "tok/s"
    assert prompts.parse_frame("no json here") is None
    assert prompts.parse_frame('```json\n{"queries": []}\n```') is None
    answer = ('```json\n{"selected": [{"i": 2, "role": "competitor", "takeaway": "t", "delta": "d"}, {"i": 2},'
              ' {"i": 9}, {"i": 1, "role": "wizard"}]}\n```\n\n```markdown\n## Existing work\nSee [2].\n```')
    picked, survey = prompts.parse_select(answer, 3)
    assert [(p["i"], p["role"]) for p in picked] == [(2, "competitor"), (1, "related")]   # duplicates, out of range, bad role
    assert survey.startswith("## Existing work")
    assert prompts.language("显存放不下全部专家时怎么办") == "zh" and prompts.language("experts do not fit") == "en"


def test_merge_dedupes_across_sources_and_ranks():
    a = {"title": "Fast Inference of MoE", "arxiv": "2401.00001", "doi": None, "abstract": "", "authors": ["A B"],
         "pdf_url": "https://arxiv.org/pdf/2401.00001", "citations": None}
    b = {"title": "Fast inference of MoE.", "arxiv": None, "doi": "10.1/x", "abstract": "abs", "authors": [],
         "pdf_url": None, "citations": 50, "venue": "MLSys"}
    c = {"title": "Something else", "arxiv": None, "doi": None, "abstract": "", "authors": [], "pdf_url": None, "citations": None}
    merged = sources.merge([("arxiv", 0, a), ("semantic_scholar", 3, b), ("openalex", 0, c)])
    assert len(merged) == 2
    top = merged[0]
    assert top["title"] == "Fast Inference of MoE" and top["sources"] == ["arxiv", "semantic_scholar"]
    assert top["abstract"] == "abs" and top["doi"] == "10.1/x" and top["citations"] == 50 and top["venue"] == "MLSys"


def test_query_words_drop_stop_words_and_repeats():
    assert sources.query_words("mixture of experts offloading expert prefetching") == \
        ["mixture", "experts", "offloading", "prefetching"]
    assert sources.query_words("the of and") == []


def test_arxiv_falls_back_to_any_word_when_all_words_find_little(scholar, monkeypatch):
    seen = []
    real = fetch.get_text

    def spy(url, params=None):
        seen.append(params["search_query"])
        return real(url, params) if " OR " in params["search_query"] else ATOM.split("<entry>")[0] + "</feed>"
    monkeypatch.setattr(fetch, "get_text", spy)
    found = sources.arxiv("expert prefetching queue", 12)
    assert seen == ["all:expert AND all:prefetching AND all:queue", "all:expert OR all:prefetching OR all:queue"]
    assert len(found) == 2


def test_bibkeys_and_entries():
    taken: set[str] = set()
    p = {"title": "The Mixture of Experts", "authors": ["Zoë Ångström", "B C"], "year": 2024, "venue": "arXiv",
         "arxiv": "2401.00001", "doi": None, "url": "https://arxiv.org/abs/2401.00001"}
    assert bib.bibkey(p, taken) == "angstrom2024mixture"
    assert bib.bibkey(p, taken) == "angstrom2024mixtureb"
    e = bib.entry(p, "angstrom2024mixture")
    assert e.startswith("@misc{angstrom2024mixture,") and "eprint = {2401.00001}" in e
    assert bib.entry({**p, "arxiv": None, "venue": "Proceedings of OSDI"}, "k").startswith("@inproceedings{k,")
    assert "{The \\{Bad\\} Title}" in bib.entry({"title": "The {Bad} Title"}, "k")


def test_pdf_download_checks(tmp_path, scholar):
    size = fetch.fetch_pdf("https://arxiv.org/pdf/2401.00001", tmp_path / "a.pdf")
    assert size == len(PDF) and (tmp_path / "a.pdf").read_bytes() == PDF
    with pytest.raises(fetch.FetchError, match="not a public address"):
        fetch.fetch_pdf("https://files.example/trap.pdf", tmp_path / "b.pdf")
    with pytest.raises(fetch.FetchError, match="not a PDF"):
        fetch.fetch_pdf("https://files.example/page.pdf", tmp_path / "c.pdf")
    with pytest.raises(fetch.FetchError, match="http"):
        fetch.fetch_pdf("file:///etc/passwd", tmp_path / "d.pdf")
    with pytest.raises(fetch.FetchError, match="larger"):
        fetch.fetch_pdf("https://arxiv.org/pdf/2401.00001", tmp_path / "e.pdf", max_bytes=10)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]          # no partial files left behind
    assert fetch.is_public_host("127.0.0.1") is False and fetch.is_public_host("10.1.2.3") is False


def test_folder_names_and_default_dirs():
    assert start_create.folder_name("MoE 专家预取") == "moe-专家预取"
    assert start_create.folder_name("  ../Weird: name?  ") == "weird-name"
    assert start_create.folder_name("!!!") == "project"
    assert start_settings.default_dir("darwin") == "~/Research"
    assert start_settings.default_dir("linux") == "~/research"
    assert start_settings.default_dir("win32") == "%USERPROFILE%\\Research"


def test_settings_roundtrip(client, tmp_path):
    as_human(client)
    s = client.get("/api/settings/new-projects").json()
    assert s["dir"] == start_settings.default_dir() and s["survey"]["count"] == 15 and s["stage_mode"] == "free"
    r = client.patch("/api/settings/new-projects", json={"dir": str(tmp_path / "R"), "survey": {"count": 30,
                     "sources": ["arxiv"]}, "stage_mode": "strict"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["dir"] == str(tmp_path / "R") and s["survey"]["count"] == 30 and s["survey"]["sources"] == ["arxiv"]
    assert s["stage_mode"] == "strict"
    assert client.patch("/api/settings/new-projects", json={"survey": {"papers_dir": "../out"}}).status_code == 400
    assert client.patch("/api/settings/new-projects", json={"dir": None}).json()["dir"] == start_settings.default_dir()
    # an agent (no cookie) may not change them
    from fastapi.testclient import TestClient
    from research_deck.app import create_app
    with TestClient(create_app(), headers={"X-RD-Request": "1"}) as agent:
        assert agent.patch("/api/settings/new-projects", json={"git_init": False}).status_code == 403


# ---------------------------------------------------------------- the whole flow

def test_new_project_from_idea_runs_the_survey(client, tmp_path, scholar):
    as_human(client)
    client.patch("/api/settings/new-projects", json={"dir": str(tmp_path / "Research")})
    idea = ("MoE 模型在单卡显存放不下全部专家时，解码要频繁把专家从 CPU 内存搬到 GPU。能不能根据请求队列里的 token 提前预取专家？"
            " Goal: Mixtral expert prefetching from the request queue, 2x decoding throughput.")
    r = client.post("/api/projects/new", json={"name": "MoE 专家预取", "idea": idea, "survey": {"count": 4}})
    assert r.status_code == 200, r.text
    out = r.json()
    pid, root = out["project"]["id"], tmp_path / "Research" / "moe-专家预取"
    assert out["root"] == str(root) and out["created"] and out["idea_file"] == "notes/idea.md"
    assert (root / ".git").is_dir() and "papers/*.pdf" in (root / ".gitignore").read_text()
    assert idea in (root / "notes" / "idea.md").read_text()

    s = wait_survey(client, pid)
    assert s["status"] == "done", s
    assert all(v == "done" for v in s["steps"].values()), s["steps"]
    assert s["search"]["sources"]["semantic_scholar"]["found"] > 0         # the 429 was retried
    assert s["lang"] == "zh" and s["queries"]
    papers = {p["title"]: p for p in s["papers"]}
    assert len(papers) == 4
    # the same paper from arXiv and Semantic Scholar is one paper, downloaded from arXiv
    fast = papers["Fast Inference of Mixture-of-Experts Models with Offloading"]
    assert fast["status"] == "done" and (root / fast["file"]).read_bytes() == PDF
    assert papers["Expert Prefetching from the Request Queue"]["status"] == "done"
    assert papers["Paywalled Expert Caching"]["status"] == "link"                  # no open-access PDF: link + BibTeX
    trap = papers["A Redirect to Nowhere"]                                         # its PDF link redirects to 127.0.0.1
    assert trap["status"] == "failed" and "not a public address" in trap["error"]
    assert not (root / "papers" / f"{trap['key']}.pdf").exists()
    assert not any(c.startswith("http://127.0.0.1") for c in scholar.calls)      # the redirect was never followed
    assert sorted(p.name for p in (root / "papers").iterdir()) == sorted(
        [f"{fast['key']}.pdf", f"{papers['Expert Prefetching from the Request Queue']['key']}.pdf", "index.md", "references.bib"])

    bibtext = (root / "papers" / "references.bib").read_text()
    assert all(f"{{{p['key']}," in bibtext for p in s["papers"])
    index = (root / "papers" / "index.md").read_text()
    survey_md = (root / "notes" / "survey.md").read_text()
    assert "# 前期调研" in survey_md and "没有运行任何实验" in survey_md and "@" + s["papers"][0]["key"] in survey_md
    assert all(p["key"] in index for p in s["papers"])

    # the map: a proposed problem and one proposed reference per paper, by the survey; nothing else
    g = client.get(f"/api/projects/{pid}/dag/graph").json()
    nodes = {n["id"]: n for n in g["nodes"]}
    assert set(nodes) == set(s["nodes"])
    probs = [n for n in nodes.values() if n["kind"] == "problem"]
    refs = [n for n in nodes.values() if n["kind"] == "reference"]
    assert len(probs) == 1 and len(refs) == 4
    assert all(n["status"] == "proposed" for n in nodes.values())
    assert not any(n["kind"] == "experiment" for n in nodes.values())
    node = client.get(f"/api/projects/{pid}/dag/nodes/ref.{fast['key']}").json()
    facets = node.get("node", node)["facets"]
    assert facets["role"]["value"] in ("competitor", "baseline", "related", "background")
    assert facets["citation"]["value"]["bibkey"] == fast["key"]

    # the conversation says so, and both backends get a note for their next turn
    entries = client.get(f"/api/projects/{pid}/transcript/project").json()
    items = entries.get("entries", entries) if isinstance(entries, dict) else entries
    assert any(e.get("purpose") == "survey" and "前期调研完成" in e.get("text", "") for e in items)
    pending = root / ".research" / "context" / "pending"
    assert all((pending / f"project-{p}.md").read_text().count("early survey") == 1 for p in ("claude", "codex"))

    # a second survey keeps the first one's files and reuses the papers already on the map
    r = client.post(f"/api/projects/{pid}/survey", json={"count": 2})
    assert r.status_code == 200, r.text
    assert r.json()["id"] > s["id"]                                   # ids sort by start, even within one second
    s2 = wait_survey(client, pid, r.json()["id"])
    assert s2["status"] == "done", s2
    assert (root / "notes" / "survey-2.md").exists() and (root / "notes" / "survey.md").read_text() == survey_md
    assert all(p["existing"] for p in s2["papers"]) and s2["nodes"] == []


def test_new_project_in_a_chosen_folder_with_an_upload(client, tmp_path, scholar):
    as_human(client)
    folder = tmp_path / "work" / "mine"
    upload = {"name": "proposal.md", "content_base64": base64.b64encode(
        "# Proposal\nPrefetch experts from the request queue to hide transfers.".encode()).decode()}
    r = client.post("/api/projects/new", json={"name": "Prefetch", "folder": str(folder), "file": upload,
                                               "survey": {"enabled": False}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["root"] == str(folder) and out["survey"] is None and out["upload"] == "notes/proposal.md"
    assert (folder / "notes" / "proposal.md").read_text().startswith("# Proposal")
    assert "Prefetch experts" in (folder / "notes" / "idea.md").read_text()
    assert client.get(f"/api/projects/{out['project']['id']}/survey").json() is None
    # the same folder again: the project is reused and the idea gets a new file
    r = client.post("/api/projects/new", json={"name": "Prefetch", "folder": str(folder), "idea": "Second thought.",
                                               "survey": {"enabled": False}})
    assert r.json()["project"]["id"] == out["project"]["id"] and r.json()["idea_file"] == "notes/idea-2.md"


@pytest.mark.parametrize("body, status", [
    ({"name": "", "idea": "x"}, 400),
    ({"name": "A"}, 400),                                                           # no idea at all
    ({"name": "A", "file": {"name": "a.exe", "content_base64": "AAAA"}}, 400),
    ({"name": "A", "file": {"name": "a.pdf", "content_base64": base64.b64encode(b"hello").decode()}}, 400),
    ({"name": "A", "idea": "x", "folder": "relative/path"}, 400),
    ({"name": "A", "idea": "x", "folder": "~"}, 400),
])
def test_new_project_refusals(client, body, status):
    as_human(client)
    r = client.post("/api/projects/new", json={"survey": {"enabled": False}, **body})
    assert r.status_code == status, r.text


def test_only_the_researcher_starts_a_survey_or_a_project(project):
    from fastapi.testclient import TestClient
    from research_deck.app import create_app
    pid, _ = project
    with TestClient(create_app(), headers={"X-RD-Request": "1"}) as agent:
        assert agent.post(f"/api/projects/{pid}/survey", json={"idea": "x"}).status_code == 403
        assert agent.post("/api/projects/new", json={"name": "A", "idea": "x"}).status_code == 403


def test_cancel_stops_the_survey(client, project, scholar, monkeypatch):
    as_human(client)
    pid, root = project
    gate = {"go": False}
    real = sources.SEARCH["arxiv"]

    def slow(query, limit):
        while not gate["go"]:
            time.sleep(0.01)
        return real(query, limit)
    monkeypatch.setitem(sources.SEARCH, "arxiv", slow)
    r = client.post(f"/api/projects/{pid}/survey", json={"idea": "expert prefetching for MoE inference"})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/projects/{pid}/survey", json={"idea": "again"}).status_code == 409
    deadline = time.time() + 10
    while client.get(f"/api/projects/{pid}/survey").json()["step"] != "search" and time.time() < deadline:
        time.sleep(0.02)
    assert client.post(f"/api/projects/{pid}/survey/cancel").json() == {"ok": True}
    gate["go"] = True
    s = wait_survey(client, pid)
    assert s["status"] == "cancelled" and s["steps"]["search"] == "skipped" and s["steps"]["write"] == "skipped"
    assert not (root / "notes" / "survey.md").exists()
    assert client.post(f"/api/projects/{pid}/survey/cancel").json() == {"ok": False}


def test_a_restart_marks_a_running_survey_interrupted(client, project):
    pid, root = project
    sid = "sv-20260101-000000-abcd"
    d = root / ".research" / "survey"
    d.mkdir(parents=True)
    (d / f"{sid}.json").write_text(json.dumps({"id": sid, "status": "running", "steps": {"frame": "running", "search": "pending"}}))
    s = client.get(f"/api/projects/{pid}/survey").json()
    assert s["status"] == "error" and "interrupted" in s["error"] and s["steps"] == {"frame": "skipped", "search": "skipped"}
    assert job.running(pid) is None


def test_cancel_ends_a_long_wait_at_once(client, project, scholar, monkeypatch):
    as_human(client)
    pid, _ = project
    monkeypatch.setattr(fetch, "sleep", time.sleep)                 # real waits, in 0.25 s slices
    monkeypatch.setitem(sources.PAUSE_S, "arxiv", 60.0)              # the next arXiv call would wait a minute
    monkeypatch.setattr(sources, "_last", {"arxiv": time.monotonic()})
    r = client.post(f"/api/projects/{pid}/survey", json={"idea": "expert prefetching for MoE inference", "sources": ["arxiv"]})
    assert r.status_code == 200, r.text
    deadline = time.time() + 10
    while client.get(f"/api/projects/{pid}/survey").json()["step"] != "search" and time.time() < deadline:
        time.sleep(0.02)
    t0 = time.time()
    assert client.post(f"/api/projects/{pid}/survey/cancel").json() == {"ok": True}
    s = wait_survey(client, pid, timeout=10)
    assert s["status"] == "cancelled" and time.time() - t0 < 3
