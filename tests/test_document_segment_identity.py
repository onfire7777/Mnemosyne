"""Optional document identities preserve legacy addresses and source custody."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from uuid import uuid4

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ids import content_cid, evidence_cid
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite", "postgres"])
def engine(request, tmp_path):
    if request.param == "local":
        value = LocalMemoryEngine(tmp_path / "memory.json")
    elif request.param == "sqlite":
        value = SqliteEngine(tmp_path / "sqlite")
    else:
        dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
        if not dsn:
            pytest.skip("live PostgreSQL DSN not configured")
        value = PostgresEngine(dsn)
    yield value
    if isinstance(value, PostgresEngine):
        value.close_connections()
    else:
        value.close()


def source(**changes):
    return Evidence(**{
        "tenant_id": f"segment-{uuid4().hex}", "user_id": "owner", "actor": "user",
        "source_type": "document", "content": "The observatory opens on Tuesday.",
        **changes,
    })


def test_legacy_payload_and_serialization_are_unchanged():
    row = source(tenant_id="legacy")
    expected = content_cid(row.content, {
        "tenant_id": row.tenant_id, "source_type": row.source_type,
        "content_pointer": None, "modality": "text",
    })
    args = dict(tenant_id=row.tenant_id, user_id=row.user_id, source_type=row.source_type,
                content_pointer=None, modality="text", sensitivity=0)
    assert evidence_cid(row.content, **args) == expected
    assert evidence_cid(row.content, document_segment_id=None, **args) == expected
    assert "document_segment_id" not in row.to_dict()
    assert Evidence.from_dict(row.to_dict()) == row


@pytest.mark.parametrize("invalid", ["", " ", "a b", "a\n", "é", "x" * 257, 42, True, [], {}])
def test_segment_identity_is_bounded_and_unambiguous(invalid):
    with pytest.raises(ValueError, match="document_segment_id"):
        source(document_segment_id=invalid)


def test_document_custody_does_not_deduplicate_across_segments_or_owners(engine):
    first = source(document_segment_id="document-a/segment-1")
    a = engine.append_evidence(first)
    b = engine.append_evidence(replace(first, document_segment_id="document-b/segment-1"))
    other_owner = engine.append_evidence(replace(first, user_id="another-owner"))
    assert len({a, b, other_owner}) == 3
    assert engine.append_evidence(first) == a
    assert engine.get_evidence(first.tenant_id, a).document_segment_id == first.document_segment_id
    assert engine.get_evidence(first.tenant_id, b).document_segment_id == "document-b/segment-1"
    assert engine.get_evidence(first.tenant_id, other_owner).user_id == "another-owner"
    # source_identity is descriptive metadata and cannot mutate an existing envelope.
    assert engine.append_evidence(replace(first, source_identity="new-label")) == a
    assert engine.get_evidence(first.tenant_id, a).source_identity is None


def test_document_tombstone_is_scoped_to_segment_generation_and_owner(engine):
    row = source(document_segment_id="document-a/generation-1")
    cid = engine.append_evidence(row)
    assert engine.forget(row.tenant_id, cid)["erased"]
    assert engine.append_evidence(row) == cid
    assert engine.get_evidence(row.tenant_id, cid) is None
    for replacement in (
        replace(row, document_segment_id="document-b/generation-1"),
        replace(row, document_segment_id="document-a/generation-2"),
        replace(row, user_id="another-owner"),
    ):
        fresh = engine.append_evidence(replacement)
        assert fresh != cid
        assert engine.get_evidence(row.tenant_id, fresh) is not None


@pytest.mark.parametrize("sensitivity", [0, 3])
def test_legacy_tombstones_cannot_be_bypassed_with_new_segment_identity(engine, sensitivity):
    row = source(sensitivity=sensitivity)
    cid = engine.append_evidence(row)
    assert engine.forget(row.tenant_id, cid)["erased"]
    assert engine.append_evidence(replace(row, document_segment_id="new-document/segment")) == cid
    assert engine.get_evidence(row.tenant_id, cid) is None


def test_local_serialization_keeps_legacy_shape_and_round_trips_segment(tmp_path):
    path = tmp_path / "memory.json"
    legacy = source(tenant_id="tenant")
    segment = replace(legacy, document_segment_id="document/segment")
    with LocalMemoryEngine(path) as engine:
        legacy_cid = engine.append_evidence(legacy)
        segment_cid = engine.append_evidence(segment)
    records = {row["cid"]: row for row in json.loads(path.read_text())["evidence"]}
    assert "document_segment_id" not in records[legacy_cid]
    assert records[segment_cid]["document_segment_id"] == "document/segment"
    with LocalMemoryEngine(path) as reopened:
        assert reopened.get_evidence("tenant", legacy_cid).document_segment_id is None
        assert reopened.get_evidence("tenant", segment_cid).document_segment_id == "document/segment"
