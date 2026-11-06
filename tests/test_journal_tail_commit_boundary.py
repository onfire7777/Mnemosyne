import json
from pathlib import Path

import pytest

from mnemosyne.journal import CIDJournal


def test_complete_json_without_commit_newline_is_a_torn_tail(tmp_path: Path) -> None:
    path = tmp_path / "tenant.journal"
    journal = CIDJournal(path)
    journal.append({"cid": "committed"})
    with path.open("ab") as stream:
        stream.write(b'{"cid":"uncommitted"}')
    original = path.read_bytes()

    assert list(journal.records()) == [{"cid": "committed"}]
    divergence = journal.verify_against({"committed", "uncommitted"})
    assert divergence.torn_tail is True
    assert divergence.missing_from_journal == ["uncommitted"]
    assert path.read_bytes() == original

    journal.append({"cid": "next"})
    assert list(journal.records()) == [{"cid": "committed"}, {"cid": "next"}]
    assert not journal.verify_against({"committed", "next"}).diverged


@pytest.mark.parametrize("operation", ["records", "verify", "purge", "tombstone"])
def test_corrupt_newline_terminated_tail_is_not_silently_discarded(
    tmp_path: Path, operation: str
) -> None:
    path = tmp_path / "tenant.journal"
    journal = CIDJournal(path)
    journal.append({"cid": "committed"})
    with path.open("ab") as stream:
        stream.write(b'{"cid": invalid-json}\n')
    original = path.read_bytes()

    with pytest.raises(json.JSONDecodeError):
        if operation == "records":
            list(journal.records())
        elif operation == "verify":
            journal.verify_against({"committed"})
        elif operation == "purge":
            journal.purge("unrelated")
        else:
            journal.tombstone("unrelated", salted_hash="hash", erased_at="2026-09-04")

    assert path.read_bytes() == original
