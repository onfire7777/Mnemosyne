from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.journal import CIDJournal, journal_filename
from mnemosyne.models import Evidence


def test_local_append_rejects_journal_alias_before_ledger_mutation(
    tmp_path: Path,
) -> None:
    owner = "../owner"
    alias = journal_filename(owner).removesuffix(".journal")
    engine = LocalMemoryEngine(journal_dir=tmp_path)

    def evidence(tenant: str) -> Evidence:
        return Evidence(
            tenant_id=tenant,
            user_id="user",
            actor="user",
            source_type="chat",
            content="private owner memory",
            access_policy={"tenant": tenant},
        )

    cid = engine.append_evidence(evidence(owner))
    path = tmp_path / journal_filename(owner)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="tenant ownership"):
        engine.append_evidence(evidence(alias))
    assert path.read_bytes() == original
    assert all(item.tenant_id != alias for item in engine.evidence.values())
    assert engine.get_evidence(owner, cid) is not None


@pytest.mark.parametrize("operation", ["append", "purge", "tombstone"])
@pytest.mark.parametrize("torn_tail", [False, True])
def test_journal_rejects_wrong_owner_without_modification(
    tmp_path: Path, operation: str, torn_tail: bool
) -> None:
    journal = CIDJournal(tmp_path / "owner.journal")
    journal.append({"cid": "private", "tenant_id": "owner"})
    if torn_tail:
        with journal.path.open("ab") as stream:
            stream.write(b'{"cid":"incomplete')
    original = journal.path.read_bytes()
    with pytest.raises(ValueError, match="tenant ownership"):
        if operation == "append":
            journal.append({"cid": "other", "tenant_id": "other"})
        elif operation == "purge":
            journal.purge("private", tenant_id="other")
        else:
            journal.tombstone(
                "private", salted_hash="hash", erased_at="now", tenant_id="other"
            )
    assert journal.path.read_bytes() == original


def test_journal_owner_can_reopen_and_legacy_untagged_records_remain_supported(
    tmp_path: Path,
) -> None:
    path = tmp_path / "owner.journal"
    CIDJournal(path).append({"cid": "legacy"})
    CIDJournal(path).append({"cid": "first", "tenant_id": "owner"})
    CIDJournal(path).append({"cid": "second", "tenant_id": "owner"})
    assert [row["cid"] for row in CIDJournal(path).records()] == [
        "legacy",
        "first",
        "second",
    ]


def test_concurrent_first_appends_cannot_mix_journal_tenants(tmp_path: Path) -> None:
    path = tmp_path / "shared.journal"
    barrier = Barrier(2)

    def append(tenant: str) -> bool:
        journal = CIDJournal(path)
        barrier.wait(timeout=5)
        try:
            journal.append({"cid": tenant, "tenant_id": tenant})
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, ["first", "second"]))
    assert sorted(results) == [False, True]
    assert len(list(CIDJournal(path).records())) == 1


def test_separate_local_engines_reject_alias_before_losing_ledger_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = "../owner"
    alias = journal_filename(owner).removesuffix(".journal")
    first = LocalMemoryEngine(journal_dir=tmp_path)
    second = LocalMemoryEngine(journal_dir=tmp_path)
    first_persisting = Event()
    release_first = Event()
    second_started = Event()

    def paused_persist() -> None:
        first_persisting.set()
        assert release_first.wait(5)

    monkeypatch.setattr(first, "_persist", paused_persist)

    def append(engine: LocalMemoryEngine, tenant: str) -> str:
        if engine is second:
            second_started.set()
        return engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id="user",
                actor="user",
                source_type="chat",
                content="private memory",
                access_policy={"tenant": tenant},
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(append, first, owner)
        assert first_persisting.wait(5)
        loser = executor.submit(append, second, alias)
        try:
            assert second_started.wait(5)
            # The owner is paused before its journal append. The second writer
            # must wait at admission instead of entering its ledger mutation.
            from concurrent.futures import TimeoutError

            with pytest.raises(TimeoutError):
                loser.result(timeout=0.25)
        finally:
            release_first.set()
        winner.result(timeout=5)
        with pytest.raises(ValueError, match="tenant ownership"):
            loser.result(timeout=5)
    assert second.evidence == {}
    assert second.audit_log == []
    assert {
        row["tenant_id"]
        for row in CIDJournal(tmp_path / journal_filename(owner)).records()
    } == {owner}
