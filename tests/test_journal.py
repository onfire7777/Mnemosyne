from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

import mnemosyne.journal as journal_module
from mnemosyne.journal import CIDJournal, journal_filename


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


def test_append_and_rewrite_force_raw_lf_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = builtins.open
    write_newlines: list[str | None] = []

    def tracking_open(*args: object, **kwargs: object):
        if len(args) > 1 and args[1] in {"a", "w"}:
            newline = kwargs.get("newline")
            assert newline is None or isinstance(newline, str)
            write_newlines.append(newline)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(journal_module, "open", tracking_open, raising=False)
    path = tmp_path / "t.journal"
    journal = CIDJournal(path)
    journal.append(_rec("cid-1"))
    journal.tombstone(
        "cid-1", salted_hash="abc123", erased_at="2026-07-01T00:00:00Z"
    )

    expected = {
        "cid": "cid-1",
        "erased": True,
        "erased_at": "2026-07-01T00:00:00Z",
        "kind": "evidence",
        "salted_hash": "abc123",
        "tenant_id": "t-a",
    }
    assert write_newlines == ["\n", "\n"]
    assert path.read_bytes() == (
        json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


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


def test_records_tolerates_torn_final_line_and_verify_flags_it(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1"))
    j.append(_rec("cid-2"))
    j.append(_rec("cid-3"))
    # Simulate a crash between the buffered write and fsync: the final line is
    # torn mid-record and the trailing newline never lands.
    path = tmp_path / "t.journal"
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:2]) + lines[2][: len(lines[2]) // 2])
    assert [r["cid"] for r in j.records()] == ["cid-1", "cid-2"]
    d = j.verify_against({"cid-1", "cid-2"})
    assert d.torn_tail is True
    assert d.diverged is True
    assert d.journal_only == []
    assert d.missing_from_journal == []


def test_records_raises_on_corrupt_middle_line(tmp_path: Path):
    j = CIDJournal(tmp_path / "t.journal")
    j.append(_rec("cid-1"))
    j.append(_rec("cid-2"))
    j.append(_rec("cid-3"))
    path = tmp_path / "t.journal"
    lines = path.read_bytes().splitlines(keepends=True)
    lines[1] = b'{"cid": not-json garbage\n'
    path.write_bytes(b"".join(lines))
    with pytest.raises(json.JSONDecodeError):
        list(j.records())


# --- repair-before-append (Phase-0 T8 handoff, first journal item) -----------


def test_append_after_torn_tail_repairs_and_preserves_records(tmp_path: Path):
    """append detects a torn tail and truncates the unfsynced fragment BEFORE
    writing, so all complete records + the new one survive and the file is clean.

    Without repair the torn fragment would become a NON-final line after the
    append and wedge every future read with a JSONDecodeError."""
    path = tmp_path / "t.journal"
    j = CIDJournal(path)
    j.append(_rec("cid-1"))
    j.append(_rec("cid-2"))
    j.append(_rec("cid-3"))
    # Simulate a crash between the buffered write and fsync: the final line is
    # torn (mid-record, no trailing newline).
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(lines[:2]) + lines[2][: len(lines[2]) // 2])

    j.append(_rec("cid-4"))

    assert [r["cid"] for r in j.records()] == ["cid-1", "cid-2", "cid-4"]
    assert path.read_bytes().endswith(b"\n")  # append-safe tail restored
    divergence = j.verify_against({"cid-1", "cid-2", "cid-4"})
    assert divergence.torn_tail is False
    assert divergence.diverged is False


def test_append_after_torn_only_fragment_starts_clean(tmp_path: Path):
    """A torn fragment with no complete line before it truncates to empty."""
    path = tmp_path / "t.journal"
    j = CIDJournal(path)
    path.write_bytes(b'{"cid": "cid-torn", "conte')  # never-fsynced fragment
    j.append(_rec("cid-1"))
    assert [r["cid"] for r in j.records()] == ["cid-1"]
    assert path.read_bytes().endswith(b"\n")


@given(
    st.lists(st.uuids().map(str), min_size=1, max_size=12, unique=True),
    st.integers(min_value=1, max_value=2**32),
)
@settings(max_examples=40, deadline=None)
def test_append_after_torn_tail_property(cid_list, cut_seed):
    """Property: for any journal and any mid-line tear of the final record, an
    append repairs the torn fragment and yields exactly the complete prefix +
    the new record, with no torn tail remaining."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.journal"
        j = CIDJournal(path)
        for cid in cid_list:
            j.append({"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid})
        body = path.read_bytes()
        lines = body[:-1].split(b"\n")  # drop trailing newline, split complete lines
        last = lines[-1]
        keep = cut_seed % len(last)  # 0..len-1: torn (never the full line + newline)
        torn = b"".join(line + b"\n" for line in lines[:-1]) + last[:keep]
        path.write_bytes(torn)

        j.append({"cid": "post-repair", "tenant_id": "t", "kind": "evidence", "content": "x"})

        got = [r["cid"] for r in j.records()]
        assert got == cid_list[:-1] + ["post-repair"]
        assert j.verify_against(set(got)).torn_tail is False
        assert path.read_bytes().endswith(b"\n")


def test_journal_filename_sane_tenant_ids_map_verbatim():
    assert journal_filename("t-a") == "t-a.journal"
    assert journal_filename("tenant.1_x-2") == "tenant.1_x-2.journal"
    assert journal_filename("A9") == "A9.journal"


def test_journal_filename_hostile_tenant_ids_map_to_safe_hashed_names():
    for hostile in ["../evil", "a/b", "..", ".", "", ".hidden", "a\\b", "-flag"]:
        expected = "t-" + hashlib.sha256(hostile.encode()).hexdigest()[:32] + ".journal"
        name = journal_filename(hostile)
        assert name == expected
        assert "/" not in name and "\\" not in name
        assert not name.startswith((".", "-"))


def test_local_engine_hostile_tenant_id_journals_inside_journal_dir(tmp_path: Path):
    from mnemosyne.engine import LocalMemoryEngine

    journal_dir = tmp_path / "journals"
    engine = LocalMemoryEngine(journal_dir=journal_dir)
    cid = engine.append_evidence(_evidence("../evil", "Traversal containment check."))
    # The append landed inside journal_dir under the hashed name...
    hashed = journal_dir / journal_filename("../evil")
    assert hashed.exists()
    assert cid in {r["cid"] for r in CIDJournal(hashed).records()}
    # ...and NOT at the traversal target (tmp_path / "evil.journal"), nor
    # anywhere else outside journal_dir.
    assert not (tmp_path / "evil.journal").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["journals"]


def test_local_engine_without_journal_dir_writes_no_journal(monkeypatch: pytest.MonkeyPatch):
    import mnemosyne.engine as engine_mod
    from mnemosyne.engine import LocalMemoryEngine

    class ForbiddenJournal:
        def __init__(self, *args, **kwargs):
            raise AssertionError("journal must not be constructed")

    monkeypatch.setattr(engine_mod, "CIDJournal", ForbiddenJournal)
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(_evidence("t-a", "No journal configured."))
    assert cid  # append succeeded without ever touching the journal path
