"""Skills: plain import, BurnSkills (the engine's passes, model replaced by a stub), coverage,
.burnskill and old .bs files, memory entries, search, state and forget - all offline."""

from __future__ import annotations

import base64
import json
import re
import time
import zipfile
import zlib
from pathlib import Path

import pytest

from mnemosyne import frameworks as fx
from mnemosyne import skills as sk

SKILL = """---
name: weekly-update
description: Post the weekly status update to the team channel.
needs: [slack]
---
# Weekly update

Collect what was finished this week.

## Steps

1. Read the done column.
2. Send the summary to the team channel.

```bash
echo never run
```
"""


def fake_chat(system, user, max_tokens=0, task=""):
    """Answers each pass the way a model would, citing every unit it was shown."""
    if task == "extract":
        units = [int(u) for u in re.findall(r"\[Unit (\d+)\]", user)]
        return {"nodes": [
            {"type": "section", "title": "Procedures", "content": "", "parent": None, "units": units[:1]},
            {"type": "step", "title": "Step 1: Read the done column", "content": "Read it.", "parent": 0,
             "units": units[1:2]},
            {"type": "step", "title": "Step 2: Send the summary", "content": "Send the summary to the team channel.",
             "parent": "0", "depends_on": "1", "units": [str(u) for u in units[2:]]},
            {"type": "warning", "title": "Warning: wrong channel", "content": "Check the channel.", "parent": 0,
             "depends_on": 2, "units": units[2:]}]}
    if task == "fields":
        items = json.loads(user.split("Items:\n", 1)[1])
        return {"items": [{"index": i["index"], "epistemic_type": "fact", "fields": {
            "Action": "Do it.", "ES": "Asserted", "EC": "Verbatim", "CT": "Prescriptive", "CN": "Core",
            "Source Quote": {"Quote": " ".join(["word"] * 80), "Core Sentence": "word"}}} for i in items]}
    if task == "edges":  # drawn the wrong way round on purpose: the taxonomy turns it
        return {"edges": [{"from": "2", "to": 3, "type": "warns", "why": "x"}, {"from": 9, "to": 1, "type": "leads_to"}],
                "logic_issues": [], "logic_warnings": ["minor"], "graph_issues": []}
    if task == "meta":
        return {"purpose": "Post updates.", "claimed_scope": "Team status posts.", "evidenced_scope": "Weekly posts.",
                "effects": ["sends", "flies"]}
    if task == "judge":
        return {"warrants_reextract": False, "findings": ["fine"]}
    if task == "ask":
        return {"answer": "Read the done column first.", "units": [2], "answered": True}
    raise AssertionError(task)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "chat_json", fake_chat)
    return sk.SkillStore(str(tmp_path / "skills.sqlite"))


def _skill_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "weekly-update"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_bytes(SKILL.encode("utf-8"))
    (folder / "scripts" / "post.py").write_bytes(b"raise SystemExit('must never run')\n")
    (folder / "LICENSE.txt").write_bytes(b"Apache License, Version 2.0\n")
    return folder


def _burnskill(store, skill_id, memory=None):
    """Make a skill a BurnSkill and wait for it."""
    revision = store.make_burnskill(skill_id, "test/model", memory)["revision"]
    for _ in range(200):
        if store.status(skill_id, revision)["conversion"] != "converting":
            return store.status(skill_id, revision)
        time.sleep(0.05)
    raise AssertionError("conversion did not finish")


def test_engine_passes(monkeypatch):
    monkeypatch.setattr(fx, "chat_json", fake_chat)
    calls = []
    fw = fx.build("weekly-update", ["# Weekly update", "Read the done column.", "Send the summary."], calls.append)
    assert fw["coverage"]["complete"] and fw["passes"] == 1
    kinds = {(e["from"], e["to"], e["type"]) for e in fw["edges"]}
    assert (3, 2, "warns") in kinds and (1, 2, "leads_to") in kinds  # turned, plus the depends_on edge
    assert not any(e["from"] == 9 for e in fw["edges"])  # an id that does not exist is dropped
    quote = fw["nodes"][1]["fields"]["Source Quote"]["Quote"]
    assert len(quote.split()) == 61  # 60 words and the ellipsis
    assert fw["nodes"][3]["fields"]["Symptoms"] == [fx.GAPS["Symptoms"]]  # the audit filled Proper Thinking's gap
    for heading in ("## 1. Metadata", "## 5. Steps", "### Step 1: Read the done column", "## 8. Dependency Map",
                    "## 9. Scope and Limits", "- minor"):
        assert heading in fw["document"]


def test_reextract_when_units_are_missed(monkeypatch):
    seen = []

    def partial(system, user, max_tokens=0, task=""):
        if task == "extract":
            seen.append("COVERAGE" in user)
            units = [int(u) for u in re.findall(r"\[Unit (\d+)\]", user)]
            return {"nodes": [{"type": "step", "title": "Only", "content": "x",
                               "units": units if len(seen) > 1 else units[:1]}]}
        return fake_chat(system, user, max_tokens, task)

    monkeypatch.setattr(fx, "chat_json", partial)
    fw = fx.build("s", ["a", "b", "c"])
    assert seen == [False, True] and fw["passes"] == 2 and fw["coverage"]["complete"]


def test_a_stalled_call_is_asked_again(monkeypatch):
    import io

    calls = []

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(request, timeout=0):
        calls.append(time.monotonic())
        if len(calls) == 1:
            time.sleep(2)  # the provider sits on the first request
        return Reply(json.dumps({"choices": [{"message": {"content": f'{{"n": {len(calls)}}}'}}]}).encode())

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(fx, "PATIENCE", 0.1)
    monkeypatch.setattr(fx.urllib.request, "urlopen", urlopen)
    started = time.monotonic()
    assert fx.chat_json("s", "u", 0, "t") == {"n": 2} and time.monotonic() - started < 1.5


def test_fields_wait_for_the_kept_pass(monkeypatch):
    tasks = []

    def record(system, user, max_tokens=0, task=""):
        tasks.append(task)
        if task == "extract" and tasks.count("extract") == 1:
            return {"nodes": [{"type": "step", "title": "Only", "content": "x", "units": [1]}]}
        return fake_chat(system, user, max_tokens, task)

    monkeypatch.setattr(fx, "chat_json", record)
    fx.build("s", ["a", "b"])
    first = tasks[: tasks.index("extract", 1)]
    assert "fields" not in first and "meta" not in first  # the pass thrown away got no fields


def test_a_step_loop_becomes_feeds_back_to():
    nodes = [{"id": i, "type": "step", "title": f"S{i}", "fields": {"Action": "a", "Done When": "d", "ES": "x",
              "EC": "x", "CT": "x", "CN": "x"}, "units": [1]} for i in range(3)]
    nodes.append({**nodes[0], "id": 3, "title": "S3"})
    # 1 -> 2 -> 0 -> 1 is the loop; 2 -> 3 only hangs off it and must stay leads_to
    edges = [{"from": 1, "to": 2, "type": "leads_to"}, {"from": 2, "to": 0, "type": "leads_to"},
             {"from": 0, "to": 1, "type": "leads_to"}, {"from": 2, "to": 3, "type": "leads_to"}]
    fw = {"nodes": nodes, "edges": edges, "coverage": {"complete": True, "unresolved": []}}
    audit = fx.mechanical_audit(fw)
    assert audit["passed"] and [e["type"] for e in edges] == ["leads_to", "feeds_back_to", "leads_to", "leads_to"]
    assert fx.step_order(fw) == [0, 1, 2, 3]


def test_effects_come_from_the_model_when_it_judged_them():
    nodes = [{"title": "Delete old drafts", "content": "Remove the drafts, then order lunch."}]
    assert sk.effects_of(nodes, [], None) == ["deletes", "pays"]  # keyword fallback
    assert sk.effects_of(nodes, ["LICENSE.txt"], ["deletes"]) == ["deletes"]  # the model's judgment
    assert sk.effects_of(nodes, ["run.py"], []) == ["runs scripts"]


def test_front_matter_units_and_coverage():
    meta, body = sk.front_matter(SKILL)
    assert meta == {"name": "weekly-update", "description": "Post the weekly status update to the team channel.",
                    "needs": ["slack"]}
    units = sk.source_units([("SKILL.md", body)])
    assert units[0] == "# Weekly update\nCollect what was finished this week."
    assert any("```bash\necho never run\n```" in u for u in units)
    nodes = [{"title": "x", "units": [1, 2]}]
    ledger = fx.coverage(["a", "b", "a", "c"], nodes)
    assert [u["status"] for u in ledger["units"]] == ["represented", "represented", "duplicate", "unresolved"]


def test_import_is_usable_at_once_and_runs_nothing(store, tmp_path):
    folder = _skill_dir(tmp_path)
    result = store.import_skill(str(folder), "test/model")
    assert result["status"] == "ready" and result["kind"] == "skill"
    assert result["attachments"] == ["LICENSE.txt", "scripts/post.py"]
    assert result["effects"] == ["sends", "runs scripts"]
    plain = store.get(result["skill_id"])
    assert plain["file"] == "SKILL.md" and plain["text"] == SKILL and "scripts/post.py" in plain["files"]
    assert store.status(result["skill_id"])["state"] == "active"
    with pytest.raises(ValueError, match="plain skill"):
        store.get(result["skill_id"], section="steps")
    status = _burnskill(store, result["skill_id"])
    assert status["conversion"] == "completed" and status["coverage"]["complete"] and status["state"] == "active"
    assert status["kind"] == "burnskill" and store.status(result["skill_id"], 1)["state"] == "draft"
    assert status["needs"] == ["slack"] and status["effects"] == ["sends", "runs scripts"]
    kept = Path(store._skill(result["skill_id"])["source_dir"])
    assert (kept / "SKILL.md").read_bytes() == SKILL.encode("utf-8")
    assert store.get(result["skill_id"], attachment="scripts/post.py")["text"].startswith("raise")
    with pytest.raises(ValueError):
        store.get(result["skill_id"], attachment="../skills.sqlite")
    graph = store.get(result["skill_id"], section="graph")
    assert len(graph["nodes"]) == 4 and graph["edges"]
    assert store.ask(result["skill_id"], "What comes first?")["answered"] is True
    assert store.import_skill(str(folder), "test/model")["unchanged"] is True
    (folder / "SKILL.md").write_bytes(SKILL.encode("utf-8") + b"\nOne more line.\n")
    assert store.import_skill(str(folder), "test/model")["revision"] == 3
    assert store.make_burnskill(result["skill_id"], "test/model")["revision"] == 4


def test_allowed_bash_means_it_runs_commands(store, tmp_path):
    page = tmp_path / "tidy.md"
    page.write_bytes(b"---\nname: tidy\nallowed-tools: Bash, Read\n---\nTidy the folder.\n")
    assert store.import_skill(str(page), "m")["effects"] == ["runs scripts"]


def test_burnskill_goes_into_memory_once(store, tmp_path):
    skill_id = store.import_skill(str(_skill_dir(tmp_path)), "m")["skill_id"]
    where = {"tenant": "t", "user": "u"}
    _burnskill(store, skill_id, where)
    [row] = store.unremembered()
    texts = store.memory_texts(row)
    assert len(texts) == 4 and texts[1].startswith("weekly-update (BurnSkill step): Step 1")
    assert store.remembered(skill_id, row["revision"], {**where, "cids": ["c1"]}) == []
    assert store.unremembered() == []
    _burnskill(store, skill_id, where)  # a newer BurnSkill: the old entries are handed back to erase
    [newer] = store.unremembered()
    assert store.remembered(skill_id, newer["revision"], {**where, "cids": ["c2"]}) == [{**where, "cids": ["c1"]}]
    assert store.forget(skill_id)["memory"] == [{**where, "cids": ["c2"]}]


def test_plain_markdown_becomes_skills(store, tmp_path):
    one = tmp_path / "deploy-site.md"
    one.write_bytes(b"# Deploy the site\n\nRun the build, then push to main.\n")
    assert store.import_skill(str(one), "m")["name"] == "deploy-site"
    library = tmp_path / "commands"
    library.mkdir()
    (library / "review.md").write_bytes(b"Review the open pull request.\n")
    (library / "release.md").write_bytes(b"---\nname: cut-release\n---\nTag and publish a release.\n")
    assert [r["name"] for r in store.import_skill(str(library), "m")["imported"]] == ["cut-release", "review"]


def test_burnskill_nodes_are_recalled_and_forgotten(tmp_path, monkeypatch):
    from mnemosyne.mcp_server import MnemosyneMcpServer

    monkeypatch.setattr(fx, "chat_json", fake_chat)
    monkeypatch.delenv("MNEMOSYNE_SKILLS_DB", raising=False)
    with MnemosyneMcpServer(store_path=tmp_path / "store.json") as server:
        tools = server.tools
        skill_id = tools.framework_import(str(_skill_dir(tmp_path)))["skill_id"]
        revision = tools.skill_make_burnskill(skill_id, tenant_id="t", user_id="u")["revision"]
        for _ in range(200):
            if tools.framework_status(skill_id, revision)["conversion"] != "converting":
                break
            time.sleep(0.05)
        tools.skill_search("")  # the next skill call puts the finished BurnSkill into memory
        assert "done column" in json.dumps(tools.search("t", "read the done column")["hits"])
        tools.skill_forget(skill_id)
        assert "done column" not in json.dumps(tools.search("t", "read the done column")["hits"])


def test_burnskill_round_trip(store, tmp_path):
    skill_id = store.import_skill(str(_skill_dir(tmp_path)), "m")["skill_id"]
    plain = store.export_skill(skill_id, str(tmp_path / "plain"))  # a plain skill goes out as it came in
    assert (Path(plain["path"]) / "SKILL.md").read_bytes() == SKILL.encode("utf-8")
    _burnskill(store, skill_id)
    out = store.export_skill(skill_id, str(tmp_path / "out"))
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert out["path"].endswith("weekly-update.burnskill") and text.startswith("---\nname: weekly-update\n")
    assert sk.front_matter(text)[0]["description"] == "Post the weekly status update to the team channel."
    other = sk.SkillStore(str(tmp_path / "other" / "skills.sqlite"))
    back = other.import_skill(out["path"], "m")
    status = other.status(back["skill_id"])
    assert status["conversion"] == "completed" and status["state"] == "active" and status["nodes"] == 4
    assert (Path(other._skill(back["skill_id"])["source_dir"]) / "SKILL.md").read_bytes() == SKILL.encode("utf-8")
    assert other.get(back["skill_id"], section="document")["text"] == store.get(skill_id, section="document")["text"]
    assert other.import_skill(out["path"], "m")["unchanged"] is True


def test_version_1_bs_still_imports(store, tmp_path):
    """A .bs file written by Mnemosyne 1.3.0 (Proper Thinking's tables) imports with no conversion."""
    payload = {
        "format": "burnos-skill", "version": 1,
        "skill": {"name": "old-skill", "aliases": "[]", "applicability": "An old one.", "needs": "[]",
                  "effects": "[]", "attachments": "[]", "meta": "{}", "model": "m"},
        "book": {}, "chunks": [{"page_number": 1, "chunk_text": "Do the thing."}],
        "framework": {"definitive_document": "# old-skill\n", "claimed_scope": "c", "evidenced_scope": "e"},
        "nodes": [{"id": 7, "node_type": "step", "title": "Do it", "content": "Do the thing.", "page_ref": "p.1",
                   "parent_id": None, "depends_on_node_id": None, "definitive_fields": '{"Action": "Do."}'}],
        "edges": [], "files": {"SKILL.md": base64.b64encode(b"Do the thing.\n").decode()},
    }
    path = tmp_path / "old-skill.bs"
    packed = base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
    path.write_text(f"# old-skill\n\n<!-- burnos-skill v1\n{packed}\n-->\n", encoding="utf-8")
    back = store.import_skill(str(path), "m")
    node = store.get(back["skill_id"], section="steps")["nodes"][0]
    assert node["units"] == [1] and node["fields"] == {"Action": "Do."}
    assert store.status(back["skill_id"])["coverage"]["complete"]


def test_zip_traversal_refused(store, tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.md", "x")
    with pytest.raises(ValueError, match="unsafe path"):
        store.import_skill(str(bad), "m")


class _FakeEmbedder:
    name, model, dims = "fake", "fake", 2

    def embed_many(self, texts):
        return [[0.0, 1.0] if "seven times" in t else [1.0, 0.0] for t in texts]


def test_search_state_and_forget(store, tmp_path):
    skill_id = store.import_skill(str(_skill_dir(tmp_path)), "m")["skill_id"]
    store.set_state(skill_id, "draft")
    assert store.search("post the weekly update")["skills"] == []  # drafts are not offered
    store.set_state(skill_id, "active")
    assert store.search("post the weekly update", available=["slack"])["skills"][0]["name"] == "weekly-update"
    named = store.search("please do my weekly update now", available=["slack"])
    assert named["matched"] == "name" and named["skills"][0]["scripts"] is True
    assert store.search("what is seven times six? reply with the number only")["skills"] == []
    assert store.search("what is seven times six", embedder=_FakeEmbedder())["skills"] == []
    unmet = store.search("post the weekly update", available=["github"])
    assert unmet["skills"] == [] and unmet["not_eligible"] == [{"name": "weekly-update", "missing": ["slack"]}]
    kept = Path(store._skill(skill_id)["source_dir"])
    store.forget(skill_id)
    assert not kept.exists() and store.search("")["skills"] == []


def test_unconverted_skill_cannot_be_turned_on(tmp_path, monkeypatch):
    monkeypatch.setattr(sk.SkillStore, "_convert", lambda self, s, r: None)
    store = sk.SkillStore(str(tmp_path / "s.sqlite"))
    result = store.import_skill(str(_skill_dir(tmp_path)), "m")
    revision = store.make_burnskill(result["skill_id"], "m")["revision"]
    assert store.make_burnskill(result["skill_id"], "m")["revision"] == revision  # one at a time
    with pytest.raises(ValueError, match="not converted"):
        store.set_state(result["skill_id"], "active", revision)


def _done(store, skill_id, revision):
    for _ in range(200):
        if store.status(skill_id, revision)["conversion"] != "converting":
            return store.status(skill_id, revision)
        time.sleep(0.05)
    raise AssertionError("conversion did not finish")


def _minimal_pdf() -> bytes:
    """One page saying 'Read the done column.', with a correct cross-reference table."""
    stream = b"BT /F1 18 Tf 20 100 Td (Read the done column.) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (n, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


def _epub(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                   '<item id="a" href="one.xhtml"/><item id="b" href="two.xhtml"/></manifest>'
                   '<spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
        z.writestr("OEBPS/one.xhtml", "<html><body><p>Send the summary &amp; stop.</p></body></html>")
        z.writestr("OEBPS/two.xhtml", "<html><style>p{}</style><body><h1>Start</h1><p>Read the done column.</p></body></html>")
    return path


def test_books_are_read_by_page_and_chapter(tmp_path):
    assert sk.book_pages(_epub(tmp_path / "b.epub")) == [("ch.1", "Start Read the done column."),
                                                         ("ch.2", "Send the summary & stop.")]
    pytest.importorskip("pypdf")
    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(_minimal_pdf())
    assert sk.book_pages(pdf) == [("p.1", "Read the done column.")]
    assert sk.chunk_pages([("p.2", " ".join(["w"] * 501))]) == ["[p.2] " + " ".join(["w"] * 500), "[p.2] w"]


def test_a_book_becomes_one_burnskill(store, tmp_path):
    book = store.import_skill(str(_epub(tmp_path / "Weekly Book.epub")), "m")
    assert book["kind"] == "burnskill" and book["status"] == "converting" and book["name"] == "Weekly Book"
    status = _done(store, book["skill_id"], book["revision"])
    assert status["conversion"] == "completed" and status["state"] == "active" and status["kind"] == "burnskill"
    assert store.get(book["skill_id"], section="source")["text"].startswith("[Unit 1]\n[ch.1] Start")
    assert store.files(book["skill_id"]) == ["Weekly Book.epub"]


def test_a_source_too_long_for_one_prompt_is_built_from_picked_passages(store, tmp_path):
    filler = [" ".join(f"filler{i}x{j}" for j in range(120)) for i in range(400)]
    filler[250] = "Risks failures mistakes warnings dangers pitfalls and what to avoid. " + filler[250]
    page = tmp_path / "long.md"
    page.write_text("\n\n".join(filler), encoding="utf-8")
    skill_id = store.import_skill(str(page), "m")["skill_id"]
    revision = store.make_burnskill(skill_id, "m")["revision"]
    assert _done(store, skill_id, revision)["conversion"] == "completed"
    units = json.loads(store._skill(skill_id, revision)["units"])
    assert len(units) <= sk.BOOK_MAX_CHUNKS and sum(map(len, units)) <= sk.BOOK_MAX_CHARS
    assert any("pitfalls" in u for u in units)


def test_validator_passes_an_export_and_names_what_is_wrong(store, tmp_path):
    skill_id = store.import_skill(str(_skill_dir(tmp_path)), "m")["skill_id"]
    _burnskill(store, skill_id)
    path = Path(store.export_skill(skill_id, str(tmp_path / "out"))["path"])
    verdict = sk.validate_burnskill(str(path))
    assert verdict["valid"] and verdict["nodes"] == 4 and verdict["errors"] == []
    _, payload, _ = sk.read_burnskill(path)
    payload["framework"]["edges"].append({"from": 0, "to": 99, "type": "teleports"})
    text = path.read_text(encoding="utf-8")
    head = text[: text.rfind(sk.BS_HEAD)]
    packed = base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
    path.write_text(f"{head}{sk.BS_HEAD}2\n{packed}\n-->\n", encoding="utf-8")
    broken = sk.validate_burnskill(str(path))
    assert not broken["valid"] and len(broken["errors"]) == 2
    assert sk.validate_burnskill(str(tmp_path / "nothing.burnskill"))["valid"] is False


def test_skills_are_offered_as_mcp_prompts_and_resources(tmp_path, monkeypatch):
    types = pytest.importorskip("mcp.types")
    import asyncio

    from mnemosyne.mcp_server import build_sdk_server

    monkeypatch.setattr(fx, "chat_json", fake_chat)
    monkeypatch.delenv("MNEMOSYNE_SKILLS_DB", raising=False)
    server = build_sdk_server(store_path=tmp_path / "store.json")
    try:
        skill_id = server.mnemosyne_mcp_facade.tools.framework_import(str(_skill_dir(tmp_path)))["skill_id"]
        ask = server.request_handlers

        async def run():
            prompts = await ask[types.ListPromptsRequest](types.ListPromptsRequest(method="prompts/list"))
            got = await ask[types.GetPromptRequest](types.GetPromptRequest(
                method="prompts/get", params=types.GetPromptRequestParams(name="weekly-update")))
            listed = await ask[types.ListResourcesRequest](types.ListResourcesRequest(method="resources/list"))
            read = await ask[types.ReadResourceRequest](types.ReadResourceRequest(
                method="resources/read", params=types.ReadResourceRequestParams(uri=f"skill://{skill_id}/scripts/post.py")))
            return prompts.root, got.root, listed.root, read.root

        prompts, got, listed, read = asyncio.run(run())
        assert [p.name for p in prompts.prompts] == ["weekly-update"]
        assert got.messages[0].content.text == SKILL
        assert f"skill://{skill_id}/SKILL.md" in {str(r.uri) for r in listed.resources}
        assert read.contents[0].text.startswith("raise")
    finally:
        server.mnemosyne_mcp_facade.close()
