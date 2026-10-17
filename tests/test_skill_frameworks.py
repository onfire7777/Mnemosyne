"""Skills as Proper Thinking frameworks: import, coverage, search, state and forget.

The model-driven conversion itself is exercised live (it needs an OpenRouter key); these
tests replace it with a stub so everything around it runs offline.
"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import pytest

from mnemosyne.frameworks import skills as sk
from mnemosyne.frameworks.book_manager import cited_units, coverage_ledger

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


@pytest.fixture
def store(tmp_path, monkeypatch):
    def fake_convert(self, skill_id, revision):
        row = self._skill(skill_id, revision)
        node = {"parent_index": None, "sort_order": 0, "node_type": "step", "title": "Send the summary",
                "content": "Send the summary to the team channel.", "page_ref": "p.1-3",
                "depends_on_index": None}
        self.db.add_framework_nodes(row["framework_id"], [node])
        self.db.mark_framework_generation_completed(row["framework_id"])
        fw = self.db.get_framework(row["framework_id"])
        with self._sql() as conn:
            conn.execute("UPDATE skills SET effects = ? WHERE skill_id = ? AND revision = ?",
                         (json.dumps(sk.effects_of(fw["nodes"], [])), skill_id, revision))

    monkeypatch.setattr(sk.SkillStore, "_convert", fake_convert)
    return sk.SkillStore(str(tmp_path / "frameworks.sqlite"))


def _skill_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "weekly-update"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_bytes(SKILL.encode("utf-8"))
    (folder / "scripts" / "post.py").write_bytes(b"raise SystemExit('must never run')\n")
    (folder / "LICENSE.txt").write_bytes(b"Apache License, Version 2.0\n")
    return folder


def _wait(store, skill_id):
    for _ in range(100):
        if store.status(skill_id)["conversion"] != "running":
            return
        time.sleep(0.05)
    raise AssertionError("conversion did not finish")


def test_front_matter_and_units():
    meta, body = sk.front_matter(SKILL)
    assert meta == {"name": "weekly-update", "description": "Post the weekly status update to the team channel.",
                    "needs": ["slack"]}
    units = sk.source_units([("SKILL.md", body)], limit=58)
    assert units[0] == "# Weekly update\nCollect what was finished this week."  # a heading heads its text
    assert any("```bash\necho never run\n```" in u for u in units)  # a fence is one unit
    assert len(sk.source_units([("SKILL.md", "\n\n".join(f"p{i}" for i in range(120)))], limit=58)) <= 58


def test_cited_units_and_ledger():
    assert cited_units("p.3") == {3}
    assert cited_units("pp. 2\u20134, p.7") == {2, 3, 4, 7}
    chunks = [{"page_number": i, "chunk_index": 0, "chunk_text": t} for i, t in ((1, "a"), (2, "b"), (3, "a"), (4, "c"))]
    ledger = coverage_ledger(chunks, [{"title": "x", "page_ref": "p.1-2"}])
    assert [u["status"] for u in ledger["units"]] == ["represented", "represented", "duplicate", "unresolved"]
    assert ledger["unresolved"] == [4] and not ledger["complete"]


def test_import_keeps_originals_and_runs_nothing(store, tmp_path):
    folder = _skill_dir(tmp_path)
    result = store.import_skill(str(folder), "test/model")
    assert result["attachments"] == ["LICENSE.txt", "scripts/post.py"]  # kept, not converted
    _wait(store, result["skill_id"])
    status = store.status(result["skill_id"])
    assert status["needs"] == ["slack"] and "sends" in status["effects"]
    row = store._skill(result["skill_id"])
    kept = Path(row["source_dir"])
    assert (kept / "SKILL.md").read_bytes() == SKILL.encode("utf-8")
    assert (kept / "scripts" / "post.py").read_bytes() == b"raise SystemExit('must never run')\n"
    assert store.get(result["skill_id"], attachment="scripts/post.py")["text"].startswith("raise")
    with pytest.raises(ValueError):
        store.get(result["skill_id"], attachment="../frameworks.sqlite")
    # The same files again are the same revision; changed files are a new one.
    assert store.import_skill(str(folder), "test/model")["unchanged"] is True
    (folder / "SKILL.md").write_bytes(SKILL.encode("utf-8") + b"\nOne more line.\n")
    assert store.import_skill(str(folder), "test/model")["revision"] == 2


def test_plain_markdown_becomes_skills(store, tmp_path):
    one = tmp_path / "deploy-site.md"
    one.write_bytes(b"# Deploy the site\n\nRun the build, then push to main.\n")
    result = store.import_skill(str(one), "m")
    assert result["name"] == "deploy-site" and result["units"] == 1
    library = tmp_path / "commands"
    library.mkdir()
    (library / "review.md").write_bytes(b"Review the open pull request.\n")
    (library / "release.md").write_bytes(b"---\nname: cut-release\n---\nTag and publish a release.\n")
    names = [r["name"] for r in store.import_skill(str(library), "m")["imported"]]
    assert names == ["cut-release", "review"]


def test_bs_file_round_trip(store, tmp_path):
    folder = _skill_dir(tmp_path)
    skill_id = store.import_skill(str(folder), "m")["skill_id"]
    _wait(store, skill_id)
    with store._sql() as conn:
        conn.execute("UPDATE frameworks SET definitive_document = '# weekly-update\n## Steps\n'")
    out = store.export_skill(skill_id, str(tmp_path / "out"))
    assert out["path"].endswith("weekly-update.bs")
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert text.startswith("# weekly-update") and "<!-- burnos-skill v1" in text

    other = sk.SkillStore(str(tmp_path / "other" / "frameworks.sqlite"))
    back = other.import_skill(out["path"], "m")
    assert back["from"] == ".bs"
    status = other.status(back["skill_id"])
    assert status["conversion"] == "completed" and status["state"] == "draft"  # no conversion, not on
    assert status["nodes"] == store.status(skill_id)["nodes"] == 1
    kept = Path(other._skill(back["skill_id"])["source_dir"])
    assert (kept / "SKILL.md").read_bytes() == SKILL.encode("utf-8")
    assert other.get(back["skill_id"], section="document")["text"] == "# weekly-update\n## Steps\n"
    assert other.import_skill(out["path"], "m")["unchanged"] is True


def test_zip_traversal_refused(store, tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.md", "x")
    with pytest.raises(ValueError, match="unsafe path"):
        store.import_skill(str(bad), "m")


def test_search_state_and_forget(store, tmp_path):
    result = store.import_skill(str(_skill_dir(tmp_path)), "m")
    skill_id = result["skill_id"]
    _wait(store, skill_id)
    assert store.search("post the weekly update")["skills"] == []  # drafts are not offered
    store.set_state(skill_id, "active")
    assert store.search("post the weekly update", available=["slack"])["skills"][0]["name"] == "weekly-update"
    assert store.search("weekly-update")["matched"] == "name"
    named = store.search("please do my weekly update now", available=["slack"])
    assert named["matched"] == "name" and named["skills"][0]["effects"] == ["sends"]
    assert named["skills"][0]["scripts"] is True
    assert [s["name"] for s in store.search("")["skills"]] == ["weekly-update"]
    assert store.search("what is seven times six? reply with the number only")["skills"] == []
    unmet = store.search("post the weekly update", available=["github"])
    assert unmet["skills"] == [] and unmet["not_eligible"] == [{"name": "weekly-update", "missing": ["slack"]}]
    kept = Path(store._skill(skill_id)["source_dir"])
    store.forget(skill_id)
    assert not kept.exists()
    assert store.search("weekly-update")["skills"] == []
    assert store._rows("SELECT COUNT(*) AS n FROM chunks")[0]["n"] == 0
    assert store._rows("SELECT COUNT(*) AS n FROM framework_nodes")[0]["n"] == 0


class _FakeEmbedder:
    name, model, dims = "fake", "fake", 2

    def embed_many(self, texts):
        return [[0.0, 1.0] if "seven times" in t else [1.0, 0.0] for t in texts]


def test_meaning_search_has_a_floor(store, tmp_path):
    skill_id = store.import_skill(str(_skill_dir(tmp_path)), "m")["skill_id"]
    _wait(store, skill_id)
    store.set_state(skill_id, "active")
    unrelated = store.search("what is seven times six", embedder=_FakeEmbedder())
    assert unrelated["matched"] == "meaning" and unrelated["skills"] == []
    assert store.search("post the team status", embedder=_FakeEmbedder())["skills"][0]["name"] == "weekly-update"


def test_unconverted_skill_cannot_be_turned_on(tmp_path, monkeypatch):
    monkeypatch.setattr(sk.SkillStore, "_convert", lambda self, s, r: None)
    store = sk.SkillStore(str(tmp_path / "f.sqlite"))
    result = store.import_skill(str(_skill_dir(tmp_path)), "m")
    with pytest.raises(ValueError, match="not converted"):
        store.set_state(result["skill_id"], "active")
