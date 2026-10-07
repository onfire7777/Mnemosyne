"""BranchIndexedStore views must equal filtered scans of the full dict, in the same order."""

from __future__ import annotations

import copy
import pickle
import random
from dataclasses import dataclass

import pytest

from mnemosyne.branch_index import BranchIndexedStore, indexed
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Relation

TENANTS = ["t1", "t2", "t3"]
BRANCHES = ["main", "canary-a", "canary-b", "scratch"]
WORDS = ["alpha", "beta", "gamma"]


@dataclass
class Item:
    tenant_id: str
    branch: str
    subject: str
    predicate: str
    source: str
    target: str
    n: int


def _item(rng: random.Random, n: int) -> Item:
    return Item(rng.choice(TENANTS), rng.choice(BRANCHES), rng.choice(WORDS), rng.choice(WORDS),
                rng.choice(WORDS), rng.choice(WORDS), n)


def _check(store: BranchIndexedStore, kind: str | None) -> None:
    items = list(dict.items(store))
    for tenant in TENANTS + [None]:
        for branch in BRANCHES:
            expected = [(k, v) for k, v in items if v.branch == branch and (tenant is None or v.tenant_id == tenant)]
            assert list(store.branch_view(tenant, branch).items()) == expected
            if tenant is not None:
                assert list(store.in_branch(tenant, branch).items()) == expected
        if tenant is not None:
            assert list(store.of_tenant(tenant).items()) == [(k, v) for k, v in items if v.tenant_id == tenant]
    for branch in BRANCHES:
        assert list(store.in_any_branch(branch).items()) == [(k, v) for k, v in items if v.branch == branch]
    if kind == "assertion":
        for t in TENANTS:
            for b in BRANCHES:
                for s in WORDS:
                    for p in WORDS:
                        expected = [(k, v) for k, v in items
                                    if (v.tenant_id, v.branch, v.subject, v.predicate) == (t, b, s, p)]
                        assert list(store.peers(t, b, s, p).items()) == expected
    if kind == "relation":
        for t in TENANTS:
            for b in BRANCHES:
                for s in WORDS:
                    for p in WORDS:
                        for o in WORDS:
                            expected = [(k, v) for k, v in items
                                        if (v.tenant_id, v.branch, v.source, v.predicate, v.target) == (t, b, s, p, o)]
                            assert list(store.peers(t, b, s, p, o).items()) == expected


@pytest.mark.parametrize("kind", [None, "assertion", "relation"])
@pytest.mark.parametrize("seed", range(8))
def test_views_equal_filtered_scans_under_random_operations(kind: str | None, seed: int) -> None:
    rng = random.Random(seed)
    store = BranchIndexedStore(kind=kind)
    reference: dict[str, Item] = {}
    for step in range(400):
        op = rng.random()
        key = f"k{rng.randrange(60)}"
        if op < 0.45:
            item = _item(rng, step)
            store[key] = item
            reference[key] = item
        elif op < 0.55 and key in reference:
            # Same key, same slots: must keep its position.
            old = reference[key]
            item = Item(old.tenant_id, old.branch, old.subject, old.predicate, old.source, old.target, step)
            store[key] = item
            reference[key] = item
        elif op < 0.7:
            if key in reference:
                del store[key]
                del reference[key]
            else:
                with pytest.raises(KeyError):
                    del store[key]
        elif op < 0.78:
            assert store.pop(key, None) is reference.pop(key, None)
        elif op < 0.82 and reference:
            assert store.popitem() == reference.popitem()
        elif op < 0.88:
            batch = {f"k{rng.randrange(60)}": _item(rng, step) for _ in range(3)}
            store.update(batch)
            reference.update(batch)
        elif op < 0.93:
            item = _item(rng, step)
            assert store.setdefault(key, item) is reference.setdefault(key, item)
        elif op < 0.96:
            store = copy.deepcopy(store) if rng.random() < 0.5 else pickle.loads(pickle.dumps(store))
            reference = {k: store[k] for k in reference}
        elif op < 0.97:
            store.clear()
            reference.clear()
        assert list(dict.items(store)) == list(reference.items())
        _check(store, kind)


def test_engine_wraps_assigned_maps_and_keeps_their_order() -> None:
    engine = LocalMemoryEngine()
    a = Assertion(tenant_id="t", subject="s", predicate="p", object="o")
    b = Assertion(tenant_id="t", subject="s", predicate="p", object="q", branch="x")
    engine.assertions = {"t:main:1": a, "t:x:2": b}
    assert isinstance(engine.assertions, BranchIndexedStore)
    assert list(engine.assertions) == ["t:main:1", "t:x:2"]
    assert list(engine.assertions.peers("t", "main", "s", "p").values()) == [a]
    engine.relations = {}
    engine.relations["t:main:r"] = Relation(tenant_id="t", source="s", predicate="p", target="o")
    assert list(engine.relations.peers("t", "main", "s", "p", "o"))== ["t:main:r"]
    assert indexed(engine.evidence, "evidence") is engine.evidence
