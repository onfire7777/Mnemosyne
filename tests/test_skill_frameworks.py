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


def fake_chat(system, user, max_tokens=0, task="", shared=""):
    """Answers each pass the way a model would, citing every unit it was shown."""
    if task == "extract":
        part = re.search(r"THIS PART: .* units (\d+)-(\d+) of", shared)  # a chapter of a book read once
        units = (list(range(int(part[1]), int(part[2]) + 1)) if part
                 else [int(u) for u in re.findall(r"\[Unit (\d+)\]", shared + user)])
        cross = [{"to": "Read the done column", "type": "warns", "why": "across"}] if part else []
        return {"nodes": [
            {"type": "section", "title": "Procedures", "content": "", "parent": None, "units": units[:1]},
            {"type": "step", "title": "Step 1: Read the done column", "content": "Read it.", "parent": 0,
             "units": units[:2]},
            {"type": "step", "title": "Step 2: Send the summary", "content": "Send the summary to the team channel.",
             "parent": "0", "depends_on": "1", "units": [str(u) for u in (units[2:] or units[-1:])]},
            {"type": "warning", "title": "Warning: wrong channel", "content": "Check the channel.", "parent": 0,
             "depends_on": 2, "units": units[2:] or units[-1:], "cross": cross}]}
    if task == "map":
        numbers = sorted({int(u) for u in re.findall(r"\[Unit (\d+)\]", shared)})
        names = {1: "One", 2: "Two", 3: "Three"}
        return {"chapters": [{"title": names.get(u, f"Chapter {u}"), "first_unit": u, "last_unit": u,
                               "kind": "reference" if f"[Unit {u}]\ncccccccc" in shared else "content"}
                              for u in numbers],
                "spine": [{"title": "Step 1: Read the done column", "chapter": 1},
                          {"title": "Send the summary", "chapter": 1}],
                "glossary": [], "links": [],
                "overview": {"purpose": "Read the book.", "claimed_scope": "Books.", "effects": ["sends", "x"]}}
    if task == "fields":
        items = json.loads(user.split("Items:\n", 1)[1])
        source = shared.split("\n\nFRAMEWORK NODES", 1)[0]
        passages = {int(number): " ".join(text.split()) for number, text in re.findall(
            r"\[Unit (\d+)\]\n(.*?)(?=\n\n\[Unit |\Z)", source, re.S)}
        result = []
        for item in items:
            text = next((passages[int(u)] for u in item["units"] if int(u) in passages), "")
            quote = " ".join(text.split()[:20])
            result.append({"index": item["index"], "epistemic_type": "fact", "fields": {
                "Action": "Do it.", "ES": "Asserted", "EC": "Verbatim", "CT": "Prescriptive", "CN": "Core",
                "Source Quote": {"Quote": quote, "Core Sentence": quote}}})
        return {"items": result}
    if task == "edges":  # drawn the wrong way round on purpose: the taxonomy turns it
        return {"edges": [{"from": "2", "to": 3, "type": "warns", "why": "x"}, {"from": 9, "to": 1, "type": "leads_to"}]}
    if task == "logic":
        return {"logic_issues": [], "logic_warnings": ["minor"], "graph_issues": []}
    if task == "link":  # across the parts of a book
        return {"edges": [{"from": 2, "to": 4, "type": "leads_to", "why": "the next part goes on"}]}
    if task == "meta":
        return {"purpose": "Post updates.", "claimed_scope": "Team status posts.", "evidenced_scope": "Weekly posts.",
                "effects": ["sends", "flies"]}
    if task == "judge":
        return {"warrants_reextract": False, "findings": ["fine"]}
    if task == "ask":
        return {"answer": "Read the done column first.", "units": [2], "answered": True}
    raise AssertionError(task)


@pytest.fixture(autouse=True)
def _isolate_framework_cache():
    """Ensure tests in this module run with a clean, isolated framework cache."""
    token = fx.CACHE.set("")
    try:
        yield
    finally:
        try:
            fx.CACHE.reset(token)
        finally:
            fx.CACHE.set("")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "chat_json", fake_chat)
    monkeypatch.setattr(fx, "check_credit", lambda units: None)  # never a real request from a test
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
    assert quote == "# Weekly update"  # exact source text, never an invented citation
    assert fw["nodes"][3]["fields"]["Symptoms"] == [fx.GAPS["Symptoms"]]  # the audit filled Proper Thinking's gap
    for heading in ("## 1. Metadata", "## 5. Steps", "### Step 1: Read the done column", "## 8. Dependency Map",
                    "## 9. Scope and Limits", "- minor"):
        assert heading in fw["document"]


def test_missed_units_are_repaired_not_rebuilt(monkeypatch):
    calls = []

    def partial(system, user, max_tokens=0, task="", shared=""):
        calls.append((task, user))
        if task == "extract":
            return {"nodes": [{"type": "step", "title": "First", "content": "x", "units": [1]}]}
        if task == "extend":
            assert "COVERAGE: units [2, 3]" in user and "[0] step: First" in shared  # it sees what exists
            return {"add": [{"type": "step", "title": "Second", "content": "y", "depends_on": 0, "units": [2, 3]}],
                    "change": [{"id": 9, "title": "no such node"}]}
        return fake_chat(system, user, max_tokens, task, shared)

    monkeypatch.setattr(fx, "chat_json", partial)
    fw = fx.build("s", ["a", "b", "c"])
    tasks = [t for t, _ in calls]
    assert tasks.count("extract") == 1 and tasks.count("extend") == 1  # no second extraction from nothing
    assert fw["passes"] == 2 and fw["coverage"]["complete"] and [n["title"] for n in fw["nodes"]] == ["First", "Second"]
    second = [json.loads(u.split("Items:\n", 1)[1]) for t, u in calls[tasks.index("extend"):] if t == "fields"]
    assert [i["index"] for batch in second for i in batch] == [1]  # only the added node gets new fields
    assert fw["nodes"][0]["fields"]["Action"] == "Do it."  # the finished node kept its fields
    after = tasks[tasks.index("extend"):]
    assert all(t in after for t in ("edges", "logic", "judge"))  # every check runs again on the whole


def test_a_rebuild_only_when_the_judge_says_the_whole_is_wrong(monkeypatch):
    judged = []

    def wrong(system, user, max_tokens=0, task="", shared=""):
        if task == "judge":
            judged.append(1)
            if len(judged) == 1:
                return {"warrants_reextract": True, "rebuild": True, "findings": ["misread"],
                        "extractor_instructions": "The steps are cases; extract the procedure again from scratch."}
        return fake_chat(system, user, max_tokens, task, shared)

    monkeypatch.setattr(fx, "chat_json", wrong)
    tasks = []
    monkeypatch.setattr(fx, "chat_json", lambda *a, **k: tasks.append(a[3]) or wrong(*a, **k))
    fw = fx.build("s", ["a", "b", "c"])
    assert tasks.count("extract") == 2 and "extend" not in tasks and fw["passes"] == 2


def _reply(n: int) -> dict:
    return {"choices": [{"message": {"content": f'{{"n": {n}}}'}}]}


def test_a_failed_repair_keeps_the_first_pass(monkeypatch):
    def broken(system, user, max_tokens=0, task="", shared=""):
        if task == "extend":
            return {}  # the model's answer could not be read twice over
        if task == "extract":
            return {"nodes": [{"type": "step", "title": "Only", "content": "x", "units": [1]}]}
        return fake_chat(system, user, max_tokens, task, shared)

    monkeypatch.setattr(fx, "chat_json", broken)
    fw = fx.build("s", ["a", "b"])
    assert fw["passes"] == 1 and fw["coverage"]["unresolved"] == [2] and "Source unit 2" in fw["document"]
    assert fw["judgment"]["findings"][-1].startswith("The repair changed nothing")


def test_a_stalled_call_is_asked_again(monkeypatch):
    calls = []

    def post(body, key):
        calls.append(time.monotonic())
        if len(calls) == 1:
            time.sleep(2)  # the provider sits on the first request
        return _reply(len(calls))

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(fx, "PATIENCE", {"t": 0.1})
    monkeypatch.setattr(fx, "_post", post)
    started = time.monotonic()
    assert fx.chat_json("s", "u", 0, "t") == {"n": 2} and time.monotonic() - started < 1.5


def test_code_fences_inside_the_answer_are_kept(monkeypatch):
    inner = {"content": "Run it:\n```bash\nnpm test\n```\nThen read the output."}
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    token = fx.CACHE.set("")
    try:
        for wrapped in (json.dumps(inner), "```json\n" + json.dumps(inner) + "\n```", "Here it is: " + json.dumps(inner)):
            monkeypatch.setattr(fx, "_post", lambda body, key, w=wrapped: {"choices": [{"message": {"content": w}}]})
            assert fx.chat_json("s", "u", 0, "t") == inner
    finally:
        fx.CACHE.reset(token)


def test_a_resumed_build_does_not_ask_twice(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(fx, "_post", lambda body, key: calls.append(body) or _reply(len(calls)))
    token = fx.CACHE.set(str(tmp_path / "cache"))
    try:
        assert fx.chat_json("s", "u", 0, "t") == {"n": 1} and fx.chat_json("s", "u", 0, "t") == {"n": 1}
        assert fx.chat_json("s", "other", 0, "t") == {"n": 2} and len(calls) == 2  # new input, new answer
    finally:
        fx.CACHE.reset(token)


def test_the_judge_reads_the_finished_pass(monkeypatch):
    tasks, judged = [], []
    long_content = "Read it. " * 80  # well past the old 400-character snippet

    starts = {}

    def record(system, user, max_tokens=0, task="", shared=""):
        tasks.append(task)
        starts[task] = shared
        if task == "extract":
            return {"nodes": [{"type": "step", "title": "Only", "content": long_content, "units": [1, 2]}]}
        if task == "judge":
            judged.append(shared + user)
        return fake_chat(system, user, max_tokens, task, shared)

    monkeypatch.setattr(fx, "chat_json", record)
    fw = fx.build("s", ["a", "b"])
    assert tasks.index("judge") > max(tasks.index(t) for t in ("edges", "logic", "meta", "fields"))
    assert '"Action": "Do it."' in judged[0] and '"ES": "Asserted"' in judged[0]  # fields and tags
    assert " ".join(long_content.split()) in judged[0] and "Mechanical audit" in judged[0]
    assert fw["passes"] == 1 and fw["meta"]["purpose"] == "Post updates."
    # laid out for the provider cache: every call after extraction starts with the same text
    after = {starts[t] for t in ("edges", "logic", "meta", "fields", "judge")}
    assert len(after) == 1 and next(iter(after)).startswith(starts["extract"]) and "[Unit 2]" in starts["extract"]


def test_a_build_the_credit_cannot_cover_is_refused_first(monkeypatch):
    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, method, path, headers=None):
            assert (method, path) == ("GET", "/api/v1/key")

        def getresponse(self):
            return type("R", (), {"read": lambda s: b'{"data": {"limit_remaining": 2.5}}'})()

        def close(self):
            pass

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(fx.http.client, "HTTPSConnection", Conn)
    with pytest.raises(RuntimeError, match=r"\$2.50 of credit left"):
        fx.check_credit(["x"])
    token = fx.MODEL.set("codex:default")
    try:
        fx.check_credit(["x"])  # the subscription is not charged per call
    finally:
        fx.MODEL.reset(token)


def test_the_prompt_starts_with_the_rulebook_and_counts_usage(monkeypatch, tmp_path):
    bodies = []
    reply = {"choices": [{"message": {"content": '{"n": 1}'}}],
             "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.01,
                       "prompt_tokens_details": {"cached_tokens": 80}}}
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(fx, "_post", lambda body, key: bodies.append(json.loads(body)) or reply)
    stats, cache = {}, fx.CACHE.set(str(tmp_path))
    token = fx.STATS.set(stats)
    try:
        fx.chat_json("TASK ONE", "a", 0, "t", shared="SOURCE")
        fx.chat_json("TASK TWO", "b", 0, "t", shared="SOURCE")
        fx.chat_json("TASK ONE", "a", 0, "t", shared="SOURCE")  # asked before: from the answer cache
    finally:
        fx.STATS.reset(token)
        fx.CACHE.reset(cache)
    assert [b["messages"][0]["content"] for b in bodies] == [fx.RULEBOOK] * 2
    assert all(b["messages"][1]["content"].startswith("SOURCE\n\n=== TASK ===\n") for b in bodies)
    assert bodies[0]["prompt_cache_key"] == bodies[1]["prompt_cache_key"] and bodies[0]["max_tokens"] >= fx.MIN_TOKENS
    assert stats == {"calls": 2, "seconds": stats["seconds"], "tokens_in": 200, "tokens_cached": 160, "tokens_out": 20,
                     "cost_usd": 0.02, "answers_from_cache": 1}


def test_graph_repair_is_add_and_remove_operations():
    nodes = [{"id": i, "type": t, "title": t, "depends_on": None} for i, t in enumerate(("step", "step", "warning"))]
    fw = {"nodes": nodes, "edges": [{"from": 1, "to": 0, "type": "leads_to", "why": ""}]}
    assert fx.apply_operations(fw, [{"op": "remove", "from": 1, "to": 0, "type": "leads_to"},
                                    {"op": "add", "from": "0", "to": 1, "type": "leads_to"},
                                    {"op": "add", "from": 0, "to": 2, "type": "warns"},  # turned round
                                    {"op": "add", "from": 0, "to": 7, "type": "leads_to"}])  # no such node
    assert {(e["from"], e["to"], e["type"]) for e in fw["edges"]} == {(0, 1, "leads_to"), (2, 0, "warns")}
    assert not fx.apply_operations(fw, [])


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
    nodes = [{"type": "principle", "title": "x", "content": "a and b", "units": [1, 2]}]
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
    monkeypatch.setattr(fx, "check_credit", lambda units: None)
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
    path.write_text(f"# old-skill\n\n<!-- burnos-skill v1\n{packed}\n-->\n", encoding="utf-8", newline="\n")
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
    assert sk.chunk_pages([("p.2", " ".join(["w"] * 600))]) == ["[p.2] " + " ".join(["w"] * 500),
                                                             "[p.2] " + " ".join(["w"] * 100)]
    # a scrap at a page break is read with its neighbour, never alone
    assert sk.chunk_pages([("p.98", " ".join(["w"] * 60)), ("p.99", "make it emotional?"), ("p.100", "x " * 50)]) == [
        "[p.98] " + " ".join(["w"] * 60) + " [p.99] make it emotional?", "[p.100] " + " ".join(["x"] * 50)]
    assert sk.chunk_pages([("p.1", "Title"), ("p.2", "y " * 50)]) == ["[p.1] Title [p.2] " + " ".join(["y"] * 50)]


def test_a_book_becomes_one_burnskill(store, tmp_path):
    book = store.import_skill(str(_epub(tmp_path / "Weekly Book.epub")), "m")
    assert book["kind"] == "burnskill" and book["status"] == "converting" and book["name"] == "Weekly Book"
    status = _done(store, book["skill_id"], book["revision"])
    assert status["conversion"] == "completed" and status["state"] == "active" and status["kind"] == "burnskill"
    assert store.get(book["skill_id"], section="source")["text"].startswith("[Unit 1]\n[ch.1] Start")
    assert store.files(book["skill_id"]) == ["Weekly Book.epub"]


def test_a_book_with_a_very_long_name_is_kept(store, tmp_path):
    book = store.import_skill(str(_epub(tmp_path / (("Blue Ocean Strategy " * 7).strip() + ".epub"))), "m")
    assert len(store.files(book["skill_id"])[0]) <= 65 and _done(store, book["skill_id"], 1)["conversion"] == "completed"


def test_a_book_is_built_part_by_part_and_joined(monkeypatch):
    monkeypatch.setattr(fx, "chat_json", fake_chat)
    monkeypatch.setattr(fx, "WINDOW_CHARS", 10)
    units = ["aaaaaaaa", "bbbbbbbb", "cccccccc"]
    assert fx.windows(units) == [[1], [2], [3]]
    calls = []
    monkeypatch.setattr(fx, "chat_json", lambda *a, **k: calls.append((a[3], k.get("shared", ""))) or fake_chat(*a, **k))
    fw = fx.build("book", units)
    tasks = [t for t, _ in calls]
    assert tasks.count("map") == 3 and "meta" not in tasks  # every bounded window is mapped
    assert tasks[0] == "map"
    mapped = [shared for task, shared in calls if task == "map"]
    assert all(sum(f"[Unit {u}]" in text for text in mapped) == 1 for u in (1, 2, 3))
    assert all(s.count("[Unit 2]") <= 1 for _, s in calls[1:])  # then only its own chapter carries a passage
    assert sum("[Unit 2]" in s for t, s in calls[1:] if t == "extract") == 1
    assert tasks.count("extract") == 2 and not any("[Unit 3]" in s for t, s in calls if t == "extract")
    assert fw["parts"] == 2 and fw["coverage"]["complete"] and fw["coverage"]["unresolved"] == []
    assert fw["coverage"]["units"][2] == {"unit": 3, "status": "reference", "of": "Three"}
    assert "Three (units 3-3) is reference matter" in fw["document"]
    sections = [n for n in fw["nodes"] if n["type"] == "section"]
    assert len(sections) == 1 and sections[0]["units"] == [1, 2]  # one Procedures section for the book
    # the same steps met in both chapters are one node each; each chapter's warning stays its own
    assert [n["type"] for n in fw["nodes"]] == ["section", "step", "step", "warning", "warning"]
    assert all(n["parent"] == 0 for n in fw["nodes"][1:]) and [n["part"] for n in fw["nodes"]] == [1, 1, 1, 1, 2]
    kinds = {(e["from"], e["to"], e["type"]) for e in fw["edges"]}
    assert (3, 1, "warns") in kinds  # chapter One's warning on the shared step, by name
    assert (4, 2, "warns") in kinds  # chapter Two's own relation, now on the merged step
    assert fw["meta"]["purpose"] == "Read the book." and fw["meta"]["effects"] == ["sends"]
    assert fw["logic"]["logic_warnings"][0].startswith("Part 1 (One, units 1-1 of 3): minor")
    assert fw["logic"]["logic_warnings"][-1] == "Whole book: minor"


def test_codex_failures_are_told_apart():
    noise = 'ERROR rmcp::transport::worker: AuthRequired(... oauth-protected-resource ...)\n'
    assert fx.codex_failure(noise + "ERROR: Selected model is at capacity. Please try a different model.")[0] == "busy"
    assert fx.codex_failure(noise + "ERROR: You've hit your usage limit.")[0] == "fatal"
    assert fx.codex_failure(noise)[0] == ""  # a plugin's sign-in noise is not a lost login


def test_a_failed_book_imported_again_is_built_again(store, tmp_path, monkeypatch):
    real = sk.SkillStore._convert
    monkeypatch.setattr(sk.SkillStore, "_convert", lambda self, s, r: (_ for _ in ()).throw(RuntimeError("busy")))
    first = store.import_skill(str(_epub(tmp_path / "Weekly Book.epub")), "m")
    assert _done(store, first["skill_id"], 1)["conversion"] == "failed"
    monkeypatch.setattr(sk.SkillStore, "_convert", real)
    again = store.import_skill(str(_epub(tmp_path / "Weekly Book.epub")), "m")
    assert again["revision"] == 2 and _done(store, first["skill_id"], 2)["conversion"] == "completed"


def test_a_built_book_imports_at_once_under_any_name(store, tmp_path):
    original = _epub(tmp_path / "Weekly Book.epub")
    first = store.import_skill(str(original), "m")
    assert _done(store, first["skill_id"], first["revision"])["conversion"] == "completed"
    renamed = tmp_path / "renamed copy.epub"
    # A renamed file keeps its bytes; rebuilding the ZIP can change its member timestamps.
    renamed.write_bytes(original.read_bytes())
    again = store.import_skill(str(renamed), "m")
    assert again == {"skill_id": first["skill_id"], "revision": 1, "name": "Weekly Book", "kind": "burnskill",
                     "status": "ready", "unchanged": True}


def test_a_book_is_in_memory_before_its_framework(tmp_path, monkeypatch):
    from mnemosyne.mcp_server import MnemosyneMcpServer

    monkeypatch.setattr(sk.SkillStore, "_convert", lambda self, s, r: None)  # the framework never comes
    monkeypatch.delenv("MNEMOSYNE_SKILLS_DB", raising=False)
    with MnemosyneMcpServer(store_path=tmp_path / "store.json") as server:
        tools = server.tools
        book = tools.framework_import(str(_epub(tmp_path / "Weekly Book.epub")), tenant_id="t", user_id="u")
        assert book["status"] == "converting"
        assert "done column" in json.dumps(tools.search("t", "read the done column")["hits"])  # recalled already
        tools.skill_forget(book["skill_id"])
        assert "done column" not in json.dumps(tools.search("t", "read the done column")["hits"])


def test_the_map_chapters_cover_every_unit_once():
    units = ["x" * 5] * 10
    got = fx.chapters({"chapters": [{"title": "Index", "first_unit": 4, "last_unit": 10, "kind": "reference"},
                                    {"title": "A", "first_unit": 3, "last_unit": 3}, {"title": "dup", "first_unit": 4, "last_unit": 4},
                                    {"title": "bad", "first_unit": 99}]}, units)
    assert [n for _, ns, _ in got for n in ns] == list(range(1, 11))  # gap before 3 and the duplicate start handled
    assert [n for _, ns, ref in got if ref for n in ns] == list(range(5, 11))
    assert any("Overlapping" in title and not ref for title, _, ref in got)
    assert fx.chapters({}, units) == [("Unmapped units 1-10", list(range(1, 11)), False)]
    titled = fx.chapters({"chapters": [{"title": "Renew Blue Oceans", "first_unit": 1, "last_unit": 5, "kind": "content"},
                                       {"title": "Notes", "first_unit": 6, "last_unit": 10, "kind": "content"}]}, units)
    assert [r for _, _, r in titled] == [False, False]  # explicit content cannot be skipped by its title


def test_codex_server_asks_in_throwaway_conversations_with_one_start():
    server = fx.CodexServer.__new__(fx.CodexServer)
    server.model, server.tmp = "gpt-6.1-sol", "tmp"
    calls, sent = [], []
    server._call = lambda method, params: calls.append((method, params)) or {"thread": {"id": f"t{len(calls)}"}}
    server._turn = lambda thread, text: sent.append(text) or {
        "text": '{"ok": true}', "usage": {"inputTokens": 100, "cachedInputTokens": 90, "outputTokens": 5}}
    reply = server.ask("BOOK", "task one")
    server.ask("BOOK", "task two")
    starts = [p for m, p in calls if m == "thread/start"]
    assert all(p["baseInstructions"] == fx.RULEBOOK and p["ephemeral"] and p["sandbox"] == "read-only" for p in starts)
    assert sent == ["BOOK\n\ntask one", "BOOK\n\ntask two"]  # the same start every time: the provider caches it
    assert [m for m, _ in calls].count("thread/unsubscribe") == 2  # nothing is kept
    assert reply["usage"]["prompt_tokens_details"]["cached_tokens"] == 90


def test_a_long_book_keeps_every_passage(store, tmp_path):
    filler = [" ".join(f"filler{i}x{j}" for j in range(120)) for i in range(400)]
    page = tmp_path / "long.md"
    page.write_text("\n\n".join(filler), encoding="utf-8", newline="\n")
    skill_id = store.import_skill(str(page), "m")["skill_id"]
    revision = store.make_burnskill(skill_id, "m")["revision"]
    status = _done(store, skill_id, revision)
    assert status["conversion"] == "completed" and status["coverage"] == {"complete": True, "unresolved": []}
    units = json.loads(store._skill(skill_id, revision)["units"])
    assert " ".join(units).count("filler") == 400 * 120  # every word of the source is still a unit
    fw = json.loads(store._skill(skill_id, revision)["framework"])
    assert fw["parts"] > 1 and {n.get("part") for n in fw["nodes"]} == set(range(1, fw["parts"] + 1))


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
    path.write_text(f"{head}{sk.BS_HEAD}2\n{packed}\n-->\n", encoding="utf-8", newline="\n")
    broken = sk.validate_burnskill(str(path))
    assert not broken["valid"] and len(broken["errors"]) == 2
    assert sk.validate_burnskill(str(tmp_path / "nothing.burnskill"))["valid"] is False


def test_skills_are_offered_as_mcp_prompts_and_resources(tmp_path, monkeypatch):
    types = pytest.importorskip("mcp_types")
    from tests.sdk_helper import sdk_handler
    import asyncio

    from mnemosyne.mcp_server import build_sdk_server

    monkeypatch.setattr(fx, "chat_json", fake_chat)
    monkeypatch.delenv("MNEMOSYNE_SKILLS_DB", raising=False)
    server = build_sdk_server(store_path=tmp_path / "store.json")
    try:
        skill_id = server.mnemosyne_mcp_facade.tools.framework_import(str(_skill_dir(tmp_path)))["skill_id"]

        async def run():
            prompts = await sdk_handler(server, types.ListPromptsRequest)(types.ListPromptsRequest(method="prompts/list"))
            got = await sdk_handler(server, types.GetPromptRequest)(types.GetPromptRequest(
                method="prompts/get", params=types.GetPromptRequestParams(name="weekly-update")))
            listed = await sdk_handler(server, types.ListResourcesRequest)(types.ListResourcesRequest(method="resources/list"))
            read = await sdk_handler(server, types.ReadResourceRequest)(types.ReadResourceRequest(
                method="resources/read", params=types.ReadResourceRequestParams(uri=f"skill://{skill_id}/scripts/post.py")))
            return prompts, got, listed, read

        prompts, got, listed, read = asyncio.run(run())
        assert [p.name for p in prompts.prompts] == ["weekly-update"]
        assert got.messages[0].content.text == SKILL
        assert f"skill://{skill_id}/SKILL.md" in {str(r.uri) for r in listed.resources}
        assert read.contents[0].text.startswith("raise")
    finally:
        server.mnemosyne_mcp_facade.close()
