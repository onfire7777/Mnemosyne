"""Immediate source writes must not outlive a failed local-store commit."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import mnemosyne.engine as engine_module
from mnemosyne.cid_lists import evidence_epoch
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ids import evidence_cid
from mnemosyne.journal import CIDJournal, journal_filename
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy


def evidence(content: str, *, actor: str = "user") -> Evidence:
    return Evidence(
        tenant_id="tenant", user_id="owner", actor=actor,
        source_type="chat", source_identity="source", content=content,
        metadata={"document": {"revision": 1}},
        access_policy={"tenant": "tenant"},
    )


def cid_for(row: Evidence) -> str:
    return evidence_cid(
        row.content, tenant_id=row.tenant_id, user_id=row.user_id,
        source_type=row.source_type, content_pointer=row.content_pointer,
        modality=row.modality, sensitivity=row.sensitivity,
    )


def fail_commit(monkeypatch: pytest.MonkeyPatch, *, stage: str) -> None:
    def fail(*_args, **_kwargs):
        raise OSError(f"injected {stage} failure")

    if stage == "fsync":
        monkeypatch.setattr(engine_module.os, "fsync", fail)
    else:
        monkeypatch.setattr(Path, "replace", fail)


@pytest.mark.parametrize("stage", ["fsync", "replace"])
@pytest.mark.parametrize("operation", ["new", "duplicate", "erased", "deferred"])
def test_failed_append_preserves_rows_audit_store_and_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, operation: str,
) -> None:
    path = tmp_path / "store.json"
    journal = tmp_path / "journal"
    policy = OperatingPolicy(self_generation_budget_max_events=1)
    with LocalMemoryEngine(path, policy=policy, journal_dir=journal) as engine:
        engine.append_evidence(evidence("An already committed source."))
        incoming = evidence("A source whose write will fail.")
        if operation in {"duplicate", "erased"}:
            cid = engine.append_evidence(incoming)
            if operation == "erased":
                engine.forget("tenant", cid)
        elif operation == "deferred":
            engine.append_evidence(evidence("Existing generated source.", actor="assistant"))
            incoming.actor = "assistant"
        cid = cid_for(incoming)
        before = engine.export_all()
        before_audit = copy.deepcopy(engine.audit_log)
        before_version = engine._store_version
        before_store = path.read_bytes()
        journal_path = journal / journal_filename("tenant")
        before_journal = journal_path.read_bytes()

        with monkeypatch.context() as failed:
            fail_commit(failed, stage=stage)
            with pytest.raises(OSError, match=f"injected {stage} failure"):
                engine.append_evidence(incoming)

        assert engine.export_all() == before
        assert engine.audit_log == before_audit
        assert engine._store_version == before_version
        assert path.read_bytes() == before_store
        assert journal_path.read_bytes() == before_journal
        if operation != "duplicate":
            assert engine.get_evidence("tenant", cid) is None

        # Retrying a failed write remains a real append, or its original safe
        # no-op; it must not mistake leaked memory for a committed duplicate.
        assert engine.append_evidence(incoming) == cid
        expected_op = {
            "new": "append_evidence",
            "duplicate": "append_evidence.noop_dedup",
            "erased": "append_evidence.blocked_erased_replay",
            "deferred": "append_evidence.self_generation_budget_deferred",
        }[operation]
        assert engine.audit_log[-1]["op"] == expected_op
        assert len(engine.audit_log) == len(before_audit) + 1
        assert (engine.get_evidence("tenant", cid) is not None) == (
            operation in {"new", "duplicate"}
        )
        assert sum(row["cid"] == cid for row in CIDJournal(journal_path).records()) == (
            0 if operation == "deferred" else 1
        )
        final = engine.export_all()
    with LocalMemoryEngine(path) as reopened:
        assert reopened.export_all() == final


@pytest.mark.parametrize("stage", ["fsync", "replace"])
def test_failed_metadata_write_restores_source_and_keeps_epoch_monotonic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    path = tmp_path / "store.json"
    with LocalMemoryEngine(path) as engine:
        cid = engine.append_evidence(evidence("The source remains at revision one."))
        before = engine.get_evidence("tenant", cid)
        before_export = engine.export_all()
        before_audit = copy.deepcopy(engine.audit_log)
        before_version = engine._store_version
        before_epoch = evidence_epoch()
        before_store = path.read_bytes()

        with monkeypatch.context() as failed:
            fail_commit(failed, stage=stage)
            with pytest.raises(OSError, match=f"injected {stage} failure"):
                engine.update_evidence_metadata(
                    "tenant", cid,
                    {"document": {"revision": 2}, "summary": {"status": "retired"}},
                )

        assert engine.get_evidence("tenant", cid) == before
        assert engine.export_all() == before_export
        assert engine.audit_log == before_audit
        assert engine._store_version == before_version
        assert evidence_epoch() > before_epoch
        assert path.read_bytes() == before_store
        assert engine.update_evidence_metadata("tenant", cid, {"document": {"revision": 2}})
        assert len(engine.audit_log) == len(before_audit) + 1
    with LocalMemoryEngine(path) as reopened:
        assert reopened.get_evidence("tenant", cid).metadata["document"] == {"revision": 2}


def test_metadata_patch_and_audit_do_not_share_mutable_input(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    with LocalMemoryEngine(path) as engine:
        cid = engine.append_evidence(evidence("A versioned source."))
        patch = {"document": {"revision": 2, "tags": ["published"]}}
        assert engine.update_evidence_metadata("tenant", cid, patch)
        committed = engine.get_evidence("tenant", cid)
        audit = copy.deepcopy(engine.audit_log)
        store = path.read_bytes()
        epoch = evidence_epoch()
        version = engine._store_version

        patch["document"]["revision"] = 999
        patch["document"]["tags"].append("caller mutation")
        assert engine.get_evidence("tenant", cid) == committed
        assert engine.audit_log == audit
        assert path.read_bytes() == store
        assert evidence_epoch() == epoch
        assert engine._store_version == version

        # An audit event is an independent historical snapshot, even if later
        # engine work changes a nested value on the current source row.
        stored = engine.evidence[engine._evidence_key("tenant", "main", cid)]
        stored.metadata["document"]["tags"].append("internal later change")
        assert engine.audit_log == audit


@pytest.mark.parametrize("operation", ["append", "metadata"])
def test_serialization_failure_does_not_publish_source_changes(
    tmp_path: Path, operation: str,
) -> None:
    path = tmp_path / "store.json"
    with LocalMemoryEngine(path) as engine:
        cid = engine.append_evidence(evidence("Existing serializable source."))
        before = engine.export_all()
        before_store = path.read_bytes()
        with pytest.raises(TypeError, match="not JSON serializable"):
            if operation == "append":
                incoming = evidence("A source with invalid metadata.")
                incoming.metadata["invalid"] = {object()}
                engine.append_evidence(incoming)
            else:
                engine.update_evidence_metadata("tenant", cid, {"invalid": {object()}})
        assert engine.export_all() == before
        assert path.read_bytes() == before_store


def test_post_commit_journal_error_does_not_undo_committed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "store.json"
    incoming = evidence("The ledger commit precedes the journal append.")
    cid = cid_for(incoming)

    def fail(*_args, **_kwargs):
        raise OSError("injected journal failure")

    with LocalMemoryEngine(path, journal_dir=tmp_path / "journal") as engine:
        monkeypatch.setattr(CIDJournal, "append", fail)
        with pytest.raises(OSError, match="injected journal failure"):
            engine.append_evidence(incoming)
        assert engine.get_evidence("tenant", cid) is not None
        assert engine.audit_log[-1]["op"] == "append_evidence"
    with LocalMemoryEngine(path) as reopened:
        assert reopened.get_evidence("tenant", cid) is not None
