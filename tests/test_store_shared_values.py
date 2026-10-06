"""Compact persistence of shared source lists (engine._SharedValueEncoder)."""

from __future__ import annotations

import json
from pathlib import Path

from mnemosyne.cid_lists import CidList, SharedMap
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Relation


def _legacy_payload(engine: LocalMemoryEngine) -> str:
    """The store text as _persist wrote it before shared values: every row via to_dict()."""
    data = {
        "policy": engine.policy.to_dict(),
        "branches": engine.branches,
        "evidence": [item.to_dict() for item in engine.evidence.values()],
        "assertions": [item.to_dict() for item in engine.assertions.values()],
        "relations": [item.to_dict() for item in engine.relations.values()],
        "preferences": [item.to_dict() for item in engine.preferences.values()],
        "justifications": [item.to_dict() for item in engine.justifications.values()],
        "contradictions": [item.to_dict() for item in engine.contradictions.values()],
        "calibrations": [item.to_dict() for item in engine.calibrations.values()],
        "entities": list(engine.entities.values()),
        "intentions": [item.to_dict() for item in engine.intentions.values()],
        "working_memory": [item.to_dict() for item in engine.working_memory.values()],
        "audit_log": engine.audit_log,
        "deletion_log": engine.deletion_log,
        "merge_log": engine.merge_log,
    }
    return json.dumps(data, indent=2, sort_keys=True)


def _fill(engine: LocalMemoryEngine, documents: int) -> list[str]:
    cids = [
        engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="note",
                                        content=f"document {i}", source_identity=f"doc{i}"))
        for i in range(documents)
    ]
    for i in range(6):
        engine.upsert_assertion(Assertion(tenant_id="t", subject=f"s{i}", predicate="is", object="o",
                                          source_evidence_cids=list(cids)))
        engine.add_relation(Relation(tenant_id="t", source=f"s{i}", predicate="links", target="o",
                                     source_evidence_cids=list(cids)))
    return cids


def test_small_stores_are_written_byte_for_byte_as_before(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    engine = LocalMemoryEngine(store_path=store)
    _fill(engine, 5)  # lists below the sharing threshold stay inline
    assert store.read_text(encoding="utf-8") == _legacy_payload(engine)


def test_large_shared_lists_are_written_once_and_reload_shared(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    engine = LocalMemoryEngine(store_path=store)
    cids = _fill(engine, 40)
    text = store.read_text(encoding="utf-8")
    legacy = _legacy_payload(engine)
    assert len(text) < len(legacy)
    # A cited CID is written a fixed number of times however many rows cite it.
    assert text.count(cids[-1]) <= 6 < legacy.count(cids[-1])
    data = json.loads(text)
    assert data["shared_values"]["cid_lists"] and data["shared_values"]["maps"]
    del engine
    reloaded = LocalMemoryEngine(store_path=store, read_only=True)
    rows = list(reloaded.assertions.values()) + list(reloaded.relations.values())
    shared = {id(row.source_evidence_cids) for row in rows}
    assert len(shared) == 1 and type(rows[0].source_evidence_cids) is CidList
    monitoring = rows[0].calibration["reality_monitoring"]
    assert type(monitoring["source_classes"]) is SharedMap and len(monitoring["source_classes"]) == 40


def _fill_orderings(engine: LocalMemoryEngine, documents: int) -> list[str]:
    """What batch consolidation stores: each document's facts cite every CID, own CID first."""
    cids = [
        engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="note",
                                        content=f"document {i}", source_identity=f"doc{i}"))
        for i in range(documents)
    ]
    # Documents are promoted out of order, so the first list written is not the batch order.
    for i, own in enumerate(cids[12:] + cids[:12]):
        ordering = list(dict.fromkeys([own, *cids]))
        engine.upsert_assertion(Assertion(tenant_id="t", subject=f"s{i}", predicate="is", object="o",
                                          source_evidence_cids=ordering))
        engine.add_relation(Relation(tenant_id="t", source=f"s{i}", predicate="links", target="o",
                                     source_evidence_cids=ordering))
    return cids


def test_orderings_of_one_cid_set_are_written_as_fronts_over_one_list(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    engine = LocalMemoryEngine(store_path=store)
    cids = _fill_orderings(engine, 30)
    expected = json.loads(_legacy_payload(engine))
    data = json.loads(store.read_text(encoding="utf-8"))
    table = data["shared_values"]["cid_lists"]
    fronts = [entry for entry in table if isinstance(entry, dict)]
    full = [entry for entry in table if isinstance(entry, list)]
    # 30 orderings of the same 30 CIDs: one written in full, the rest as one-CID fronts.
    assert len(fronts) >= 28 and all(len(entry["front"]) <= 1 for entry in fronts)
    assert sum(entry.count(cids[-1]) for entry in full) <= 2
    del engine
    reloaded = LocalMemoryEngine(store_path=store, read_only=True)
    assert json.loads(_legacy_payload(reloaded)) == expected
    for row in reloaded.assertions.values():
        assert type(row.source_evidence_cids) is CidList


def test_front_encoding_round_trips_arbitrary_lists() -> None:
    import random

    from mnemosyne.cid_lists import intern_cids
    from mnemosyne.engine import _decode_shared_values, _SharedValueEncoder

    rng = random.Random(7)
    for _ in range(300):
        universe = [f"c{i}" for i in range(rng.randint(16, 40))]
        values = []
        for _ in range(rng.randint(1, 6)):
            members = rng.sample(universe, rng.randint(16, len(universe)))
            if rng.random() < 0.5 and values:
                # A short front over an earlier list (the shape consolidation produces) ...
                base = list(rng.choice(values))
                front = rng.sample(base, rng.randint(0, 3))
                members = front + [item for item in base if item not in front]
            elif rng.random() < 0.3:
                rng.shuffle(members)  # ... or an unrelated ordering, possibly with repeats.
                members = members + members[: rng.randint(0, 2)]
            values.append(intern_cids(members))
        encoder = _SharedValueEncoder()
        encoded = encoder.encode({"rows": [{"cids": value} for value in values]})
        decoded = _decode_shared_values(
            json.loads(json.dumps(encoded)), json.loads(json.dumps({"cid_lists": encoder.lists}))
        )
        assert [row["cids"] for row in decoded["rows"]] == [list(value) for value in values]
        assert all(row["cids"] is value for row, value in zip(decoded["rows"], values, strict=True))


def test_reloaded_state_equals_the_state_written(tmp_path: Path) -> None:
    store = tmp_path / "store.json"
    engine = LocalMemoryEngine(store_path=store)
    _fill(engine, 40)
    expected = json.loads(_legacy_payload(engine))
    del engine
    reloaded = LocalMemoryEngine(store_path=store, read_only=True)
    assert json.loads(_legacy_payload(reloaded)) == expected
