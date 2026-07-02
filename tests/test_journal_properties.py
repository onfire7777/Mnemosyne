"""Hypothesis property tests for the Phase-0 storage invariants (spec §4.0):
append-only-ness, rebuild determinism, tombstone safety, and torn-tail
recovery, plus cheap lane-invariant predicates.
Chaos/DST fault injection arrives in Phase 2 with SqliteEngine (spec §8)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings, strategies as st

from mnemosyne.journal import CIDJournal

cids = st.lists(st.uuids().map(str), min_size=1, max_size=30, unique=True)


@given(cids)
@settings(max_examples=50, deadline=None)
def test_append_only_prefix_property(cid_list):
    # hypothesis+fixtures don't mix; build our own tmp dir per example
    with tempfile.TemporaryDirectory() as d:
        j = CIDJournal(Path(d) / "t.journal")
        seen: list[str] = []
        for cid in cid_list:
            j.append({"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid})
            current = [r["cid"] for r in j.records()]
            assert current[: len(seen)] == seen, "existing prefix mutated by append"
            seen = current
        assert seen == cid_list


@given(cids)
@settings(max_examples=50, deadline=None)
def test_rebuild_determinism_same_records_same_bytes(cid_list):
    with tempfile.TemporaryDirectory() as d:
        j1 = CIDJournal(Path(d) / "a.journal")
        j2 = CIDJournal(Path(d) / "b.journal")
        for cid in cid_list:
            record = {"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid}
            j1.append(dict(record))
            j2.append(dict(record))
        assert (Path(d) / "a.journal").read_bytes() == (Path(d) / "b.journal").read_bytes()


@given(cids, st.integers(min_value=0, max_value=29))
@settings(max_examples=50, deadline=None)
def test_tombstone_never_loses_non_target_records(cid_list, idx):
    target = cid_list[idx % len(cid_list)]
    with tempfile.TemporaryDirectory() as d:
        j = CIDJournal(Path(d) / "t.journal")
        for cid in cid_list:
            j.append({"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid})
        j.tombstone(target, salted_hash="h", erased_at="2026-07-01T00:00:00Z")
        recs = {r["cid"]: r for r in j.records()}
        assert set(recs) == set(cid_list)                      # nothing lost
        assert recs[target].get("erased") is True              # target tombstoned
        assert "content" not in recs[target]                   # content shredded
        for cid in cid_list:
            if cid != target:
                assert recs[cid]["content"] == cid             # others untouched


@given(cids, st.integers(min_value=0, max_value=2**32))
@settings(max_examples=50, deadline=None)
def test_torn_final_line_recovers_intact_prefix(cid_list, cut_seed):
    """Torn-tail recovery (journal fix semantics, Task 8).

    Tear the FINAL line at an arbitrary mid-line byte offset: records() must
    yield exactly the first n-1 records unchanged, and verify_against(full
    cid set) must flag only the last cid as missing with torn_tail=True.
    """
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.journal"
        j = CIDJournal(path)
        expected: list[dict] = []
        for cid in cid_list:
            record = {"cid": cid, "tenant_id": "t", "kind": "evidence", "content": cid}
            j.append(record)
            expected.append(record)

        body = path.read_bytes()
        assert body.endswith(b"\n")
        lines = body[:-1].split(b"\n")
        last = lines[-1]
        # Keep between 1 and len(last)-1 bytes of the final JSON line (and drop
        # its newline) so the line is genuinely torn -- not deleted, not intact.
        keep = 1 + (cut_seed % (len(last) - 1))
        torn = last[:keep]
        path.write_bytes(b"".join(line + b"\n" for line in lines[:-1]) + torn)

        # Surviving records are byte-identical: every field value round-trips.
        assert list(j.records()) == expected[:-1]

        divergence = j.verify_against(set(cid_list))
        assert divergence.torn_tail is True
        assert divergence.missing_from_journal == [cid_list[-1]]
        assert divergence.journal_only == []
        assert divergence.diverged
