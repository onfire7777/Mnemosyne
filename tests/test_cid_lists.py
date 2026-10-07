"""Shared source lists and the evidence epoch (mnemosyne.cid_lists)."""

from __future__ import annotations

import copy
import pickle
from dataclasses import asdict

import pytest

from mnemosyne.cid_lists import CidList, evidence_epoch, intern_cids
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Relation


def test_interned_lists_are_shared_read_only_and_copy_free() -> None:
    first = intern_cids(["b", "a", "c"])
    again = intern_cids(iter(["b", "a", "c"]))
    assert type(first) is CidList and first is again and first == ["b", "a", "c"]
    assert intern_cids(["a", "b", "c"]) is not first  # order is part of the content
    assert intern_cids(first) is first
    assert copy.copy(first) is first and copy.deepcopy(first) is first
    for mutate in (
        lambda x: x.append("d"), lambda x: x.extend(["d"]), lambda x: x.insert(0, "d"),
        lambda x: x.remove("a"), lambda x: x.pop(), lambda x: x.clear(), lambda x: x.sort(),
        lambda x: x.reverse(), lambda x: x.__setitem__(0, "d"), lambda x: x.__delitem__(0),
        lambda x: x.__iadd__(["d"]), lambda x: x.__imul__(2),
    ):
        with pytest.raises(TypeError):
            mutate(first)
    assert first == ["b", "a", "c"]
    # Built directly (as asdict and copy helpers do), it is an ordinary list.
    assert type(CidList(["x"])) is list
    assert type(first + ["d"]) is list and type(sorted(first)) is list and type(list(first)) is list
    restored = pickle.loads(pickle.dumps(first))
    assert restored is first
    assert intern_cids([["unhashable"]]) == [["unhashable"]] and type(intern_cids([["unhashable"]])) is list


def test_shared_maps_are_read_only_copy_free_and_serialise_plain() -> None:
    from mnemosyne.cid_lists import SharedMap, shared_map

    shared = shared_map({"a": "grounded", "b": "unknown"})
    assert type(shared) is SharedMap and shared == {"a": "grounded", "b": "unknown"}
    assert copy.copy(shared) is shared and copy.deepcopy({"x": shared})["x"] is shared
    for mutate in (lambda m: m.__setitem__("c", 1), lambda m: m.__delitem__("a"), lambda m: m.clear(),
                   lambda m: m.pop("a"), lambda m: m.popitem(), lambda m: m.setdefault("c", 1),
                   lambda m: m.update(c=1), lambda m: m.__ior__({"c": 1})):
        with pytest.raises(TypeError):
            mutate(shared)
    assert type(SharedMap({"x": 1})) is dict
    assert type(pickle.loads(pickle.dumps(shared))) is dict


def test_rows_store_shared_lists_and_serialise_plain_lists() -> None:
    engine = LocalMemoryEngine()
    sources = ["c2", "c1"]
    engine.upsert_assertion(Assertion(tenant_id="t", subject="s", predicate="p", object="o", source_evidence_cids=sources))
    engine.add_relation(Relation(tenant_id="t", source="s", predicate="p", target="o", source_evidence_cids=list(sources)))
    stored = next(iter(engine.assertions.values()))
    relation = next(iter(engine.relations.values()))
    assert type(stored.source_evidence_cids) is CidList and stored.source_evidence_cids is relation.source_evidence_cids
    assert type(stored.to_dict()["source_evidence_cids"]) is list
    assert type(asdict(relation)["source_evidence_cids"]) is list
    sources.append("c3")  # the caller's own list is never shared
    assert stored.source_evidence_cids == ["c2", "c1"]
    # Reinforcing replaces the list with a new shared one instead of mutating it.
    engine.upsert_assertion(Assertion(tenant_id="t", subject="s", predicate="p", object="o", source_evidence_cids=["c0"]))
    assert stored.source_evidence_cids == ["c0", "c1", "c2"] and type(stored.source_evidence_cids) is CidList
    assert relation.source_evidence_cids == ["c2", "c1"]


def test_evidence_epoch_moves_on_every_change_to_a_stored_row_only() -> None:
    engine = LocalMemoryEngine()
    free = Evidence(tenant_id="t", user_id="u", actor="user", source_type="note", content="hello")
    before = evidence_epoch()
    free.metadata = {"x": 1}  # not in a store: nobody can have cached it
    assert evidence_epoch() == before
    cid = engine.append_evidence(free)
    assert evidence_epoch() > before
    row = engine.evidence[engine._evidence_key("t", "main", cid)]
    mark = evidence_epoch()
    clone = copy.deepcopy(row)
    clone.metadata = {}  # a copy is not the stored row
    assert evidence_epoch() == mark
    row.metadata = {**row.metadata, "quarantine_reason": "x"}
    assert evidence_epoch() > mark
    mark = evidence_epoch()
    engine.evidence.pop(engine._evidence_key("t", "main", cid))
    assert evidence_epoch() > mark
    mark = evidence_epoch()
    row.metadata = {}  # no longer stored
    assert evidence_epoch() == mark


def _security_inputs(engine: LocalMemoryEngine, relation: Relation) -> dict:
    return dict(branch="main", include_quarantined=False, max_trust=5, max_sensitivity=3,
                access_context={"tenant_id": "t", "branch": "main"})


def test_relation_security_memo_equals_the_computation_and_sees_evidence_changes() -> None:
    engine = LocalMemoryEngine()
    cids = [
        engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="note",
                                        content=f"source {i}", source_identity=f"s{i}"))
        for i in range(4)
    ]
    engine.add_relation(Relation(tenant_id="t", source="a", predicate="links", target="b", source_evidence_cids=cids))
    relation = next(iter(engine.relations.values()))
    inputs = _security_inputs(engine, relation)
    expected = engine._relation_hit_security_compute(relation, **inputs)[0]
    first = engine._relation_hit_security(relation, **inputs)
    assert first == expected
    assert engine._relation_hit_security(relation, **inputs) is first  # served from the memo
    # A canary branch name does not split the memo: the rows read are main's.
    assert engine._relation_hit_security(relation, **{**inputs, "access_context": {"tenant_id": "t", "branch": "x"}}) is first
    # Any change to a cited row invalidates it.
    row = engine.evidence[engine._evidence_key("t", "main", cids[2])]
    row.metadata = {**row.metadata, "quarantine_reason": "poisoned"}
    assert engine._relation_hit_security(relation, **inputs) is None
    assert engine._relation_hit_security_compute(relation, **inputs)[0] is None
    # A wall-clock dependent policy is never cached.
    row.metadata = {key: value for key, value in row.metadata.items() if key != "quarantine_reason"}
    row.access_policy = {**row.access_policy, "expires_at": "2999-01-01T00:00:00Z"}
    one = engine._relation_hit_security(relation, **inputs)
    assert one == engine._relation_hit_security_compute(relation, **inputs)[0]
    assert engine._relation_hit_security(relation, **inputs) is not one
