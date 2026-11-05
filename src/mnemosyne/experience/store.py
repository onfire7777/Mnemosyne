"""Engine-native learning records with one serialized transaction per mutation."""

from __future__ import annotations

import copy
import json
import threading
from contextlib import contextmanager

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
                    try:
                        state = empty_state()
                        for key, table in TABLES.items():
                            for row in conn.execute(
                                f"SELECT record_key, payload FROM {table} WHERE tenant_id=?",
                                (tenant,),
                            ):
                                state[key][row[0]] = json.loads(row[1])
                        yield state, conn
                        if not nested:
                            conn.commit()
                    except BaseException:
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
        for key, table in TABLES.items():
            for record_key in before[key].keys() - state[key].keys():
                handle.execute(
                    f"DELETE FROM {table} WHERE tenant_id={placeholder} AND record_key={placeholder}",
                    (db_tenant, record_key),
                )
            for record_key, payload in state[key].items():
                if before[key].get(record_key) == payload:
                    continue
                serialized = json.dumps(payload, sort_keys=True, allow_nan=False)
                if self.backend == "postgres":
                    serialized = self.engine._jsonb(payload)
                handle.execute(
                    f"INSERT INTO {table}(tenant_id,record_key,payload) VALUES ({placeholder},{placeholder},{placeholder}) "
                    "ON CONFLICT(tenant_id,record_key) DO UPDATE SET payload=excluded.payload",
                    (db_tenant, record_key, serialized),
                )
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
        with self.transaction(tenant) as (state, _):
            return copy.deepcopy(state)

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
                from uuid import uuid4

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
                    change[side] = {
                        "sealed": cipher.encrypt(
                            json.dumps(value, sort_keys=True).encode()
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
        sealed["encryption"] = "fernet-v1"
        return sealed

    @staticmethod
    def _open_event(state: dict, event: dict) -> dict:
        from cryptography.fernet import Fernet

        opened = copy.deepcopy(event)
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
                    change[side] = json.loads(
                        Fernet(key["secret"].encode()).decrypt(value["sealed"].encode())
                    )
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
