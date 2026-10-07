"""Branch-scoped indexes for the in-memory engine's evidence, assertion and relation maps.

``LocalMemoryEngine`` keeps every item of every tenant and branch in one flat ``dict`` keyed
``"tenant:branch:id"``, and almost every operation used to walk the whole dict to find the
few items of one tenant/branch, or the peers of one assertion. With batch consolidation
creating a canary branch per fact, those walks made ingest super-linear.

``BranchIndexedStore`` is that same dict - same keys, same values, same iteration order -
that also maintains ordered sub-views:

* ``in_branch(tenant, branch)``  items of one tenant on one branch;
* ``in_any_branch(branch)``      items of every tenant on one branch;
* ``of_tenant(tenant)``          items of one tenant on every branch;
* ``peers(*key)``                assertions sharing tenant/branch/subject/predicate, or
                                 relations sharing tenant/branch/source/predicate/target.

Every view lists its items in the SAME relative order as iterating the full dict and
filtering, so replacing a filtered scan with a view is byte-for-byte equivalent. Index keys
are read from the item at insertion; the engine sets ``branch`` before it stores an item and
never reassigns tenant, branch, subject, predicate, source or target afterwards.

Views are live and must not be mutated; copy them (``list(...)``) before mutating the store
while iterating.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from mnemosyne.cid_lists import bump_evidence_epoch, track_evidence, untrack_evidence

_MISSING = object()
_EMPTY: dict[str, Any] = {}


def _assertion_peer(item: Any) -> tuple[Any, ...]:
    return (item.tenant_id, item.branch, item.subject, item.predicate)


def _relation_peer(item: Any) -> tuple[Any, ...]:
    return (item.tenant_id, item.branch, item.source, item.predicate, item.target)


_PEER_KEYS = {"assertion": _assertion_peer, "relation": _relation_peer, "evidence": None, None: None}


def _rebuild(kind: str | None, items: list[tuple[str, Any]]) -> "BranchIndexedStore":
    return BranchIndexedStore(items, kind=kind)


class BranchIndexedStore(dict):
    """A ``dict`` of engine items that keeps ordered per-branch, per-tenant and peer views."""

    __slots__ = ("_kind", "_peer_of", "_branch", "_branch_any", "_tenant", "_peer", "_where")

    def __init__(self, items: Mapping[str, Any] | Iterable[tuple[str, Any]] = (), *, kind: str | None = None):
        super().__init__()
        self._kind = kind
        self._peer_of = _PEER_KEYS[kind]
        self._branch: dict[tuple[Any, Any], dict[str, Any]] = {}
        self._branch_any: dict[Any, dict[str, Any]] = {}
        self._tenant: dict[Any, dict[str, Any]] = {}
        self._peer: dict[tuple[Any, ...], dict[str, Any]] = {}
        # key -> the index slots it sits in, recorded at insertion.
        self._where: dict[str, tuple[Any, ...]] = {}
        source = items.items() if isinstance(items, Mapping) else items
        for key, item in source:
            self[key] = item

    # ------------------------------------------------------------------ index upkeep

    def _slots_for(self, item: Any) -> tuple[Any, ...]:
        tenant = getattr(item, "tenant_id", None)
        branch = getattr(item, "branch", None)
        peer = self._peer_of(item) if self._peer_of is not None else None
        return (tenant, branch, peer)

    def _buckets(self, where: tuple[Any, ...]) -> list[dict[str, Any]]:
        tenant, branch, peer = where
        buckets = [
            self._branch.setdefault((tenant, branch), {}),
            self._branch_any.setdefault(branch, {}),
            self._tenant.setdefault(tenant, {}),
        ]
        if peer is not None:
            buckets.append(self._peer.setdefault(peer, {}))
        return buckets

    def _drop(self, key: str, where: tuple[Any, ...]) -> None:
        tenant, branch, peer = where
        for table, slot in ((self._branch, (tenant, branch)), (self._branch_any, branch), (self._tenant, tenant),
                            (self._peer, peer)):
            if slot is None and table is self._peer:
                continue
            bucket = table.get(slot)
            if bucket is not None:
                bucket.pop(key, None)
                if not bucket:
                    del table[slot]

    def _reorder(self, where: tuple[Any, ...]) -> None:
        # A key moved to new slots keeps its place in the dict, so the buckets it joined are
        # rebuilt in dict order. Never happens on the engine's own paths; kept for exactness.
        for bucket in self._buckets(where):
            ordered = {key: dict.__getitem__(self, key) for key in self if key in bucket}
            bucket.clear()
            bucket.update(ordered)

    # ------------------------------------------------------------------ dict protocol

    def __setitem__(self, key: str, item: Any) -> None:
        where = self._slots_for(item)
        old = self._where.get(key)
        if self._kind == "evidence":
            # Evidence changes invalidate per-list caches (mnemosyne.cid_lists).
            previous = dict.get(self, key, _MISSING)
            if previous is not item:
                if previous is not _MISSING:
                    untrack_evidence(previous)
                track_evidence(item)
            bump_evidence_epoch()
        dict.__setitem__(self, key, item)
        self._where[key] = where
        if old is None:
            for bucket in self._buckets(where):
                bucket[key] = item
        elif old == where:
            for bucket in self._buckets(where):
                bucket[key] = item  # existing key: keeps its position, like the dict
        else:
            self._drop(key, old)
            for bucket in self._buckets(where):
                bucket[key] = item
            self._reorder(where)

    def __delitem__(self, key: str) -> None:
        item = dict.__getitem__(self, key)
        dict.__delitem__(self, key)
        self._drop(key, self._where.pop(key))
        if self._kind == "evidence":
            untrack_evidence(item)
            bump_evidence_epoch()

    def pop(self, key: str, default: Any = _MISSING) -> Any:
        if key in self:
            item = dict.__getitem__(self, key)
            del self[key]
            return item
        if default is _MISSING:
            raise KeyError(key)
        return default

    def popitem(self) -> tuple[str, Any]:
        key, item = dict.popitem(self)
        self._drop(key, self._where.pop(key))
        if self._kind == "evidence":
            untrack_evidence(item)
            bump_evidence_epoch()
        return key, item

    def clear(self) -> None:
        if self._kind == "evidence":
            for item in dict.values(self):
                untrack_evidence(item)
            bump_evidence_epoch()
        dict.clear(self)
        for table in (self._branch, self._branch_any, self._tenant, self._peer, self._where):
            table.clear()

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self:
            return dict.__getitem__(self, key)
        self[key] = default
        return default

    def update(self, *args: Any, **kwargs: Any) -> None:
        for key, item in dict(*args, **kwargs).items():
            self[key] = item

    def __ior__(self, other: Any) -> "BranchIndexedStore":
        self.update(other)
        return self

    def copy(self) -> "BranchIndexedStore":
        return BranchIndexedStore(self, kind=self._kind)

    __copy__ = copy

    def __deepcopy__(self, memo: dict[int, Any]) -> "BranchIndexedStore":
        clone = BranchIndexedStore(kind=self._kind)
        memo[id(self)] = clone
        for key, item in dict.items(self):
            clone[copy.deepcopy(key, memo)] = copy.deepcopy(item, memo)
        return clone

    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild, (self._kind, list(dict.items(self))))

    # ------------------------------------------------------------------ views

    def in_branch(self, tenant_id: Any, branch: Any) -> Mapping[str, Any]:
        return self._branch.get((tenant_id, branch), _EMPTY)

    def in_any_branch(self, branch: Any) -> Mapping[str, Any]:
        return self._branch_any.get(branch, _EMPTY)

    def of_tenant(self, tenant_id: Any) -> Mapping[str, Any]:
        return self._tenant.get(tenant_id, _EMPTY)

    def peers(self, *key: Any) -> Mapping[str, Any]:
        return self._peer.get(tuple(key), _EMPTY)

    def branch_view(self, tenant_id: Any, branch: Any) -> Mapping[str, Any]:
        """Items on ``branch`` for one tenant, or for every tenant when ``tenant_id`` is None."""
        return self.in_any_branch(branch) if tenant_id is None else self.in_branch(tenant_id, branch)

    def select(self, tenant_id: Any = None, branch: Any = None) -> Mapping[str, Any]:
        """Items filtered by tenant and/or branch; a None filter means every value."""
        if tenant_id is None and branch is None:
            return self
        if tenant_id is None:
            return self.in_any_branch(branch)
        if branch is None:
            return self.of_tenant(tenant_id)
        return self.in_branch(tenant_id, branch)


def indexed(value: Any, kind: str | None) -> BranchIndexedStore:
    """Wrap a plain mapping assigned to an engine store, keeping its order."""
    if isinstance(value, BranchIndexedStore) and value._kind == kind:
        return value
    return BranchIndexedStore(value if value is not None else {}, kind=kind)
