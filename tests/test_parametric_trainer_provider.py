from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRAINER = REPO_ROOT / "infra" / "providers" / "parametric-trainer.py"

_CID_A = "a" * 64  # content-addressed evidence cid (64-hex)
_CID_B = "b" * 64
_UUID = "11111111-2222-3333-4444-555555555555"  # lesson/procedure provenance id


def _load_trainer():
    spec = importlib.util.spec_from_file_location("mnemosyne_parametric_trainer", TRAINER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return list(self._rows)


def test_train_split_allow_only_treats_evidence_cids_as_a_filter() -> None:
    trainer = _load_trainer()
    # No source ids -> no restriction (train on the whole tenant corpus).
    assert trainer._train_split_allow(None) is None
    assert trainer._train_split_allow([]) is None
    # Provenance ids (lesson/procedure UUIDs from propose_from_lessons) are NOT
    # evidence cids -> they must not restrict the corpus to nothing.
    assert trainer._train_split_allow([_UUID, "provider-health"]) is None
    # A genuine evidence-cid train split still filters (eval isolation preserved).
    assert trainer._train_split_allow([_CID_A]) == {_CID_A}
    # Mixed input keeps only the evidence cids as the filter.
    assert trainer._train_split_allow([_CID_A, _UUID]) == {_CID_A}


def test_load_training_rows_ignores_provenance_ids_but_honours_cid_splits() -> None:
    trainer = _load_trainer()
    corpus = [
        (_CID_A, 5, "[0.1, 0.2, 0.3]"),
        (_CID_B, 0, "[0.4, 0.5, 0.6]"),
    ]

    # propose_from_lessons forwards lesson/procedure UUIDs; the trainer must still
    # see the tenant's full embedded corpus (previously this filtered to 0 rows and
    # failed closed with "insufficient training evidence", breaking the MCP
    # parametric_propose tool and the provider-check parametric sub-check).
    provenance = trainer._load_training_rows(_FakeCursor(corpus), [_UUID])
    assert {r["cid_hex"] for r in provenance} == {_CID_A, _CID_B}
    assert {r["label"] for r in provenance} == {0, 1}

    # A real evidence-cid train split still restricts the corpus (eval isolation).
    split = trainer._load_training_rows(_FakeCursor(corpus), [_CID_A])
    assert [r["cid_hex"] for r in split] == [_CID_A]

    # All-zero embeddings carry no signal and are dropped.
    zero = trainer._load_training_rows(_FakeCursor([(_CID_A, 5, "[0, 0, 0]")]), None)
    assert zero == []
