"""Shared source-evidence lists and the evidence-change epoch.

A consolidated batch stamps every fact and relation it promotes with the batch's source list
(consolidation unions the work CIDs into every candidate, so a batch of N documents gives
every one of its facts all N sources). Thousands of rows then hold the same thousands of CIDs.

``CidList`` lets those rows hold ONE shared, read-only list:

* copying or deep-copying a row never copies its sources (``copy``/``deepcopy`` return the
  list itself), and
* anything computed purely from a list and the evidence rows it names - access decisions,
  reality classes, independent-corroboration reports - can be computed once per list and
  reused for as long as no evidence row changes (``evidence_epoch``).

A shared list is read-only: mutating it raises ``TypeError``, so no row can change another
row's sources; a row that needs different sources is assigned a new list. Building a
``CidList`` directly (as ``dataclasses.asdict`` and copy helpers do) returns a plain ``list``;
only ``intern_cids`` makes shared lists, and it returns the same object for equal content.

The evidence epoch is a process-wide counter that moves whenever an evidence row that sits in
an engine store is added, replaced, removed or has any attribute assigned. A cached value
computed at epoch E is valid while the epoch is still E.
"""

from __future__ import annotations

import weakref
from collections.abc import Iterable
from functools import partial
from typing import Any

__all__ = [
    "CidList",
    "SharedMap",
    "intern_cids",
    "shared_map",
    "shared_or_copy",
    "evidence_epoch",
    "bump_evidence_epoch",
    "track_evidence",
    "untrack_evidence",
    "evidence_tracked",
    "evidence_caching_safe",
]


class CidList(list):
    """A read-only list of evidence CIDs shared by many rows (see the module docstring)."""

    __slots__ = ("__weakref__",)

    def __new__(cls, *args: Any, _shared: bool = False) -> Any:
        if not _shared:
            # dataclasses.asdict, copy helpers and any other caller get an ordinary list.
            return list(*args)
        return super().__new__(cls)

    def __init__(self, values: Iterable[Any] = (), *, _shared: bool = False) -> None:
        list.__init__(self, values)

    def _read_only(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("a shared source-evidence CID list is read-only; assign a new list instead")

    append = extend = insert = remove = pop = clear = sort = reverse = _read_only
    __setitem__ = __delitem__ = __iadd__ = __imul__ = _read_only

    def __copy__(self) -> CidList:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> CidList:
        return self

    def __reduce__(self) -> tuple[Any, ...]:
        return (intern_cids, (list(self),))


class SharedMap(dict):
    """A read-only dict shared by many rows (e.g. per-CID reality classes of a shared list).

    Same contract as ``CidList``: mutating it raises, ``copy``/``deepcopy`` return it, and
    building one directly (as ``dataclasses.asdict`` does) returns a plain ``dict``.
    """

    __slots__ = ("__weakref__",)

    def __new__(cls, *args: Any, _shared: bool = False, **kwargs: Any) -> Any:
        if not _shared:
            return dict(*args, **kwargs)
        return super().__new__(cls)

    def __init__(self, *args: Any, _shared: bool = False, **kwargs: Any) -> None:
        dict.__init__(self, *args, **kwargs)

    def _read_only(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("a shared map is read-only; build a new dict instead")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _read_only

    def __copy__(self) -> SharedMap:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> SharedMap:
        return self

    def __reduce__(self) -> tuple[Any, ...]:
        return (dict, (dict(self),))


def shared_map(values: Any) -> SharedMap:
    """A read-only shared copy of ``values``."""
    return SharedMap(values, _shared=True)


def shared_or_copy(values: Iterable[Any]) -> list[Any]:
    """A private copy of a list - or a shared read-only ``CidList`` itself, which needs none."""
    return values if type(values) is CidList else list(values)


# content hash -> weak references to the live shared lists with that hash
_INTERNED: dict[int, list[weakref.ref[CidList]]] = {}


def _forget_interned(digest: int, ref: weakref.ref[CidList]) -> None:
    bucket = _INTERNED.get(digest)
    if bucket is None:
        return
    try:
        bucket.remove(ref)
    except ValueError:
        pass
    if not bucket:
        _INTERNED.pop(digest, None)


def intern_cids(values: Iterable[Any]) -> list[Any]:
    """The shared read-only list equal to ``values`` (same elements, same order).

    Returns ``values`` itself when it already is a shared list. Members that cannot be hashed
    make the list unshareable; a private plain list is returned for those.
    """
    if type(values) is CidList:
        return values
    items = list(values)
    try:
        digest = hash(tuple(items))
    except TypeError:
        return items
    bucket = _INTERNED.get(digest)
    if bucket:
        for ref in bucket:
            existing = ref()
            if existing is not None and list.__eq__(existing, items):
                return existing
    shared = CidList(items, _shared=True)
    _INTERNED.setdefault(digest, []).append(weakref.ref(shared, partial(_forget_interned, digest)))
    return shared


# ---------------------------------------------------------------------- evidence epoch


class _Epoch:
    __slots__ = ("value", "untracked")

    def __init__(self) -> None:
        self.value = 0
        # Evidence stored without being trackable: changes to it cannot be seen, so no
        # cache may trust the epoch while any such row is live in a store.
        self.untracked = 0


_EPOCH = _Epoch()

# id(evidence) -> (weak reference, number of stores holding it)
_TRACKED: dict[int, tuple[weakref.ref[Any], int]] = {}


def evidence_epoch() -> int:
    return _EPOCH.value


def bump_evidence_epoch() -> None:
    _EPOCH.value += 1


def evidence_caching_safe() -> bool:
    """False while an untrackable evidence row is stored (its changes would be invisible)."""
    return _EPOCH.untracked == 0


def _drop_dead(key: int, ref: weakref.ref[Any]) -> None:
    entry = _TRACKED.get(key)
    if entry is not None and entry[0] is ref:
        del _TRACKED[key]


def track_evidence(item: Any) -> None:
    """``item`` now sits in an engine store: its attribute writes move the epoch."""
    key = id(item)
    entry = _TRACKED.get(key)
    if entry is not None and entry[0]() is item:
        _TRACKED[key] = (entry[0], entry[1] + 1)
        return
    try:
        ref = weakref.ref(item, partial(_drop_dead, key))
    except TypeError:
        _EPOCH.untracked += 1
        return
    _TRACKED[key] = (ref, 1)


def untrack_evidence(item: Any) -> None:
    """``item`` left one engine store."""
    key = id(item)
    entry = _TRACKED.get(key)
    if entry is None or entry[0]() is not item:
        try:
            weakref.ref(item)
        except TypeError:
            _EPOCH.untracked = max(0, _EPOCH.untracked - 1)
        return
    if entry[1] <= 1:
        del _TRACKED[key]
    else:
        _TRACKED[key] = (entry[0], entry[1] - 1)


def evidence_tracked(item: Any) -> bool:
    entry = _TRACKED.get(id(item))
    return entry is not None and entry[0]() is item
