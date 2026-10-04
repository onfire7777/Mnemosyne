"""Durable, data-only action sink for development evaluations; no payload execution."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

_APPLICATION_ID = 0x4D313253  # M12S: do not mutate another application's database.


def _identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("sink identities must be nonempty strings of at most 256 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("sink identities must not contain control characters")
    return value


class ActionSink:
    """Bind delivery identities to a harness-owned run/case/principal scope.

    One committed receipt per logical intention occurrence. Every attempt is
    retained, including duplicates and conflicting action IDs. An accepted
    receipt represents a durable inert record, not an external side effect.
    """

    def __init__(self, path, *, run_id, case_id, tenant_id, session_id):
        self.path = Path(path)
        self.scope = tuple(_identity(value) for value in (run_id, case_id, tenant_id, session_id))
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if application == 0 and not tables and version == 0:
                connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                connection.execute("PRAGMA user_version = 1")
                connection.execute("""CREATE TABLE receipts (
                    run_id TEXT, case_id TEXT, tenant_id TEXT, session_id TEXT,
                    intention_id TEXT, occurrence INTEGER, action_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL UNIQUE,
                    PRIMARY KEY (run_id, case_id, tenant_id, session_id, intention_id, occurrence))""")
                connection.execute("""CREATE TABLE attempts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL, action_id TEXT NOT NULL,
                    origin TEXT NOT NULL, outcome TEXT NOT NULL)""")
            elif application != _APPLICATION_ID or version != 1:
                raise ValueError("path is not a supported action-sink database")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        if (connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or connection.execute("PRAGMA user_version").fetchone()[0] != 1):
            connection.close()
            raise ValueError("action-sink database identity changed")
        return connection

    def deliver(self, *, intention_id, occurrence, action_id, origin="candidate-observation"):
        intention_id, action_id = _identity(intention_id), _identity(action_id)
        if type(occurrence) is not int or not 0 <= occurrence <= 9223372036854775807:
            raise ValueError("sink occurrence must be a nonnegative signed-64-bit integer")
        if origin not in {"candidate-observation", "harness-retry"}:
            raise ValueError("unknown delivery origin")
        key = (*self.scope, intention_id, occurrence)
        receipt_id = hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT action_id FROM receipts WHERE receipt_id = ?", (receipt_id,)).fetchone()
            if existing is None:
                connection.execute("INSERT INTO receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*key, action_id, receipt_id))
                outcome = "accepted"
            else:
                outcome = "duplicate" if existing[0] == action_id else "conflict"
            connection.execute("INSERT INTO attempts (receipt_id, action_id, origin, outcome) VALUES (?, ?, ?, ?)",
                               (receipt_id, action_id, origin, outcome))
        return {"receipt_id": receipt_id, "action_id": action_id, "origin": origin, "outcome": outcome}

    def snapshot(self):
        with closing(self._connect()) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            receipts = [dict(row) for row in connection.execute(
                "SELECT * FROM receipts WHERE run_id=? AND case_id=? AND tenant_id=? AND session_id=? ORDER BY receipt_id",
                self.scope)]
            attempts = [dict(row) for row in connection.execute("""SELECT a.* FROM attempts a
                JOIN receipts r ON a.receipt_id=r.receipt_id
                WHERE r.run_id=? AND r.case_id=? AND r.tenant_id=? AND r.session_id=? ORDER BY a.sequence""", self.scope)]
        return {"schema": "m12-inert-action-sink/v1", "receipts": receipts, "attempts": attempts,
                "external_actions_executed": False, "publishable": False}
