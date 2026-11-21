"""Engine-native learning records with one serialized transaction per mutation."""

from __future__ import annotations

import copy
import json
import threading
from contextlib import contextmanager
from uuid import uuid4

TABLES = {
    "receipts": "learning_receipts",
    "episodes": "learning_episodes",
    "credit": "learning_credit",
    "stats": "learning_stats",
    "artifacts": "learning_artifacts",
    "defects": "learning_defects",
    "policy": "learning_policy_state",
}


def empty_state() -> dict:
    return {key: {} for key in TABLES}


class _CowDict(dict):
    """Copy-on-write dict view over an immutable cached snapshot.

    Stores immediate entries in its own C dict table so ``isinstance(x, dict)``,
    ``json.dumps``, and key lookups run at native dict speed while avoiding
    deep-copying untouched nested subtrees (such as megabytes of historical
    episode tool_events). Any mutation marks the node and its ancestors dirty
    without ever modifying ``_origin``.
    """

    __slots__ = ("_origin", "_dirty", "_on_mutate", "_wrapped_all")

    def __init__(self, origin: dict, on_mutate=None):
        dict.__init__(self, origin)
        self._origin = origin
        self._dirty = False
        self._on_mutate = on_mutate
        self._wrapped_all = False

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            cb = self._on_mutate
            if cb is not None:
                cb()

    def _wrap_entry(self, key, value):
        t = type(value)
        if t is dict:
            wrapped = _CowDict(value, self._mark_dirty)
            dict.__setitem__(self, key, wrapped)
            return wrapped
        if t is list:
            wrapped = _CowList(value, self._mark_dirty)
            dict.__setitem__(self, key, wrapped)
            return wrapped
        return value

    def _ensure_wrapped_all(self) -> None:
        if self._wrapped_all:
            return
        for key, value in list(dict.items(self)):
            t = type(value)
            if t is dict:
                dict.__setitem__(self, key, _CowDict(value, self._mark_dirty))
            elif t is list:
                dict.__setitem__(self, key, _CowList(value, self._mark_dirty))
        self._wrapped_all = True

    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        return self._wrap_entry(key, value)

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return self[key]
        return default

    def values(self):
        self._ensure_wrapped_all()
        return dict.values(self)

    def items(self):
        self._ensure_wrapped_all()
        return dict.items(self)

    def __setitem__(self, key, value) -> None:
        self._mark_dirty()
        self._wrapped_all = False
        dict.__setitem__(self, key, value)

    def __delitem__(self, key) -> None:
        self._mark_dirty()
        dict.__delitem__(self, key)

    def pop(self, key, *args):
        if dict.__contains__(self, key):
            value = self._wrap_entry(key, dict.__getitem__(self, key))
            self._mark_dirty()
            dict.__delitem__(self, key)
            return value
        return dict.pop(self, key, *args)

    def popitem(self):
        key, value = dict.popitem(self)
        self._mark_dirty()
        t = type(value)
        if t is dict:
            return key, _CowDict(value, None)
        if t is list:
            return key, _CowList(value, None)
        return key, value

    def clear(self) -> None:
        if dict.__len__(self):
            self._mark_dirty()
            self._wrapped_all = True
            dict.clear(self)

    def update(self, *args, **kwargs) -> None:
        if args or kwargs:
            self._mark_dirty()
            self._wrapped_all = False
            dict.update(self, *args, **kwargs)

    def setdefault(self, key, default=None):
        if dict.__contains__(self, key):
            return self[key]
        self._mark_dirty()
        self._wrapped_all = False
        dict.__setitem__(self, key, default)
        return default

    def __ior__(self, other):
        if other:
            self._mark_dirty()
            self._wrapped_all = False
            return dict.__ior__(self, other)
        return self

    def copy(self) -> dict:
        self._ensure_wrapped_all()
        return dict(dict.items(self))

    def __eq__(self, other) -> bool:
        if not self._dirty:
            if isinstance(other, _CowDict) and not other._dirty and self._origin is other._origin:
                return True
            if other is self._origin:
                return True
        return dict.__eq__(self, other)

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def __deepcopy__(self, memo) -> dict:
        out: dict = {}
        memo[id(self)] = out
        for k, v in dict.items(self):
            out[copy.deepcopy(k, memo)] = copy.deepcopy(v, memo)
        return out


class _CowList(list):
    """Copy-on-write list view paired with :class:`_CowDict`."""

    __slots__ = ("_origin", "_dirty", "_on_mutate", "_wrapped_all")

    def __init__(self, origin: list, on_mutate=None):
        list.__init__(self, origin)
        self._origin = origin
        self._dirty = False
        self._on_mutate = on_mutate
        self._wrapped_all = False

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            cb = self._on_mutate
            if cb is not None:
                cb()

    def _wrap_index(self, idx: int):
        value = list.__getitem__(self, idx)
        t = type(value)
        if t is dict:
            wrapped = _CowDict(value, self._mark_dirty)
            list.__setitem__(self, idx, wrapped)
            return wrapped
        if t is list:
            wrapped = _CowList(value, self._mark_dirty)
            list.__setitem__(self, idx, wrapped)
            return wrapped
        return value

    def _ensure_wrapped_all(self) -> None:
        if self._wrapped_all:
            return
        for idx in range(list.__len__(self)):
            self._wrap_index(idx)
        self._wrapped_all = True

    def __getitem__(self, index):
        if isinstance(index, slice):
            self._ensure_wrapped_all()
            return list.__getitem__(self, index)
        return self._wrap_index(index)

    def __iter__(self):
        self._ensure_wrapped_all()
        return list.__iter__(self)

    def __setitem__(self, index, value) -> None:
        self._mark_dirty()
        self._wrapped_all = False
        list.__setitem__(self, index, value)

    def __delitem__(self, index) -> None:
        self._mark_dirty()
        list.__delitem__(self, index)

    def append(self, value) -> None:
        self._mark_dirty()
        self._wrapped_all = False
        list.append(self, value)

    def extend(self, values) -> None:
        items = list(values)
        if items:
            self._mark_dirty()
            self._wrapped_all = False
            list.extend(self, items)

    def insert(self, index: int, value) -> None:
        self._mark_dirty()
        self._wrapped_all = False
        list.insert(self, index, value)

    def pop(self, index: int = -1):
        value = self._wrap_index(index)
        self._mark_dirty()
        list.__delitem__(self, index)
        return value

    def remove(self, value) -> None:
        self._mark_dirty()
        list.remove(self, value)

    def clear(self) -> None:
        if list.__len__(self):
            self._mark_dirty()
            self._wrapped_all = True
            list.clear(self)

    def reverse(self) -> None:
        if list.__len__(self) > 1:
            self._mark_dirty()
            list.reverse(self)

    def sort(self, *args, **kwargs) -> None:
        if list.__len__(self) > 1:
            self._mark_dirty()
            list.sort(self, *args, **kwargs)

    def __iadd__(self, other):
        self.extend(other)
        return self

    def __imul__(self, n: int):
        if list.__len__(self) and n != 1:
            self._mark_dirty()
            self._wrapped_all = False
        return list.__imul__(self, n)

    def copy(self) -> list:
        self._ensure_wrapped_all()
        return list(list.__iter__(self))

    def __eq__(self, other) -> bool:
        if not self._dirty:
            if isinstance(other, _CowList) and not other._dirty and self._origin is other._origin:
                return True
            if other is self._origin:
                return True
        return list.__eq__(self, other)

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def __deepcopy__(self, memo) -> list:
        out: list = []
        memo[id(self)] = out
        for item in list.__iter__(self):
            out.append(copy.deepcopy(item, memo))
        return out


def _to_plain(value):
    """Unwrap copy-on-write views back to plain dicts/lists, reusing clean origins in O(1)."""
    if isinstance(value, _CowDict):
        if not value._dirty:
            return value._origin
        return {k: _to_plain(v) for k, v in dict.items(value)}
    if isinstance(value, _CowList):
        if not value._dirty:
            return value._origin
        return [_to_plain(v) for v in list.__iter__(value)]
    t = type(value)
    if t is dict:
        return {k: _to_plain(v) for k, v in value.items()}
    if t is list:
        return [_to_plain(v) for v in value]
    return value


def _wrap_state_cow(snapshot: dict) -> dict:
    return {key: _CowDict(snapshot[key]) for key in TABLES}


class LearningStore:
    def __init__(self, engine):
        self.engine = engine
        self.lock = getattr(engine, "_lock", None) or engine.__dict__.setdefault(
            "_learning_lock", threading.RLock()
        )
        self.backend = (
            "sqlite"
            if hasattr(engine, "_tenant_db_path")
            else ("postgres" if hasattr(engine, "dsn") else "local")
        )

    def _sqlite_cache(self) -> dict:
        cache = self.engine.__dict__.get("_learning_state_cache")
        if cache is None:
            cache = {}
            self.engine.__dict__["_learning_state_cache"] = cache
        return cache

    @staticmethod
    def _sqlite_learning_revision(conn, tenant: str) -> int | None:
        try:
            row = conn.execute(
                "SELECT revision FROM learning_revisions WHERE tenant_id = ?",
                (tenant,),
            ).fetchone()
        except Exception:
            return None
        return int(row[0]) if row is not None else 0

    @staticmethod
    def _load_sqlite_state(conn, tenant: str) -> dict:
        state = empty_state()
        for key, table in TABLES.items():
            for row in conn.execute(
                f"SELECT record_key, payload FROM {table} WHERE tenant_id=?",
                (tenant,),
            ):
                state[key][row[0]] = json.loads(row[1])
        return state

    def _cached_sqlite_snapshot(self, conn, tenant: str, *, nested: bool) -> dict:
        if nested:
            return self._load_sqlite_state(conn, tenant)
        rev = self._sqlite_learning_revision(conn, tenant)
        cache = self._sqlite_cache()
        cached = cache.get(tenant)
        if cached is not None and cached["conn_id"] == id(conn):
            if rev is not None and rev > 0 and cached["rev"] == rev:
                return cached["snapshot"]
            if cached["rev"] == rev:
                dv = int(conn.execute("PRAGMA data_version").fetchone()[0])
                if cached["fp"] == (conn.total_changes, dv):
                    return cached["snapshot"]
        snapshot = self._load_sqlite_state(conn, tenant)
        dv = int(conn.execute("PRAGMA data_version").fetchone()[0])
        cache[tenant] = {
            "conn_id": id(conn),
            "rev": rev,
            "fp": (conn.total_changes, dv),
            "snapshot": snapshot,
        }
        return snapshot

    @contextmanager
    def transaction(self, tenant: str):
        with self.lock:
            if self.backend == "local":
                if not hasattr(self.engine, "_learning_data"):
                    self.engine._learning_data = {}
                state = copy.deepcopy(
                    self.engine._learning_data.get(tenant, empty_state())
                )
                yield state, None
                return
            if self.backend == "sqlite":
                with self.engine._lock:
                    conn = self.engine._connect(tenant)
                    nested = conn.in_transaction
                    if nested and getattr(conn, "_source_guard", None) is None:
                        raise RuntimeError(
                            "learning cannot join an unmanaged transaction"
                        )
                    if not nested:
                        conn.execute("BEGIN IMMEDIATE")
                    pending_snapshot = None
                    try:
                        snapshot = self._cached_sqlite_snapshot(conn, tenant, nested=nested)
                        state = _wrap_state_cow(snapshot)
                        self._pending_save = None
                        yield state, conn
                        pending_snapshot = self._pending_save
                        self._pending_save = None
                        if not nested:
                            conn.commit()
                            if pending_snapshot is not None:
                                rev = self._sqlite_learning_revision(conn, tenant)
                                dv = int(conn.execute("PRAGMA data_version").fetchone()[0])
                                self._sqlite_cache()[tenant] = {
                                    "conn_id": id(conn),
                                    "rev": rev,
                                    "fp": (conn.total_changes, dv),
                                    "snapshot": pending_snapshot,
                                }
                        elif pending_snapshot is not None:
                            # Inside a nested source_transaction: invalidate cache until committed.
                            self._sqlite_cache().pop(tenant, None)
                    except BaseException:
                        self._pending_save = None
                        self._sqlite_cache().pop(tenant, None)
                        if nested:
                            conn._source_guard["failed"] = True
                        else:
                            conn.rollback()
                        raise
                return
            from mnemosyne.postgres_engine import _stable_uuid

            db_tenant = _stable_uuid("tenant", tenant)
            with self.engine._source_connection(tenant, "main") as conn:
                with conn.cursor() as cursor:
                    self.engine._set_tenant(cursor, db_tenant)
                    cursor.execute(
                        "INSERT INTO tenants(id,name) VALUES (%s,%s) ON CONFLICT(id) DO NOTHING",
                        (db_tenant, tenant),
                    )
                    self.engine._lock_working_tenant(cursor, tenant)
                    state = empty_state()
                    for key, table in TABLES.items():
                        cursor.execute(
                            f"SELECT record_key, payload FROM {table} WHERE tenant_id=%s",
                            (db_tenant,),
                        )
                        for record_key, payload in cursor.fetchall():
                            state[key][record_key] = payload
                    yield state, cursor

    def save(
        self,
        tenant: str,
        before: dict,
        state: dict,
        handle,
        event: dict,
        *,
        erasure_terms=None,
    ) -> None:
        """Only LearningWriter calls this method, while holding transaction()."""
        if erasure_terms:
            self._revoke_audit_keys(state, erasure_terms)
            event = self._redacted(event)
        else:
            event = self._seal_event(state, event)
        if self.backend == "local":
            old = self.engine._learning_data.get(tenant)
            audit_size = len(self.engine.audit_log)
            self.engine._learning_data[tenant] = copy.deepcopy(state)
            self.engine._audit(
                tenant, "learning", event["op"], event["id"], event, source="experience"
            )
            try:
                self.engine._persist()
            except BaseException:
                if old is None:
                    self.engine._learning_data.pop(tenant, None)
                else:
                    self.engine._learning_data[tenant] = old
                del self.engine.audit_log[audit_size:]
                raise
            return
        db_tenant = tenant
        if self.backend == "postgres":
            from mnemosyne.postgres_engine import _stable_uuid

            db_tenant = _stable_uuid("tenant", tenant)
        placeholder = "?" if self.backend == "sqlite" else "%s"
        next_snapshot = {} if self.backend == "sqlite" else None
        for key, table in TABLES.items():
            col_state = state[key]
            col_before = before[key]
            if isinstance(col_state, _CowDict) and not col_state._dirty and col_state._origin is col_before:
                if next_snapshot is not None:
                    next_snapshot[key] = col_before
                continue
            updated_col = dict(col_before) if next_snapshot is not None else None
            for record_key in col_before.keys() - col_state.keys():
                handle.execute(
                    f"DELETE FROM {table} WHERE tenant_id={placeholder} AND record_key={placeholder}",
                    (db_tenant, record_key),
                )
                if updated_col is not None:
                    updated_col.pop(record_key, None)
            for record_key, payload in dict.items(col_state):
                old_val = col_before.get(record_key)
                if isinstance(payload, _CowDict) and not payload._dirty and payload._origin is old_val:
                    continue
                if isinstance(payload, _CowList) and not payload._dirty and payload._origin is old_val:
                    continue
                if old_val is payload or old_val == payload:
                    continue
                plain_payload = _to_plain(payload)
                serialized = json.dumps(plain_payload, sort_keys=True, allow_nan=False)
                if self.backend == "postgres":
                    serialized = self.engine._jsonb(plain_payload)
                handle.execute(
                    f"INSERT INTO {table}(tenant_id,record_key,payload) VALUES ({placeholder},{placeholder},{placeholder}) "
                    "ON CONFLICT(tenant_id,record_key) DO UPDATE SET payload=excluded.payload",
                    (db_tenant, record_key, serialized),
                )
                if updated_col is not None:
                    updated_col[record_key] = plain_payload
            if next_snapshot is not None:
                next_snapshot[key] = updated_col
        if self.backend == "sqlite":
            self.engine._audit_row(
                handle,
                tenant,
                "learning",
                event["op"],
                event["id"],
                event,
                source="experience",
            )
            self._pending_save = next_snapshot
        else:
            self.engine._audit(
                handle,
                db_tenant,
                "learning",
                event["op"],
                event["id"],
                event,
                source="experience",
            )

    def read(self, tenant: str) -> dict:
        if self.backend == "sqlite":
            with self.lock, self.engine._lock:
                conn = self.engine._connect(tenant)
                nested = conn.in_transaction
                snapshot = self._cached_sqlite_snapshot(conn, tenant, nested=nested)
                return _wrap_state_cow(snapshot)
        with self.transaction(tenant) as (state, _):
            return state  # transaction() already hands out a private copy on every backend

    def history(self, tenant: str) -> list[dict]:
        with self.lock:
            if self.backend == "local":
                rows = self.engine.audit_log
            elif self.backend == "sqlite":
                with self.engine._lock:
                    rows = [
                        json.loads(row[0])
                        for row in self.engine._connect(tenant).execute(
                            "SELECT record FROM audit_log WHERE tenant_id=? ORDER BY seq",
                            (tenant,),
                        )
                    ]
            else:
                from mnemosyne.postgres_engine import _stable_uuid

                with (
                    self.engine._source_connection(tenant, "main", read=True) as conn,
                    conn.cursor() as cursor,
                ):
                    db_tenant = _stable_uuid("tenant", tenant)
                    self.engine._set_tenant(cursor, db_tenant)
                    cursor.execute(
                        "SELECT diff FROM audit_log WHERE tenant_id=%s AND actor=%s ORDER BY at",
                        (db_tenant, "learning"),
                    )
                    events = [
                        row[0]
                        for row in cursor.fetchall()
                        if row[0].get("source") == "experience"
                    ]
                state = self.read(tenant)
                return [self._open_event(state, event) for event in events]
            state = self.read(tenant)
            return [
                self._open_event(state, row["diff"])
                for row in rows
                if row.get("tenant_id") == tenant and row.get("source") == "experience"
            ]

    @staticmethod
    def _redacted(event: dict) -> dict:
        from .receipts import digest

        return {
            "id": event["id"],
            "op": event["op"],
            "revision": event["revision"],
            "created_at": event["created_at"],
            "erased": True,
            "changes": [],
            "redacted_payload_hash": digest(event),
        }

    @staticmethod
    def _references(value, field="") -> set[str]:
        from .receipts import digest

        if isinstance(value, dict):
            return set().union(
                *(LearningStore._references(item, key) for key, item in value.items()),
                set(),
            )
        if isinstance(value, (list, tuple)):
            return set().union(
                *(LearningStore._references(item, field) for item in value), set()
            )
        if isinstance(value, str) and (field.endswith("id") or field.endswith("ids")):
            return {digest(value)}
        return set()

    @staticmethod
    def _seal_event(state: dict, event: dict) -> dict:
        import zlib
        from cryptography.fernet import Fernet
        from .receipts import digest

        sealed = copy.deepcopy(event)
        keyring = state["policy"].setdefault("audit_keys", {})
        slots = state["policy"].setdefault("audit_key_slots", {})
        for change in sealed["changes"]:
            if change["collection"] == "policy" and change["key"] in {
                "audit_keys",
                "audit_key_slots",
            }:
                continue
            slot = digest([change["collection"], change["key"]])
            key_id = slots.get(slot)
            if key_id not in keyring:
                key_id = str(uuid4())
                slots[slot] = key_id
                keyring[key_id] = {
                    "secret": Fernet.generate_key().decode(),
                    "references": [],
                }
            key = keyring[key_id]
            references = LearningStore._references(change) | {digest(change["key"])}
            key["references"] = sorted(set(key["references"]) | references)
            cipher = Fernet(key["secret"].encode())
            for side in ("before", "after"):
                value = change[side]
                if value is not None:
                    raw = json.dumps(value, sort_keys=True).encode()
                    change[side] = {
                        "sealed": cipher.encrypt(
                            zlib.compress(raw, level=6)
                        ).decode(),
                        "key_id": key_id,
                    }
        # Encryption keys are canonical state only and never enter the audit log.
        sealed["changes"] = [
            change
            for change in sealed["changes"]
            if not (
                change["collection"] == "policy"
                and change["key"] in {"audit_keys", "audit_key_slots"}
            )
        ]
        sealed["encryption"] = "fernet-zlib-v2"
        return sealed

    @staticmethod
    def _open_event(state: dict, event: dict) -> dict:
        import zlib
        from cryptography.fernet import Fernet

        opened = copy.deepcopy(event)
        compressed = opened.get("encryption") == "fernet-zlib-v2"
        for change in opened.get("changes", []):
            for side in ("before", "after"):
                value = change.get(side)
                if not isinstance(value, dict) or "sealed" not in value:
                    continue
                key = state["policy"].get("audit_keys", {}).get(value["key_id"])
                if key is None:
                    change[side] = None
                    change["redacted"] = True
                    opened["erased"] = True
                else:
                    plaintext = Fernet(key["secret"].encode()).decrypt(
                        value["sealed"].encode()
                    )
                    if compressed:
                        plaintext = zlib.decompress(plaintext)
                    change[side] = json.loads(plaintext)
        return opened

    @staticmethod
    def _revoke_audit_keys(state: dict, terms: list[str]) -> None:
        from .receipts import digest

        references = {digest(term) for term in terms}
        keyring = state["policy"].get("audit_keys", {})
        for key_id, key in list(keyring.items()):
            if references.intersection(key["references"]):
                del keyring[key_id]
                for slot, generation in list(
                    state["policy"].get("audit_key_slots", {}).items()
                ):
                    if generation == key_id:
                        del state["policy"]["audit_key_slots"][slot]
