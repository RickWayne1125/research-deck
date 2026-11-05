"""Writing panel backend: documents, the five-pass review pipeline (fake agent), findings, learned rules, glossary,
versions (snapshots + git) and DAG claims. No test reaches a real CLI (conftest: RD_FAKE_AGENT, isolated registry).
"""
from __future__ import annotations

import json
import sys
import time
import types

import pytest
import yaml

from research_deck.agents import runner
from research_deck.writing import findings as F
from research_deck.writing import prompts

from conftest import git

PAPER = r"""\documentclass{article}
\title{ToyCache: Tiered \emph{KV} Caching for Long Contexts}
\begin{document}
\maketitle
\begin{abstract}
We recieve teh requests and the the KV-cache grows without bound. ToyCache is 1.7$\times$ faster.
\end{abstract}
\section{Introduction}
% rd:sec sec.intro
The KV cache dominates memory. A KV cache prefetcher hides the transfer; our pre-fetcher always keeps up.
In order to scale, we utilize a large number of GPUs.
\section{Evaluation}
ToyCache reaches a 1.6$\times$ speedup over vLLM and 1.7$\times$ over the offload baseline~\cite{flexgen}.
\end{document}
"""


def wait_review(client, pid, rid, timeout=20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/projects/{pid}/writing/review/{rid}")
        assert r.status_code == 200, r.text
        if r.json()["status"] != "running":
            return r.json()
        time.sleep(0.05)
    raise AssertionError("review did not finish")


def review(client, pid, path="paper/main.tex", **body) -> dict:
    r = client.post(f"/api/projects/{pid}/writing/review", json={"path": path, **body})
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["status"] == "running"
    return wait_review(client, pid, started["review_id"])


@pytest.fixture
def paper(project):
    pid, root = project
    (root / "paper" / "sections").mkdir(parents=True)
    (root / "paper" / "main.tex").write_text(PAPER, encoding="utf-8")
    return pid, root


@pytest.fixture
def fake_dag(monkeypatch):
    """A stand-in for research_deck.dag.service (docs/DAG.md §11) with one stale claim on paper/main.tex."""
    claims = {"paper/main.tex": [
        {"id": "claim.speedup", "label": "1.7× over vLLM", "text": "ToyCache is {{speedup}}× faster than vLLM", "line": 13,
         "evidence": ["exp.e2e"], "freshness": "stale", "values": {"speedup": 1.7}},
        {"id": "sec.intro", "label": "Introduction", "text": "", "line": 9, "evidence": [], "freshness": "fresh", "values": {}},
    ]}
    mod = types.ModuleType("research_deck.dag.service")
    mod.claims_for_doc = lambda pid, path: claims.get(path, [])
    monkeypatch.setitem(sys.modules, "research_deck.dag.service", mod)
    return claims


def capture(monkeypatch, purpose: str) -> list[runner.RunSpec]:
    """Record the specs a pass is started with (and keep its fake answer)."""
    seen: list[runner.RunSpec] = []
    original = runner.FAKE_RESPONDERS[purpose]
    monkeypatch.setitem(runner.FAKE_RESPONDERS, purpose, lambda spec: (seen.append(spec), original(spec))[1])
    return seen


# ------------------------------------------------------------------ documents

def test_docs_lists_tex_and_md_with_titles_and_words(client, paper):
    pid, root = paper
    (root / "paper" / "sections" / "design.tex").write_text("\\section{System Design}\nThe prefetcher reads ahead.\n% a comment here\n")
    (root / "docs").mkdir()
    (root / "docs" / "plan.md").write_text("---\ntitle: ignored\n---\n# Research plan\n\nFirst we 测量 the cache.\n\n```py\ncode words here\n```\n")
    (root / "notes").mkdir()
    (root / "notes" / "idea.md").write_text("no heading here\n")
    (root / "notes" / "script.py").write_text("print('not a doc')\n")
    (root / "src").mkdir()
    (root / "src" / "README.md").write_text("# outside the doc dirs\n")
    docs = client.get(f"/api/projects/{pid}/writing/docs").json()
    by = {d["path"]: d for d in docs}
    assert list(by)[0] == "paper/main.tex"                     # the paper's main file first
    assert set(by) == {"paper/main.tex", "paper/sections/design.tex", "docs/plan.md", "notes/idea.md"}
    assert by["paper/main.tex"]["title"] == "ToyCache: Tiered KV Caching for Long Contexts"
    assert by["paper/main.tex"]["kind"] == "tex" and by["docs/plan.md"]["kind"] == "md"
    assert by["paper/sections/design.tex"]["title"] == "System Design"
    assert by["paper/sections/design.tex"]["words"] == 6          # the comment and the command are not words
    assert by["docs/plan.md"]["title"] == "Research plan"
    assert by["docs/plan.md"]["words"] == 2 + 4 + 2               # heading, words, two CJK characters; front matter and code skipped
    assert by["notes/idea.md"]["title"] == "idea"
    assert all(d["claims"] == 0 and d["stale_claims"] == 0 for d in docs)


def test_docs_count_claims_from_the_dag(client, paper, fake_dag):
    pid, _ = paper
    main = next(d for d in client.get(f"/api/projects/{pid}/writing/docs").json() if d["path"] == "paper/main.tex")
    assert main["claims"] == 2 and main["stale_claims"] == 1
    claims = client.get(f"/api/projects/{pid}/writing/claims", params={"path": "paper/main.tex"}).json()["claims"]
    assert [c["id"] for c in claims] == ["claim.speedup", "sec.intro"]
    assert claims[0]["freshness"] == "stale" and claims[0]["line"] == 13 and claims[0]["evidence"] == ["exp.e2e"]


def test_claims_empty_without_a_dag(client, paper):
    pid, _ = paper
    assert client.get(f"/api/projects/{pid}/writing/claims", params={"path": "paper/main.tex"}).json() == {"claims": []}


def test_paths_are_checked(client, paper):
    pid, _ = paper
    assert client.get(f"/api/projects/{pid}/writing/claims", params={"path": "../outside.tex"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/writing/review", json={"path": "src/x.py"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/writing/review", json={"path": "paper/missing.tex"}).status_code == 404
    assert client.post(f"/api/projects/{pid}/writing/review", json={"path": "paper/main.tex", "passes": ["style"]}).status_code == 400
    assert client.get(f"/api/projects/{pid}/writing/review/rv-nope").status_code == 404


# ------------------------------------------------------------------ the pipeline

def test_full_pipeline_finds_each_kind_of_problem(client, paper):
    pid, root = paper
    r = review(client, pid, lang="en")
    assert r["status"] == "done" and r["passes"] == list(prompts.PIPELINE)
    assert r["progress"] == {p: "done" for p in prompts.PIPELINE}
    text = (root / "paper" / "main.tex").read_text()
    lines = text.split("\n")
    got = {(f["pass"], f["quote"], f["replacement"]) for f in r["findings"]}
    assert {("typo", "teh", "the"), ("typo", "the the", "the"), ("typo", "recieve", "receive")} <= got
    assert ("terminology", "KV-cache", "KV cache") in got
    assert ("terminology", "pre-fetcher", "prefetcher") in got
    assert {("wording", "In order to", "To"), ("wording", "utilize", "use"), ("wording", "a large number of", "many")} <= got
    assert ("consistency", "1.6", "1.7") in got
    assert any(f["pass"] == "logic" and f["quote"] == "always" and f["replacement"] is None for f in r["findings"])
    for f in r["findings"]:
        # every quote sits exactly where the finding says, with the stored `before` right in front of it
        assert f["quote"] in lines[f["line"] - 1]
        assert text[f["offset"]:f["offset"] + len(f["quote"])] == f["quote"]
        assert text[:f["offset"]].endswith(f["before"])
        assert f["status"] == "open" and 0 <= f["confidence"] <= 1 and f["reason"]
    assert all(f["confidence"] >= 0.8 for f in r["findings"] if f["pass"] == "typo")
    assert len({f["id"] for f in r["findings"]}) == len(r["findings"])
    assert (root / ".research" / "writing" / "reviews" / f"{r['review_id']}.json").exists()
    # the reasons follow the language the client asked for
    zh = review(client, pid, passes=["typo"], lang="zh")
    assert "拼写" in zh["findings"][0]["reason"]


def test_passes_run_in_order_with_their_efforts(client, paper, monkeypatch):
    pid, _ = paper
    seen = {p: capture(monkeypatch, f"review-{p}") for p in prompts.PIPELINE}
    order: list[str] = []
    for p in prompts.PIPELINE:
        monkeypatch.setitem(runner.FAKE_RESPONDERS, f"review-{p}",
                            (lambda p, fn: lambda spec: (order.append(p), fn(spec))[1])(p, runner.FAKE_RESPONDERS[f"review-{p}"]))
    review(client, pid, passes=["logic", "typo", "consistency", "wording", "terminology"])
    assert order == list(prompts.PIPELINE)
    efforts = {p: s[0].effort for p, s in seen.items()}
    assert efforts == {"typo": "low", "terminology": "medium", "wording": "high", "consistency": "high", "logic": "xhigh"}
    for p, specs in seen.items():
        spec = specs[0]
        assert spec.panel == "project" and spec.ephemeral and not spec.tools and spec.purpose == f"review-{p}"
        assert spec.session_id is None and spec.system == prompts.SYSTEM


def test_effort_is_clamped_to_the_model(client, paper, monkeypatch):
    pid, _ = paper
    r = client.put(f"/api/projects/{pid}/sessions/writing", json={"model": "claude-haiku-5-5"})
    assert r.status_code == 200, r.text
    seen = capture(monkeypatch, "review-logic")
    review(client, pid, passes=["logic"])
    assert seen[0].effort == "high"             # Haiku stops at high


def test_selection_scope_keeps_findings_inside_the_range(client, paper, monkeypatch):
    pid, _ = paper
    seen = capture(monkeypatch, "review-typo")
    r = review(client, pid, passes=["typo", "wording"], range={"start_line": 10, "end_line": 11})
    assert r["range"] == {"start_line": 10, "end_line": 11}
    assert r["findings"] and all(10 <= f["line"] <= 11 for f in r["findings"])
    assert not any(f["quote"] == "teh" for f in r["findings"])          # line 6 is outside
    assert "Check only lines 10–11" in seen[0].prompt


def test_unsaved_text_is_reviewed(client, paper):
    pid, _ = paper
    r = review(client, pid, passes=["typo"], text="Fresh line.\nWe recieve it.\n")
    assert [(f["quote"], f["line"]) for f in r["findings"]] == [("recieve", 2)]


def test_prompts_carry_context(client, paper, fake_dag, monkeypatch):
    pid, root = paper
    client.put(f"/api/projects/{pid}/writing/glossary", json={"terms": [
        {"term": "KV cache", "preferred": "KV cache", "avoid": ["KV-cache", "kv-cache"], "note": "two words, no hyphen"}]})
    client.put(f"/api/projects/{pid}/writing/rules", json={"rules": [
        {"pass": "wording", "text": "Keep 'utilize' in the related-work quotes.", "on": True},
        {"pass": "wording", "text": "A rule that is off.", "on": False},
        {"pass": "all", "text": "British spelling is deliberate.", "on": True}]})
    (root / ".research" / "experiments").mkdir(exist_ok=True)
    (root / ".research" / "experiments" / "e2e.json").write_text(json.dumps(
        {"id": "e2e", "node_id": "exp.e2e", "title": "End to end", "status": "succeeded", "metrics": {"speedup": 1.71}}))
    seen = {p: capture(monkeypatch, f"review-{p}") for p in prompts.PIPELINE}
    r = review(client, pid, lang="en")
    term, wording, consistency, logic, typo = (seen[p][0].prompt for p in ("terminology", "wording", "consistency", "logic", "typo"))
    assert 'preferred: "KV cache"; avoid: "KV-cache", "kv-cache"' in term
    assert "plain research writing" in wording and "Keep 'utilize'" in wording and "A rule that is off" not in wording
    assert "British spelling is deliberate." in typo and "Keep 'utilize'" not in typo
    assert '"id": "claim.speedup"' in consistency and '"speedup": 1.71' in consistency
    assert '"id": "claim.speedup"' in logic and "<experiments>" not in logic
    assert "   6| We recieve teh requests" in typo                 # numbered lines
    assert "in one short sentence in English" in typo
    # the fake uses the claim's value as the truth and names the claim; logic flags the stale claim's line
    cons = [f for f in r["findings"] if f["pass"] == "consistency"]
    assert [(f["quote"], f["replacement"], f["evidence_node"], f["line"]) for f in cons] == [("1.6", "1.7", "claim.speedup", 13)]
    stale = [f for f in r["findings"] if f["pass"] == "logic" and f["kind"] == "unsupported"]
    assert stale and stale[0]["evidence_node"] == "claim.speedup" and stale[0]["line"] == 13
    # the glossary wins over the document's majority
    assert any(f["pass"] == "terminology" and f["quote"] == "KV-cache" for f in r["findings"])


def test_a_failing_pass_does_not_stop_the_others(client, paper, monkeypatch):
    pid, _ = paper

    def boom(spec):
        raise RuntimeError("the model refused")
    monkeypatch.setitem(runner.FAKE_RESPONDERS, "review-wording", boom)
    r = review(client, pid, passes=["typo", "wording", "consistency"])
    assert r["status"] == "done"
    assert r["progress"] == {"typo": "done", "wording": "error", "consistency": "done"}
    assert "refused" in r["pass_errors"]["wording"]
    assert {f["pass"] for f in r["findings"]} == {"typo", "consistency"}


def test_cancel_stops_the_review(client, paper, monkeypatch):
    pid, _ = paper

    def slow(spec):
        time.sleep(0.6)
        return '{"done": true}'
    monkeypatch.setitem(runner.FAKE_RESPONDERS, "review-typo", slow)
    started = client.post(f"/api/projects/{pid}/writing/review", json={"path": "paper/main.tex", "passes": ["typo", "logic"]}).json()
    time.sleep(0.1)
    assert client.post(f"/api/projects/{pid}/writing/review/{started['review_id']}/cancel").status_code == 200
    r = wait_review(client, pid, started["review_id"])
    assert r.get("cancelled") is True and r["progress"]["logic"] == "error"


def test_reviews_listing_and_auto_snapshot(client, paper):
    pid, _ = paper
    first = review(client, pid, passes=["typo"])
    second = review(client, pid, passes=["typo"])
    listed = client.get(f"/api/projects/{pid}/writing/reviews", params={"path": "paper/main.tex"}).json()
    assert [r["review_id"] for r in listed] == [second["review_id"], first["review_id"]]
    assert listed[0]["counts"]["typo"]["open"] == 3 and "findings" not in listed[0]
    snaps = client.get(f"/api/projects/{pid}/writing/versions", params={"path": "paper/main.tex"}).json()
    assert [v["label"] for v in snaps if v["source"] == "snapshot"] == ["before check"]    # unchanged text: one snapshot


# ------------------------------------------------------------------ findings, rules, dismissals

def test_accept_reject_and_learned_rules(client, paper):
    pid, root = paper
    r = review(client, pid, passes=["typo", "terminology"])
    by = {(f["pass"], f["quote"]): f for f in r["findings"]}
    base = f"/api/projects/{pid}/writing/findings/{r['review_id']}"

    ok = client.post(f"{base}/{by[('typo', 'teh')]['id']}", json={"status": "accepted"}).json()
    assert ok["status"] == "accepted" and ok["decided_by"]

    term = by[("terminology", "KV-cache")]
    no = client.post(f"{base}/{term['id']}", json={"status": "rejected", "reason": "Hyphenated as a compound modifier"}).json()
    assert no["status"] == "rejected" and no["rule_id"]
    rules = client.get(f"/api/projects/{pid}/writing/rules").json()["rules"]
    assert len(rules) == 1
    rule = rules[0]
    assert rule["pass"] == "terminology" and rule["text"] == "Hyphenated as a compound modifier" and rule["on"]
    assert rule["example"] == {"kind": "term", "quote": "KV-cache", "replacement": "KV cache"}
    assert json.loads((root / ".research" / "writing" / "rules.json").read_text())["rules"][0]["id"] == rule["id"]

    # a rejection without a reason teaches no rule, but is never suggested again
    client.post(f"{base}/{by[('typo', 'recieve')]['id']}", json={"status": "rejected"})
    assert len(client.get(f"/api/projects/{pid}/writing/rules").json()["rules"]) == 1

    again = review(client, pid, passes=["typo", "terminology"])
    quotes = {(f["pass"], f["quote"]) for f in again["findings"]}
    assert ("terminology", "KV-cache") not in quotes and ("typo", "recieve") not in quotes
    assert ("typo", "teh") in quotes                 # accepted (the text still has it), so it is found again

    saved = client.get(f"/api/projects/{pid}/writing/review/{r['review_id']}").json()
    assert {f["id"]: f["status"] for f in saved["findings"]}[term["id"]] == "rejected"

    # reopening a rejection lifts the dismissal
    client.post(f"{base}/{by[('typo', 'recieve')]['id']}", json={"status": "open"})
    third = review(client, pid, passes=["typo"])
    assert ("recieve", "receive") in {(f["quote"], f["replacement"]) for f in third["findings"]}


def test_batch_decisions(client, paper):
    pid, _ = paper
    r = review(client, pid, passes=["typo"])
    ids = [f["id"] for f in r["findings"] if f["confidence"] >= 0.8]
    out = client.post(f"/api/projects/{pid}/writing/findings/{r['review_id']}", json={"ids": ids, "status": "accepted"}).json()
    assert [f["status"] for f in out] == ["accepted"] * len(ids)
    assert client.post(f"/api/projects/{pid}/writing/findings/{r['review_id']}", json={"ids": ["nope"], "status": "accepted"}).status_code == 404
    assert client.post(f"/api/projects/{pid}/writing/findings/{r['review_id']}/{ids[0]}", json={"status": "maybe"}).status_code == 422


def test_rules_and_glossary_round_trip(client, paper):
    pid, root = paper
    g = client.put(f"/api/projects/{pid}/writing/glossary", json={"terms": [
        {"term": "prefetcher", "preferred": "prefetcher", "avoid": ["pre-fetcher", "prefetcher"], "note": ""},
        {"term": "", "preferred": "", "avoid": []}]}).json()
    assert g == {"terms": [{"term": "prefetcher", "preferred": "prefetcher", "avoid": ["pre-fetcher"], "note": ""}]}
    assert yaml.safe_load((root / ".research" / "writing" / "glossary.yaml").read_text()) == g
    assert client.get(f"/api/projects/{pid}/writing/glossary").json() == g

    out = client.put(f"/api/projects/{pid}/writing/rules", json={"rules": [
        {"pass": "logic", "text": "Motivation claims may cite prior work only.", "on": False},
        {"pass": "nonsense", "text": "falls back to all"}, {"pass": "typo", "text": "  "}]}).json()["rules"]
    assert [(r["pass"], r["on"]) for r in out] == [("logic", False), ("all", True)]
    assert all(r["id"] and r["created_at"] for r in out)
    assert client.get(f"/api/projects/{pid}/writing/rules").json()["rules"] == out


# ------------------------------------------------------------------ versions

def test_snapshots(client, paper):
    pid, root = paper
    v = client.post(f"/api/projects/{pid}/writing/versions", json={"path": "paper/main.tex", "label": "draft 1"}).json()
    assert v["source"] == "snapshot" and v["label"] == "draft 1" and v["id"].startswith("snap-")
    (root / "paper" / "main.tex").write_text("changed\n")
    listed = client.get(f"/api/projects/{pid}/writing/versions", params={"path": "paper/main.tex"}).json()
    assert listed[0]["id"] == v["id"]
    content = client.get(f"/api/projects/{pid}/writing/versions/{v['id']}", params={"path": "paper/main.tex"}).json()
    assert content == {"content": PAPER}
    assert client.get(f"/api/projects/{pid}/writing/versions/snap-20990101T000000000Z", params={"path": "paper/main.tex"}).status_code == 404
    assert client.get(f"/api/projects/{pid}/writing/versions/other", params={"path": "paper/main.tex"}).status_code == 404
    snap_dir = next((root / ".research" / "writing" / "snapshots").iterdir())
    index = json.loads((snap_dir / "index.json").read_text())
    assert index["path"] == "paper/main.tex" and (snap_dir / index["versions"][0]["file"]).read_text() == PAPER


def test_git_versions(client, paper):
    pid, root = paper
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "paper/main.tex")
    git(root, "commit", "-q", "-m", "first draft")
    (root / "paper" / "main.tex").write_text(PAPER.replace("ToyCache is 1.7", "ToyCache is 1.8"))
    git(root, "commit", "-qam", "second draft")
    git(root, "mv", "paper/main.tex", "paper/paper.tex")
    git(root, "commit", "-qm", "rename")
    versions = client.get(f"/api/projects/{pid}/writing/versions", params={"path": "paper/paper.tex"}).json()
    commits = [v for v in versions if v["source"] == "git"]
    assert [v["label"] for v in commits] == ["rename", "second draft", "first draft"]
    assert all(v["sha"] and v["created_at"] for v in commits)
    first = client.get(f"/api/projects/{pid}/writing/versions/{commits[-1]['id']}", params={"path": "paper/paper.tex"}).json()
    assert first["content"] == PAPER                        # read from the file's old path
    assert client.get(f"/api/projects/{pid}/writing/versions/git-zzzz", params={"path": "paper/paper.tex"}).status_code == 400


def test_versions_outside_git(client, paper):
    pid, _ = paper
    assert client.get(f"/api/projects/{pid}/writing/versions", params={"path": "paper/main.tex"}).json() == []


# ------------------------------------------------------------------ the finding contract

TEXT = "Alpha beta the cache.\nThe cache is   warm here and the cache\nis cold.\n"


def test_parse_answer_accepts_every_shape():
    item = {"kind": "typo", "quote": "beta", "before": "Alpha ", "replacement": "Beta", "reason": "r", "confidence": 0.9}
    lines = json.dumps(item) + "\n" + json.dumps({"done": True, "summary": "one"})
    assert F.parse_answer(lines) == ([item], "one")
    assert F.parse_answer(f"Here you go:\n```json\n[{json.dumps(item)}]\n```")[0] == [item]
    assert F.parse_answer(json.dumps({"findings": [item]}))[0] == [item]
    assert F.parse_answer("prose around [" + json.dumps(item) + "] the array")[0] == [item]
    assert F.parse_answer('{"done": true, "summary": "nothing"}') == ([], "nothing")
    assert F.parse_answer("no json at all") == ([], None)


def test_locate_uses_before_and_line_and_loose_whitespace():
    first = TEXT.index("the cache")
    third = TEXT.rindex("the cache")
    assert F.locate(TEXT, "the cache", "and ") == (third, third + 9)
    assert F.locate(TEXT, "the cache", "Alpha beta ") == (first, first + 9)
    assert F.locate(TEXT, "the cache", "", line=2) == (third, third + 9)
    start, end = F.locate(TEXT, "is warm here", "")
    assert TEXT[start:end] == "is   warm here"
    assert F.locate(TEXT, "absent", "") is None


def test_validator_rules():
    v = F.Validator(TEXT, scope=(1, 2), dismissed={F.fingerprint("typo", "Alpha", "alpha")})
    ok = v.check("typo", {"kind": "grammar", "quote": "is   warm", "before": "cache ", "replacement": "is warm", "confidence": "0.9", "line": 2})
    assert ok and ok["line"] == 2 and ok["kind"] == "grammar" and ok["before"].endswith("The cache ")
    assert v.check("typo", {"quote": "is   warm", "before": "cache ", "replacement": "is warm", "confidence": 0.9}) is None   # duplicate
    assert v.check("typo", {"quote": "not in text", "replacement": "x"}) is None
    assert v.check("typo", {"quote": "beta", "replacement": "beta"}) is None                 # no change
    assert v.check("typo", {"quote": "beta", "replacement": None}) is None                   # edits need a replacement
    assert v.check("typo", {"quote": "Alpha", "replacement": "alpha"}) is None               # dismissed before
    assert v.check("typo", {"quote": "cold", "replacement": "warm"}) is None                 # line 3: outside the scope
    assert v.check("typo", {"quote": "beta", "replacement": "Beta", "confidence": 0.1}) is None
    advisory = v.check("logic", {"kind": "magic", "quote": "the cache.", "replacement": None, "confidence": 70})
    assert advisory and advisory["replacement"] is None and advisory["kind"] == "unsupported" and advisory["confidence"] == 0.7
    prefixed = v.check("wording", {"quote": "   2| The cache", "replacement": "This cache", "confidence": 0.8})
    assert prefixed and prefixed["quote"] == "The cache"
    assert v.dropped["quote not found"] == 1 and v.dropped["duplicate"] == 1
