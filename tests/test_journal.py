from __future__ import annotations

import json
from pathlib import Path

from mnemosyne.journal import CIDJournal


def _rec(cid: str) -> dict:
    return {"cid": cid, "tenant_id": "t-a", "content": f"payload-{cid}", "kind": "evidence"}


def _evidence(tenant_id: str, content: str):
    from mnemosyne.models import Evidence

    return Evidence(
        tenant_id=tenant_id,
        user_id="user-a",
        actor="user",
        source_type="chat",
        content=content,
        trust_tier=0,
        access_policy={"tenant": tenant_id},
    )


def test_append_writes_canonical_json_lines(tmp_path: Path):
    j = CIDJournal(tmp_path / "t-a.journal")
    j.append(_rec("cid-1"))
    j.append(_rec("cid-2"))
    lines = (tmp_path / "t-a.journal").read_text().splitlines()
    assert [json.loads(line)["cid"] for line in lines] == ["cid-1", "cid-2"]
    assert lines[0] == json.dumps(_rec("cid-1"), sort_keys=True, separators=(",", ":"))


def test_tombstone_preserves_line_with_marker_not_content(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1"))
    j.append(_rec("cid-2"))
    j.tombstone("cid-1", salted_hash="abc123", erased_at="2026-07-01T00:00:00Z")
    recs = list(j.records())
    assert len(recs) == 2
    tomb = next(r for r in recs if r["cid"] == "cid-1")
    assert tomb["erased"] is True and tomb["salted_hash"] == "abc123"
    assert "content" not in tomb


def test_purge_removes_line_entirely(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1"))
    j.append(_rec("cid-2"))
    j.purge("cid-1")
    assert [r["cid"] for r in j.records()] == ["cid-2"]


def test_verify_against_reports_both_divergence_directions(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1"))
    d = j.verify_against({"cid-1", "cid-2"})
    assert d.missing_from_journal == ["cid-2"] and d.journal_only == []
    d2 = j.verify_against(set())
    assert d2.journal_only == ["cid-1"]


def test_local_engine_appends_to_journal_when_configured(tmp_path: Path):
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine(journal_dir=tmp_path)
    cid = engine.append_evidence(_evidence("t-a", "Journal wiring check."))
    journal = CIDJournal(tmp_path / "t-a.journal")
    assert cid in {r["cid"] for r in journal.records()}


def test_local_engine_dedup_reingest_does_not_duplicate_journal_line(tmp_path: Path):
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine(journal_dir=tmp_path)
    ev = _evidence("t-a", "Dedup journal check.")
    first = engine.append_evidence(ev)
    second = engine.append_evidence(ev)
    assert first == second
    journal = CIDJournal(tmp_path / "t-a.journal")
    assert [r["cid"] for r in journal.records()].count(first) == 1


def test_local_engine_without_journal_dir_writes_no_journal(tmp_path: Path):
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine()
    engine.append_evidence(_evidence("t-a", "No journal configured."))
    assert list(tmp_path.iterdir()) == []
