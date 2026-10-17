"""Skills as frameworks: the engine's passes (model replaced by a stub), import, coverage, .bs
files old and new, search, state and forget - all offline."""

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
        return {"purpose": "Post updates.", "claimed_scope": "Team status posts.", "evidenced_scope": "Weekly posts."}
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


def _wait(store, skill_id):
    for _ in range(200):
        if store.status(skill_id)["conversion"] != "converting":
            return store.status(skill_id)
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
    assert fw["nodes"][3]["fields"]["Symptoms"] == [fx.GAP]  # the mechanical audit filled the gap
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


def test_import_keeps_originals_and_runs_nothing(store, tmp_path):
    folder = _skill_dir(tmp_path)
    result = store.import_skill(str(folder), "test/model")
    assert result["attachments"] == ["LICENSE.txt", "scripts/post.py"]
    status = _wait(store, result["skill_id"])
    assert status["conversion"] == "completed" and status["coverage"]["complete"]
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
    assert store.import_skill(str(folder), "test/model")["revision"] == 2
    assert store.regenerate(result["skill_id"], "test/model")["revision"] == 3


def test_plain_markdown_becomes_skills(store, tmp_path):
    one = tmp_path / "deploy-site.md"
    one.write_bytes(b"# Deploy the site\n\nRun the build, then push to main.\n")
    assert store.import_skill(str(one), "m")["name"] == "deploy-site"
    library = tmp_path / "commands"
    library.mkdir()
    (library / "review.md").write_bytes(b"Review the open pull request.\n")
    (library / "release.md").write_bytes(b"---\nname: cut-release\n---\nTag and publish a release.\n")
    assert [r["name"] for r in store.import_skill(str(library), "m")["imported"]] == ["cut-release", "review"]


def test_bs_round_trip(store, tmp_path):
    skill_id = store.import_skill(str(_skill_dir(tmp_path)), "m")["skill_id"]
    _wait(store, skill_id)
    out = store.export_skill(skill_id, str(tmp_path / "out"))
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert out["path"].endswith("weekly-update.bs") and text.startswith("# weekly-update")
    other = sk.SkillStore(str(tmp_path / "other" / "skills.sqlite"))
    back = other.import_skill(out["path"], "m")
    status = other.status(back["skill_id"])
    assert status["conversion"] == "completed" and status["state"] == "draft" and status["nodes"] == 4
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
    _wait(store, skill_id)
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
    with pytest.raises(ValueError, match="not converted"):
        store.set_state(result["skill_id"], "active")
