"""Transactional request journal for the draft reference, not production storage."""

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3

from eval.public.action_reference import ExplicitActionReference
from eval.public.action_sink import _identity
from eval.public.bundle import _canonical, _parse_json

APPLICATION_ID = 0x4D313252  # M12R, distinct from the inert action sink.
MAX_RECORD_BYTES = 256 * 1024
MAX_RECORDS = 10000


def _bytes(value):
    encoded = _canonical(value)
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError('reference journal record exceeds limit')
    return encoded


class DurableActionReference:
    """Rebuild one scoped reference under a write transaction before every call.

    Returning an acknowledgement happens after commit. A lost response therefore
    does not lose its state or idempotency record. The journal is local development
    evidence; its hash chain is not a signature or malicious-tamper protection.
    """

    def __init__(self, path, *, run_id, case_id, tenant_id, session_id):
        self.path = Path(path)
        self.scope = _canonical([_identity(v) for v in (run_id, case_id, tenant_id, session_id)]).decode()
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            application = connection.execute('PRAGMA application_id').fetchone()[0]
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            objects = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            if application == 0 and version == 0 and not objects:
                connection.execute(f'PRAGMA application_id = {APPLICATION_ID}')
                connection.execute('PRAGMA user_version = 1')
                connection.execute('CREATE TABLE journal (scope TEXT, sequence INTEGER, request BLOB NOT NULL, response BLOB NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(scope, sequence))')
            elif application != APPLICATION_ID or version != 1:
                raise ValueError('not a supported draft-reference database')

    def run(self, command, payload):
        request = _bytes({'command': command, 'payload': payload})
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute('PRAGMA synchronous = FULL')
            connection.execute('BEGIN IMMEDIATE')
            if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                    or connection.execute('PRAGMA user_version').fetchone()[0] != 1):
                raise ValueError('draft-reference database identity changed')
            count = connection.execute('SELECT count(*) FROM journal WHERE scope=?', (self.scope,)).fetchone()[0]
            if count >= MAX_RECORDS:
                raise ValueError('reference journal capacity exceeded')
            reference, previous = ExplicitActionReference(), hashlib.sha256(self.scope.encode()).hexdigest()
            rows = connection.execute('SELECT sequence, request, response, digest FROM journal WHERE scope=? ORDER BY sequence', (self.scope,))
            for expected, (sequence, raw_request, raw_response, digest) in enumerate(rows):
                if sequence != expected or len(raw_request) > MAX_RECORD_BYTES or len(raw_response) > MAX_RECORD_BYTES:
                    raise ValueError('invalid reference journal sequence or record size')
                saved = _parse_json(raw_request.decode(), 'journal request')
                if not isinstance(saved, dict) or set(saved) != {'command', 'payload'}:
                    raise ValueError('invalid journal request')
                if _bytes(saved) != raw_request:
                    raise ValueError('noncanonical journal request')
                actual = _bytes(reference.run(saved['command'], saved['payload']))
                computed = hashlib.sha256(previous.encode() + raw_request + raw_response).hexdigest()
                if actual != raw_response or digest != computed:
                    raise ValueError('reference journal does not replay')
                previous = digest
            # Decode the exact bytes we will retain, avoiding mutable caller data.
            current = _parse_json(request.decode(), 'request')
            response = reference.run(current['command'], current['payload'])
            encoded_response = _bytes(response)
            digest = hashlib.sha256(previous.encode() + request + encoded_response).hexdigest()
            connection.execute('INSERT INTO journal VALUES (?, ?, ?, ?, ?)',
                               (self.scope, count, request, encoded_response, digest))
        return response
