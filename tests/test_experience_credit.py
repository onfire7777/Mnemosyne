import copy

from mnemosyne.experience.runtime import LearningRuntime, stat_key
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Hit
from mnemosyne.algorithms import rrf_fuse


def test_weighted_fusion_default_is_unchanged_and_weight_changes_rank():
    a = Hit(
        id="a",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="a",
        score=1,
        channel="lexical",
        provenance=[],
        trust_tier=0,
        sensitivity=0,
        metadata={},
    )
    b = copy.deepcopy(a)
    b.id, b.channel = "b", "graph_ppr"
    baseline = rrf_fuse([[a], [b]], 2, rrf_k=60)
    explicit = rrf_fuse([[a], [b]], 2, rrf_k=60, channel_weights=None)
    assert [h.to_dict() for h in baseline] == [h.to_dict() for h in explicit]
    weighted = rrf_fuse(
        [[a], [b]], 2, rrf_k=60, channel_weights={"lexical": 0.1, "graph": 0.6}
    )
    assert weighted[0].id == "b"


def test_outcome_updates_only_comparable_eligible_targets():
    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    state["episodes"]["e"] = {
        "id": "e",
        "task_class": "x",
        "reward": 1.0,
        "rpe": 0.5,
        "receipt_ids": ["r"],
        "turn_index": 0,
        "resolved_at": "2026-11-05T00:00:00+00:00",
        "signals": [],
    }
    state["receipts"]["r"] = {
        "created_at": "2026-11-05T00:00:00+00:00",
        "turn_index": 0,
        "items": [],
        "eligible_targets": [{"kind": "item", "item_id": "eligible", "revision": 1}],
    }
    state["artifacts"]["future"] = {
        "id": "future",
        "kind": "procedure",
        "revision": 1,
        "task_class": "x",
        "state": "probation",
    }
    runtime._credit(state, state["episodes"]["e"])
    assert stat_key("item", "eligible", 1, "x") in state["stats"]
    assert stat_key("procedure", "future", 1, "x") not in state["stats"]
