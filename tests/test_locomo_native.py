"""Synthetic native capture tests through the public subprocess boundary."""
import json
from pathlib import Path

import pytest

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters.locomo import LoCoMoError
from eval.public.adapters.locomo_native import captured_conversations


def sample(identity):
    return {"sample_id": identity, "conversation": {
        "session_1_date_time": "Synthetic date", "session_1": [
            {"dia_id": "D1:1", "speaker": "A", "text": "violet synthetic kite"},
            {"dia_id": "D1:2", "speaker": "A", "text": "violet synthetic kite"}]},
        "qa": [{"question": "what?", "answer": "SECRET_LABEL", "category": 4, "evidence": ["D1:1"]}]}


def test_native_public_capture_is_isolated_verified_and_label_free(tmp_path):
    parent_store = tmp_path / "untouched.json"
    cli = MnemoCLI(store=str(parent_store), timeout_s=30)
    with captured_conversations([sample("one"), sample("two")], cli,
                                caption_policy="exclude-caption") as conversations:
        stores = [Path(row["cli"].store) for row in conversations]
        assert len(set(stores)) == 2 and all(path.exists() for path in stores)
        first, second = conversations
        assert first["tenant_id"] != second["tenant_id"]
        assert set(first["evidence"]).isdisjoint(second["evidence"])
        for row in conversations:
            assert len(row["evidence"]) == 2
            assert "SECRET_LABEL" not in json.dumps(row["evidence"])
            assert row["explicit_lifecycle_operations"] == []
            result = row["cli"].search(row["tenant_id"], "violet")
            assert {hit["id"] for hit in result["hits"]} == set(row["evidence"])
        foreign = first["cli"].search(second["tenant_id"], "violet")
        assert foreign["hits"] == []
    assert not parent_store.exists()
    assert all(not path.exists() for path in stores)


@pytest.mark.parametrize("result", [{"results": []}, {"results": [{"cid": "wrong"}, {"cid": "wrong"}]}])
def test_native_capture_rejects_invalid_receipts_before_yield(monkeypatch, result, tmp_path):
    monkeypatch.setattr(MnemoCLI, "capture_batch", lambda *args: result)
    with pytest.raises(LoCoMoError, match="capture"):
        with captured_conversations([sample("one")], MnemoCLI(store=str(tmp_path / "unused")),
                                    caption_policy="exclude-caption"):
            pytest.fail("invalid receipt must not reach caller")
