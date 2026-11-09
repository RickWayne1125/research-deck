"""The outline as a Markdown file (outline/doc.py): written from the map, read back when the researcher saves it,
edits made elsewhere arriving as a proposal, and the file's own rules (tags, numbers, ‖ groups, ↳ directions)."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from research_deck.outline import doc
from test_outline import STRUCTURE, base, flat, human, ops, outline

PATH = "notes/outline.md"


@pytest.fixture
def made(client, project):
    human(client)
    pid, root = project
    r = client.post(f"{base(pid)}/outline/init", json={"template": "systems", "lang": "en", "structure": STRUCTURE})
    assert r.status_code == 200, r.text
    outline(client, pid)                                   # reading the outline writes the file
    return pid, root


def read(root) -> str:
    return (root / PATH).read_text()


def save(client, pid, text, status=200):
    r = client.put(f"{base(pid)}/file", json={"path": PATH, "content": text})
    assert r.status_code == status, r.text
    return r.json()


def tagged(text: str, iid: str) -> str:
    return next(ln for ln in text.splitlines() if f"rd:item {iid} " in ln)


def edit(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


def ids(o) -> dict[str, str]:
    """text → id over the live items."""
    return {it["text"]: it["id"] for it in flat(o).values() if it["state"] != "abandoned"}


def test_the_outline_is_also_a_markdown_file(client, made):
    pid, root = made
    o = outline(client, pid)
    assert o["file"]["path"] == PATH and not o["file"]["error"]
    text = read(root)
    f = flat(o)
    assert text.startswith("# Outline: Test Project\n")
    assert "## 1 Introduction <!-- rd:sec sec.intro -->" in text
    assert "> The bottleneck is real" in text                             # the role, under its heading
    assert tagged(text, f["2.1"]["id"]) == f"- **2.1** On-demand loading waits 58% of the time. <!-- rd:item {f['2.1']['id']} -->"
    assert tagged(text, f["2.3"]["id"]).startswith("- **2.3** ‖ Adjacent tokens")   # in parallel with 2.2
    lines = text.splitlines()
    assert lines[lines.index(tagged(text, f["2.2"]["id"])) - 1] == "> ‖ two measurements"
    assert tagged(text, f["3.1.1"]["id"]).startswith("  - **3.1.1** Scores")
    assert PATH in [d["path"] for d in client.get(f"{base(pid)}/writing/docs").json()]
    # the parser reads back what was written
    d = doc.parse(text)
    assert [s.id for s in d.sections][:3] == ["sec.intro", "sec.motivation", "sec.design"]
    assert doc.steps_of(d.sections[1].items) == ([[f["2.1"]["id"]], [f["2.2"]["id"], f["2.3"]["id"]], [f["2.4"]["id"]]],
                                                 {"1": "two measurements"})


def test_saving_the_file_changes_the_outline(client, made):
    pid, root = made
    f = flat(outline(client, pid))
    text = read(root)
    text = edit(text, "On-demand loading waits 58% of the time.", "On-demand loading waits most of the time.")
    text = edit(text, f"k = 4-8 covers 90%. <!-- rd:item {f['3.1.2']['id']} -->", f"k = 4-8 covers 90%. (derived) <!-- rd:item {f['3.1.2']['id']} -->")
    text = edit(text, tagged(text, f["2.4"]["id"]) + "\n", "")                                  # removed
    scores = tagged(text, f["3.1.1"]["id"])
    text = edit(text, scores + "\n", "")
    text = edit(text, tagged(text, f["3.2"]["id"]),
                tagged(text, f["3.2"]["id"]) + "\n  - A sub-item typed by hand\n" + scores.strip())      # moved out, after 3.2
    out = save(client, pid, text)
    assert out["outline"]["applied"] is True
    o = outline(client, pid)
    g = flat(o)
    assert g["2.1"]["text"] == "On-demand loading waits most of the time."
    assert g["3.1.1"]["id"] == f["3.1.2"]["id"] and g["3.1.1"]["derived"] is True
    assert g["3.2.1"]["text"] == "A sub-item typed by hand" and g["3.3"]["id"] == f["3.1.1"]["id"]
    assert f["2.4"]["id"] not in ids(o).values()
    gone = client.get(f"{base(pid)}/dag/nodes/{f['2.4']['id']}").json()
    assert gone["status"] == "abandoned"
    # the file comes back with the numbers up to date and the new line tagged
    disk = read(root)
    assert out["content"] == disk and out["sha"]
    assert tagged(disk, g["3.2.1"]["id"]) == f"  - **3.2.1** A sub-item typed by hand <!-- rd:item {g['3.2.1']['id']} -->"
    assert tagged(disk, g["3.3"]["id"]).startswith("- **3.3** Scores are known")
    assert "(derived)" in tagged(disk, g["3.1.1"]["id"])
    # saving it again changes nothing
    before = len(ids(o))
    again = save(client, pid, disk)
    assert again.get("content", disk) == disk and len(ids(outline(client, pid))) == before


def test_changes_on_the_outline_page_reach_the_file(client, made):
    pid, root = made
    f = flat(outline(client, pid))
    ops(client, pid, {"op": "edit_item", "item": f["2.1"]["id"], "text": "Loading waits 58% of the time."})
    assert "- **2.1** Loading waits 58% of the time." in read(root)
    new = ops(client, pid, {"op": "add_item", "parent": f["3.2"]["id"], "text": "Overlap is 80%."})["last"]
    assert tagged(read(root), new) == f"  - **3.2.1** Overlap is 80%. <!-- rd:item {new} -->"
    ops(client, pid, {"op": "remove_item", "item": f["2.4"]["id"]})
    assert f"rd:item {f['2.4']['id']}" not in read(root)


def test_a_line_that_comes_back_revives_its_item(client, made):
    """Cut in one save, pasted somewhere else in the next: the item and what is under it come back, in the new place."""
    pid, root = made
    f = flat(outline(client, pid))
    text = read(root)
    block = "\n".join(tagged(text, f[k]["id"]) for k in ("3.1", "3.1.1", "3.1.2"))
    cut = edit(text, block + "\n", "")
    save(client, pid, cut)
    assert {f["3.1"]["id"], f["3.1.1"]["id"]}.isdisjoint(ids(outline(client, pid)).values())
    pasted = edit(read(root), tagged(read(root), f["2.4"]["id"]), tagged(read(root), f["2.4"]["id"]) + "\n" + block)
    save(client, pid, pasted)
    g = flat(outline(client, pid))
    assert g["2.5"]["id"] == f["3.1"]["id"] and g["2.5.1"]["id"] == f["3.1.1"]["id"] and g["2.5.2"]["id"] == f["3.1.2"]["id"]
    assert g["2.5"]["state"] != "abandoned" and g["3.1"]["id"] == f["3.2"]["id"]


def test_sections_from_the_file(client, made):
    pid, root = made
    text = read(root)
    text = edit(text, "## 3 Design <!-- rd:sec sec.design -->", "## 3 System design <!-- rd:sec sec.design -->")
    text = edit(text, "> How it works: each key decision and why", "> Each key decision and why")
    text = edit(text, "## 4 Implementation", "## Threat model\n\n- The attacker sees the queue.\n- ‖ The attacker sees timing.\n\n## 4 Implementation")
    related = "## 6 Related Work <!-- rd:sec sec.related -->\n\n> How this differs from each line of existing work\n"
    text = edit(text, related, "")
    text = edit(text, "## 2 Background", related + "\n## 2 Background")
    text = edit(text, "## 7 Conclusion <!-- rd:sec sec.conclusion -->\n\n> Summary and outlook (a summary)\n", "")
    save(client, pid, text)
    o = outline(client, pid)
    assert [s["id"] for s in o["sections"]] == ["sec.intro", "sec.related", "sec.motivation", "sec.design",
                                                "sec.threat-model", "sec.implementation", "sec.evaluation"]
    design = o["sections"][3]
    assert design["title"]["en"] == "System design" and design["role"] == "Each key decision and why"
    threat = o["sections"][4]
    assert [[i["text"] for i in st["items"]] for st in threat["items"]] == [["The attacker sees the queue.", "The attacker sees timing."]]
    assert threat["phase"] == "design"                                    # the phase of the section before it
    assert "## 5 Threat model <!-- rd:sec sec.threat-model -->" in read(root)
    assert client.get(f"{base(pid)}/dag/nodes/sec.conclusion").json()["status"] == "abandoned"


def test_edits_made_outside_become_a_proposal(client, made):
    pid, root = made
    f = flat(outline(client, pid))
    (root / PATH).write_text(edit(read(root), "Prefetch during compute.", "Prefetch while computing."))
    o = outline(client, pid)                               # the next read notices
    assert flat(o)["3.2"]["text"] == "Prefetch during compute."
    assert "Prefetch during compute." in read(root)        # the file shows the outline as it is
    props = [p for p in client.get(f"{base(pid)}/dag/proposals").json() if p.get("state") == "open"]
    assert len(props) == 1 and props[0]["by"] == "agent:unknown"
    r = client.post(f"{base(pid)}/dag/proposals/{props[0]['id']}/approve", json={})
    assert r.status_code == 200, r.text
    assert flat(outline(client, pid))["3.2"]["text"] == "Prefetch while computing."
    assert tagged(read(root), f["3.2"]["id"]).startswith("- **3.2** Prefetch while computing.")


def test_an_agents_save_is_a_proposal(client, made):
    pid, root = made
    agent = TestClient(client.app, headers={"X-RD-Request": "1"})
    changed = edit(read(root), "Prefetch during compute.", "Prefetch always.")
    r = agent.put(f"{base(pid)}/file", json={"path": PATH, "content": changed})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["outline"]["proposal"] is True and "Prefetch during compute." in out["content"] == read(root)
    assert flat(outline(client, pid))["3.2"]["text"] == "Prefetch during compute."


def test_what_cannot_be_applied_is_kept_and_said(client, made):
    pid, root = made
    from research_deck.outline import service

    def refuse(*a, **k):
        raise HTTPException(409, "sec.design is locked: unlock it first")
    text = edit(read(root), "Prefetch during compute.", "Prefetch always.")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service, "_commit", refuse)
        out = save(client, pid, text)
    assert out["outline"]["applied"] is False and "locked" in out["outline"]["error"]
    o = outline(client, pid)
    assert o["file"]["error"] and read(root) == text       # the researcher's text stays until a save applies
    assert flat(o)["3.2"]["text"] == "Prefetch during compute."
    out = save(client, pid, text)
    assert out["outline"]["applied"] is True and flat(outline(client, pid))["3.2"]["text"] == "Prefetch always."
    assert not outline(client, pid)["file"]["error"]


def test_branches_in_the_file(client, made):
    pid, root = made
    f = flat(outline(client, pid))
    fork = f["3.2"]["id"]
    ops(client, pid, {"op": "fork", "item": fork, "directions": ["Prefetch on the GPU.", "Prefetch on the CPU."]})
    o = outline(client, pid)
    d1, d2 = (d["id"] for d in flat(o)["3.2"]["fork"]["directions"])
    text = read(root)
    assert tagged(text, d1) == f"  - ↳ Direction 1: Prefetch on the GPU. <!-- rd:item {d1} -->"
    text = edit(text, "Prefetch on the CPU.", "Prefetch on the host.")
    text = edit(text, tagged(text, d2), tagged(text, d2) + "\n  - ↳ Prefetch from disk.\n    - Disks are slow.")
    text = edit(text, tagged(text, f["2.4"]["id"]), tagged(text, f["2.4"]["id"]) + "\n  - ↳ Not a branch here.")
    out = save(client, pid, text)
    g = flat(outline(client, pid))
    dirs = g["3.2"]["fork"]["directions"]
    assert [d["text"] for d in dirs] == ["Prefetch on the GPU.", "Prefetch on the host.", "Prefetch from disk."]
    assert [c["text"] for st in dirs[2]["children"] for c in st["items"]] == ["Disks are slow."]
    assert g["2.4.1"]["text"] == "Not a branch here." and any("sub-item" in w for w in out["outline"]["warnings"])
    # a direction is given up on the outline page, not by deleting its line
    out = save(client, pid, edit(read(root), tagged(read(root), d1) + "\n", ""))
    assert any("outline page" in w for w in out["outline"]["warnings"])
    assert d1 in [d["id"] for d in flat(outline(client, pid))["3.2"]["fork"]["directions"]]


def test_a_file_of_the_researchers_own_is_left_alone(client, project):
    human(client)
    pid, root = project
    (root / "notes").mkdir()
    (root / PATH).write_text("# My outline\n\n- my own notes\n")
    client.post(f"{base(pid)}/outline/init", json={"template": "systems", "lang": "en", "structure": STRUCTURE})
    o = outline(client, pid)
    assert o["file"]["path"] == "notes/outline-2.md" and (root / "notes/outline-2.md").is_file()
    assert read(root) == "# My outline\n\n- my own notes\n"
    # saving the researcher's own file changes nothing on the outline
    out = save(client, pid, "# My outline\n\n## 1 Mine\n- an item\n")
    assert "outline" not in out and len(outline(client, pid)["sections"]) == 7


def test_docmost_gets_the_notes_without_research_decks_tags():
    from research_deck.docmost.sync import split_title
    title, body = split_title("# Outline\n\n<!-- rd:describes claim.x -->\n## 1 Intro <!-- rd:sec sec.intro -->\n"
                              "- **1.1** One. <!-- rd:item claim.a -->\n", "notes/outline.md")
    assert title == "Outline" and body == "## 1 Intro\n- **1.1** One.\n"
