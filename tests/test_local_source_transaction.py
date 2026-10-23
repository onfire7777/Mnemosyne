"""Interrupted source replacement must leave a usable, unchanged local ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.journal import CIDJournal, journal_filename
from mnemosyne.models import Assertion, Evidence
from mnemosyne.privacy import ErasureMode


def source(text="old source", **changes):
    return Evidence(tenant_id="tenant", user_id="owner", actor="user",
                    source_type="document", content=text, **changes)


def test_source_transaction_commits_once_and_supports_nested_reads(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    with LocalMemoryEngine(path, journal_dir=tmp_path / "journal") as engine:
        old = engine.append_evidence(source())
        before = path.read_bytes()
        writes = []
        real_replace = Path.replace

        def count_replace(target, destination):
            writes.append(destination)
            return real_replace(target, destination)

        monkeypatch.setattr(Path, "replace", count_replace)
        with engine.source_transaction("tenant"):
            new = engine.append_evidence(source("new source"))
            with engine.source_transaction("tenant"):
                assert engine.update_evidence_metadata("tenant", new, {"revision": 2})
                assert engine.get_evidence("tenant", new).metadata["revision"] == 2
            assert engine.forget("tenant", old)["erased"]
            assert path.read_bytes() == before
        assert writes == [path]
        assert engine.get_evidence("tenant", old) is None
        assert engine.get_evidence("tenant", new) is not None
        final = engine.export_all()
    with LocalMemoryEngine(path) as reopened:
        assert reopened.export_all() == final


@pytest.mark.parametrize("failure", ["raised", "caught_nested", "caught_scope", "caught_validation", "unsupported"])
def test_interrupted_replacement_restores_sources_projections_audit_and_journal(tmp_path, failure):
    path = tmp_path / "memory.json"
    journal_path = tmp_path / "journal" / journal_filename("tenant")
    with LocalMemoryEngine(path, journal_dir=journal_path.parent) as engine:
        cid = engine.append_evidence(source())
        engine.upsert_assertion(Assertion(tenant_id="tenant", subject="observatory",
            predicate="opens", object="Tuesday", source_evidence_cids=[cid], status="active"))
        before = engine.export_all()
        store_bytes, journal_bytes = path.read_bytes(), journal_path.read_bytes()
        with pytest.raises((RuntimeError, ValueError)):
            with engine.source_transaction("tenant"):
                engine.append_evidence(source("replacement"))
                engine.forget("tenant", cid)
                if failure == "raised":
                    raise ValueError("interrupted replacement")
                try:
                    if failure == "caught_nested":
                        with engine.source_transaction("tenant"):
                            raise ValueError("nested interruption")
                    elif failure == "caught_scope":
                        engine.get_evidence("another-tenant", cid)
                    elif failure == "caught_validation":
                        engine.update_evidence_metadata("tenant", cid, {"access_policy": {}})
                    else:
                        engine.upsert_assertion(Assertion(tenant_id="tenant", subject="unsupported",
                            predicate="must", object="rollback", status="active"))
                except (ValueError, RuntimeError):
                    pass
        assert engine.export_all() == before
        assert path.read_bytes() == store_bytes
        assert journal_path.read_bytes() == journal_bytes
        with engine.source_transaction("tenant"):
            retry = engine.append_evidence(source("retry works"))
        assert engine.get_evidence("tenant", retry) is not None
    with LocalMemoryEngine(path) as reopened:
        assert reopened.get_evidence("tenant", cid) is not None
        assert reopened.get_evidence("tenant", retry) is not None


def test_failed_final_persistence_rolls_back_and_can_retry(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    with LocalMemoryEngine(path) as engine:
        cid = engine.append_evidence(source())
        before, disk = engine.export_all(), path.read_bytes()
        with monkeypatch.context() as failed:
            def fail(*args, **kwargs):
                raise OSError("injected final rename failure")
            failed.setattr(Path, "replace", fail)
            with pytest.raises(OSError, match="final rename"):
                with engine.source_transaction("tenant"):
                    engine.forget("tenant", cid)
                    engine.append_evidence(source("replacement"))
        assert engine.export_all() == before
        assert path.read_bytes() == disk
        assert not path.with_suffix(".json.tmp").exists()
        with engine.source_transaction("tenant"):
            engine.forget("tenant", cid)
        assert engine.get_evidence("tenant", cid) is None


@pytest.mark.parametrize("outer", ["source", "model", "deferred"])
def test_incompatible_guard_nesting_fails_without_poisoning_engine(tmp_path, outer):
    with LocalMemoryEngine(tmp_path / "memory.json") as engine:
        if outer == "source":
            with pytest.raises(RuntimeError, match="mental_model_guard"):
                with engine.source_transaction("tenant"):
                    with engine.mental_model_guard("tenant"):
                        pass
        elif outer == "model":
            with engine.mental_model_guard("tenant"):
                with pytest.raises(RuntimeError, match="mental_model_guard"):
                    with engine.source_transaction("tenant"):
                        pass
        else:
            with engine.defer_persistence():
                with pytest.raises(RuntimeError, match="defer_persistence"):
                    with engine.source_transaction("tenant"):
                        pass
        with engine.source_transaction("tenant"):
            cid = engine.append_evidence(source())
        assert engine.get_evidence("tenant", cid) is not None


@pytest.mark.parametrize("mode", [ErasureMode.TOMBSTONE_RECOMPUTE, ErasureMode.HARD_DELETE_LEGAL])
@pytest.mark.parametrize("batch", [False, True])
def test_local_forget_removes_plaintext_from_journal(tmp_path, mode, batch):
    path = tmp_path / "memory.json"
    journal_path = tmp_path / "journal" / journal_filename("tenant")
    with LocalMemoryEngine(path, journal_dir=journal_path.parent) as engine:
        if batch:
            with engine.source_transaction("tenant"):
                cid = engine.append_evidence(source("erase this journal plaintext"))
                engine.forget("tenant", cid, erasure_mode=mode, requested_by="legal")
        else:
            cid = engine.append_evidence(source("erase this journal plaintext"))
            engine.forget("tenant", cid, erasure_mode=mode, requested_by="legal")
        assert "erase this journal plaintext" not in journal_path.read_text()
        records = list(CIDJournal(journal_path).records())
        if mode is ErasureMode.HARD_DELETE_LEGAL or batch:
            assert records == []
        else:
            assert records[0]["erased"] is True
            assert records[0]["cid"] == cid


def test_journal_failure_after_forget_does_not_undo_committed_erasure(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    with LocalMemoryEngine(path, journal_dir=tmp_path / "journal") as engine:
        cid = engine.append_evidence(source("sensitive source"))
        def fail(*args, **kwargs):
            raise OSError("injected journal failure")
        monkeypatch.setattr(CIDJournal, "tombstone", fail)
        with pytest.raises(OSError, match="journal failure"):
            with engine.source_transaction("tenant"):
                engine.forget("tenant", cid)
        assert engine.get_evidence("tenant", cid) is None
    with LocalMemoryEngine(path) as reopened:
        assert reopened.get_evidence("tenant", cid) is None


@pytest.mark.parametrize("mode", [ErasureMode.TOMBSTONE_RECOMPUTE, ErasureMode.HARD_DELETE_LEGAL])
@pytest.mark.parametrize("batch", [False, True])
def test_journal_preserves_live_branch_until_final_copy_erased(tmp_path, mode, batch):
    path = tmp_path / "memory.json"
    journal_path = tmp_path / "journal" / journal_filename("tenant")
    with LocalMemoryEngine(path, journal_dir=journal_path.parent) as engine:
        cid = engine.append_evidence(source("shared branch source"))
        engine.branch("draft", tenant_id="tenant")
        if batch:
            with engine.source_transaction("tenant", "draft"):
                engine.forget("tenant", cid, "draft", erasure_mode=mode, requested_by="legal")
        else:
            engine.forget("tenant", cid, "draft", erasure_mode=mode, requested_by="legal")
        assert engine.get_evidence("tenant", cid) is not None
        assert "shared branch source" in journal_path.read_text()
        engine.forget("tenant", cid, erasure_mode=mode, requested_by="legal")
        assert "shared branch source" not in journal_path.read_text()


def test_failed_journal_append_still_processes_later_erasure(tmp_path, monkeypatch):
    path = tmp_path / "memory.json"
    journal_path = tmp_path / "journal" / journal_filename("tenant")
    with LocalMemoryEngine(path, journal_dir=journal_path.parent) as engine:
        cid = engine.append_evidence(source("old private source"))
        def fail(*args, **kwargs):
            raise OSError("injected append failure")
        monkeypatch.setattr(CIDJournal, "append", fail)
        with pytest.raises(OSError, match="append failure"):
            with engine.source_transaction("tenant"):
                engine.append_evidence(source("new independent source"))
                engine.forget("tenant", cid)
        assert engine.get_evidence("tenant", cid) is None
        assert "old private source" not in journal_path.read_text()


def test_invalid_model_guard_also_poison_source_transaction(tmp_path):
    with LocalMemoryEngine(tmp_path / "memory.json") as engine:
        with pytest.raises(RuntimeError, match="aborted"):
            with engine.source_transaction("tenant"):
                cid = engine.append_evidence(source())
                try:
                    with engine.mental_model_guard(""):
                        pass
                except (RuntimeError, ValueError):
                    pass
        assert engine.get_evidence("tenant", cid) is None
