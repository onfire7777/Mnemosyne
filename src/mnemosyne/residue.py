"""``mneme residue-cleanup``: remove what older versions left in an existing store.

Every category is something the current code no longer writes. The scan changes nothing;
``apply=True`` fixes what it found (data only, no schema change), so a second run reports zeros.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from mnemosyne.models import Preference
from mnemosyne.retrieval import is_retired_summary_metadata
from mnemosyne.sqlite_schema import PRAGMA_STATEMENTS, json_text

CATEGORIES = (
    "erased_rows",  # tombstoned evidence that still holds text or a vector: run through forget() again
    "unscrubbed_erasures",  # beliefs, edges, preferences a past forget retracted but left their text in
    "embedding_cache_rows",  # SQLite write-only mirror of evidence vectors; nothing reads the table
    "finished_jobs",  # complete queue jobs, or their stored result where the queue keeps the row
    "single_source_gists",  # active summary of exactly one memory: retired like a superseded summary
    "cadence_killed_jobs",  # consolidation jobs the old 5-step cadence rail drove to 'dead': queued again
    "sqlite_free_pages",  # may still hold erased text; apply also rebuilds FTS, VACUUMs and truncates the WAL
)
REQUESTED_BY = "residue-cleanup"
_CADENCE_REFUSAL = re.compile(r"consolidation pass refused: \d+ step\(s\) since last pass < \d+-step .*cadence lower bound")
_SCRUBBED_CALIBRATION = {"dependency_erased": True}
_PROPAGATED = {"assertions": "retracted_assertions", "relations": "expired_relations", "preferences": "retracted_preferences"}


def residue_cleanup(engine: Any, runtime_state: Any = None, *, apply: bool = False) -> dict[str, Any]:
    counts, file_bytes = _run(engine, runtime_state, apply=False)
    report: dict[str, Any] = {"apply": apply, "counts": counts, "file_bytes": file_bytes, "ok": True}
    if apply:
        _, report["file_bytes_after"] = _run(engine, runtime_state, apply=True)
        report["after"], _ = _run(engine, runtime_state, apply=False)
        report["ok"] = not any(report["after"].values())
    return report


def _run(engine: Any, runtime_state: Any, *, apply: bool) -> tuple[dict[str, int], dict[str, int]]:
    counts = dict.fromkeys(CATEGORIES, 0)
    files: dict[str, int] = {}
    kind = type(engine).__name__
    if kind == "SqliteEngine":
        _sqlite(engine, counts, files, apply)
    elif kind == "PostgresEngine":
        _postgres(engine, counts, apply)
    else:
        _local(engine, counts, apply)
    if runtime_state is not None:
        _runtime_queue(runtime_state, counts, apply)
    return counts, files


def _single_source_gist(metadata: Any) -> bool:
    summary = metadata.get("summary") if isinstance(metadata, dict) else None
    if not isinstance(summary, dict) or is_retired_summary_metadata(metadata):
        return False
    return len(set(summary.get("source_evidence_cids") or metadata.get("source_evidence_cids") or [])) == 1


def _retired_gist(metadata: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {"summary": {**metadata["summary"], "status": "retired", "retired_at": now, "retired_by": REQUESTED_BY}}


def _cadence_killed(kind: str, status: str, last_error: str | None) -> bool:
    return kind == "consolidate_evidence" and status == "dead" and bool(_CADENCE_REFUSAL.fullmatch(last_error or ""))


def _erasure_ids(propagated_rows: Iterable[Any]) -> dict[str, set[str]]:
    """Ids a past forget retracted; older versions emptied their sources, so only the log links them."""
    ids: dict[str, set[str]] = {table: set() for table in _PROPAGATED}
    for propagated in propagated_rows:
        if isinstance(propagated, dict):
            for table, key in _PROPAGATED.items():
                ids[table].update(str(item) for item in propagated.get(key) or [])
    return ids


def _forget_again(engine: Any, rows: Iterable[tuple[str, str, str]]) -> None:
    for tenant_id, branch, cid in rows:
        engine.forget(tenant_id, cid, branch, requested_by=REQUESTED_BY)


def _retire_gists(engine: Any, rows: Iterable[tuple[str, str, str, dict[str, Any]]]) -> None:
    for tenant_id, branch, cid, metadata in rows:
        engine.update_evidence_metadata(
            tenant_id, cid, _retired_gist(metadata), branch=branch, actor="consolidation", source=REQUESTED_BY
        )


def _runtime_queue(runtime_state: Any, counts: dict[str, int], apply: bool) -> None:
    """The JSON / runtime-state queue: complete jobs are dropped by ``to_dict`` on save."""
    queue = runtime_state.load_queue()
    finished = [job for job in queue.jobs.values() if job.status == "complete" or job.result is not None]
    killed = [job for job in queue.jobs.values() if _cadence_killed(job.kind, job.status, job.last_error)]
    counts["finished_jobs"] += len(finished)
    counts["cadence_killed_jobs"] += len(killed)
    if apply and (finished or killed):
        for job in finished:
            job.result = None
        for job in killed:
            job.status, job.attempts, job.last_error, job.updated_at = "queued", 0, None, datetime.now(UTC)
        runtime_state.save_queue(queue)


# --- SQLite: every <tenant>.db plus system.db under the store root ------------------------------

_SQLITE_UNSCRUBBED = {
    "assertions": "status = 'retracted' AND source_evidence_cids = '[]' AND NOT (subject = '[erased]' "
    "AND predicate = 'erased' AND object = '[erased]' AND scope = '{}' AND calibration = :calibration)",
    "relations": "source_evidence_cids = '[]' AND valid_to IS NOT NULL "
    "AND NOT (source = '[erased]' AND predicate = 'erased' AND target = '[erased]')",
}
_SQLITE_SCRUB = {
    "assertions": "subject = '[erased]', predicate = 'erased', object = '[erased]', scope = '{}', calibration = :calibration",
    "relations": "source = '[erased]', predicate = 'erased', target = '[erased]'",
}


def _sqlite(engine: Any, counts: dict[str, int], files: dict, apply: bool) -> None:
    for path in sorted(Path(engine.root_dir).glob("*.db")):
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            for pragma in PRAGMA_STATEMENTS:
                conn.execute(pragma)
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'evidence'").fetchone() is None:
                continue  # not a store file
            _sqlite_file(engine, conn, path, counts, files, apply)
        finally:
            conn.close()


def _sqlite_file(engine: Any, conn: sqlite3.Connection, path: Path, counts: dict[str, int], files: dict, apply: bool) -> None:
    erased = [tuple(row) for row in conn.execute(
        "SELECT tenant_id, branch, cid FROM evidence WHERE erased = 1 AND (content != '' OR embedding IS NOT NULL)")]
    gists = [
        (row["tenant_id"], row["branch"], row["cid"], metadata)
        for row in conn.execute(
            "SELECT tenant_id, branch, cid, metadata FROM evidence "
            "WHERE source_type = 'consolidation-summary' AND erased = 0 AND retired_at IS NULL").fetchall()
        if _single_source_gist(metadata := json.loads(row["metadata"] or "{}"))
    ]
    ids = _erasure_ids(json.loads(row["record"]).get("propagated") for row in conn.execute("SELECT record FROM deletion_log"))
    calibration = {"calibration": json_text(_SCRUBBED_CALIBRATION)}
    unscrubbed = {
        table: [row[0] for row in conn.execute(
            f"SELECT rowid, id FROM {table} WHERE {where}", calibration) if row[1] in ids[table]]
        for table, where in _SQLITE_UNSCRUBBED.items()
    }
    preferences = []
    for row in conn.execute("SELECT rowid, id, record FROM preferences").fetchall():
        pref = Preference.from_dict(json.loads(row["record"]))
        if row["id"] in ids["preferences"] and pref.status == "retracted" and not pref.source_evidence_cids and (
            pref.statement, pref.scope, pref.exceptions) != ("[erased]", {}, {}):
            pref.statement, pref.scope, pref.exceptions = "[erased]", {}, {}
            preferences.append((json_text(pref.to_dict()), row["rowid"]))
    killed = [row["id"] for row in conn.execute(
        "SELECT id, kind, status, last_error FROM runtime_jobs WHERE status = 'dead'").fetchall()
        if _cadence_killed(row["kind"], row["status"], row["last_error"])]
    counts["erased_rows"] += len(erased)
    counts["single_source_gists"] += len(gists)
    counts["unscrubbed_erasures"] += sum(map(len, unscrubbed.values())) + len(preferences)
    counts["embedding_cache_rows"] += conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
    counts["finished_jobs"] += conn.execute(
        "SELECT COUNT(*) FROM runtime_jobs WHERE status = 'complete' OR result IS NOT NULL").fetchone()[0]
    counts["cadence_killed_jobs"] += len(killed)
    counts["sqlite_free_pages"] += conn.execute("PRAGMA freelist_count").fetchone()[0]
    files[path.name] = _sqlite_bytes(path)
    if not apply:
        return
    _forget_again(engine, erased)
    _retire_gists(engine, gists)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, rowids in unscrubbed.items():
            conn.executemany(f"UPDATE {table} SET {_SQLITE_SCRUB[table]} WHERE rowid = :rowid",
                             [{**calibration, "rowid": rowid} for rowid in rowids])
        conn.executemany("UPDATE preferences SET record = ? WHERE rowid = ?", preferences)
        conn.execute("DELETE FROM embedding_cache")
        conn.execute("DELETE FROM runtime_jobs WHERE status = 'complete'")
        conn.execute("UPDATE runtime_jobs SET result = NULL WHERE result IS NOT NULL")
        conn.executemany(
            "UPDATE runtime_jobs SET status = 'queued', attempts = 0, last_error = NULL, updated_at = ? WHERE id = ?",
            [(datetime.now(UTC).isoformat(), job_id) for job_id in killed])
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    # Deleted FTS terms and freed pages keep the old text until rewritten; the WAL keeps the old frames.
    conn.execute("INSERT INTO evidence_fts(evidence_fts) VALUES('rebuild')")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    files[path.name] = _sqlite_bytes(path)


def _sqlite_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in (path, Path(f"{path}-wal")) if item.exists())


# --- Local JSON store ---------------------------------------------------------------------------


def _local(engine: Any, counts: dict[str, int], apply: bool) -> None:
    rows = list(engine.evidence.values())
    erased = [(ev.tenant_id, ev.branch, ev.cid) for ev in rows if ev.erased and (ev.content or ev.embedding is not None)]
    gists = [
        (ev.tenant_id, ev.branch, ev.cid, ev.metadata)
        for ev in rows
        if not ev.erased and ev.retired_at is None and ev.source_type == "consolidation-summary"
        and _single_source_gist(ev.metadata)
    ]
    ids = _erasure_ids(entry.get("propagated") for entry in engine.deletion_log)
    assertions = [
        key for key, item in engine.assertions.items()
        if item.id in ids["assertions"] and item.status == "retracted" and not item.source_evidence_cids
        and (item.subject, item.predicate, item.object, item.scope, item.calibration)
        != ("[erased]", "erased", "[erased]", {}, _SCRUBBED_CALIBRATION)
    ]
    relations = [
        key for key, item in engine.relations.items()
        if item.id in ids["relations"] and item.valid_to is not None and not item.source_evidence_cids
        and (item.source, item.predicate, item.target) != ("[erased]", "erased", "[erased]")
    ]
    preferences = [
        item for item in engine.preferences.values()
        if item.id in ids["preferences"] and item.status == "retracted" and not item.source_evidence_cids
        and (item.statement, item.scope, item.exceptions) != ("[erased]", {}, {})
    ]
    counts["erased_rows"] += len(erased)
    counts["single_source_gists"] += len(gists)
    counts["unscrubbed_erasures"] += len(assertions) + len(relations) + len(preferences)
    if not apply:
        return
    _forget_again(engine, erased)
    _retire_gists(engine, gists)
    if not (assertions or relations or preferences):
        return
    with engine._lock:
        # Same values forget writes; re-assigning re-indexes the scrubbed subject/source.
        for key in assertions:
            item = engine.assertions[key]
            item.subject = item.object = "[erased]"
            item.predicate, item.scope, item.calibration = "erased", {}, dict(_SCRUBBED_CALIBRATION)
            engine.assertions[key] = item
        for key in relations:
            item = engine.relations[key]
            item.source = item.target = "[erased]"
            item.predicate = "erased"
            engine.relations[key] = item
        for item in preferences:
            item.statement, item.scope, item.exceptions = "[erased]", {}, {}
        engine._persist()


# --- PostgreSQL (run as the admin or consolidator role) -----------------------------------------

_PG_UNSCRUBBED = {
    "assertions": (
        "status = 'retracted' AND source_evidence_cids = '{}' AND NOT (subject = '[erased]' AND predicate = 'erased' "
        "AND object = '[erased]' AND scope = '{}'::jsonb AND calibration = %(calibration)s "
        "AND lexeme IS NULL AND embedding IS NULL)",
        "subject = '[erased]', predicate = 'erased', object = '[erased]', scope = '{}'::jsonb, "
        "calibration = %(calibration)s, lexeme = NULL, embedding = NULL, embedding_partition = 'none'",
    ),
    "relations": (
        "source_evidence_cids = '{}' AND valid_to IS NOT NULL "
        "AND NOT (source = '[erased]' AND predicate = 'erased' AND target = '[erased]')",
        "source = '[erased]', predicate = 'erased', target = '[erased]'",
    ),
    "preferences": (
        "status = 'retracted' AND source_evidence_cids = '{}' "
        "AND NOT (statement = '[erased]' AND scope = '{}'::jsonb AND exceptions = '{}'::jsonb)",
        "statement = '[erased]', scope = '{}'::jsonb, exceptions = '{}'::jsonb",
    ),
}


def _postgres(engine: Any, counts: dict[str, int], apply: bool) -> None:
    from mnemosyne.postgres_engine import _bytes_to_cid

    with engine.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text, name FROM tenants ORDER BY name")
        tenants = cur.fetchall()
    for db_tenant_id, tenant_id in tenants:
        with engine.connect() as conn, conn.cursor() as cur:
            engine._set_tenant(cur, db_tenant_id)
            cur.execute(
                "SELECT branch, cid FROM evidence WHERE tenant_id = %s AND erased "
                "AND (COALESCE(content, '') <> '' OR embedding IS NOT NULL)", (db_tenant_id,))
            erased = [(tenant_id, branch, _bytes_to_cid(cid)) for branch, cid in cur.fetchall()]
            cur.execute(
                "SELECT branch, cid, metadata FROM evidence WHERE tenant_id = %s AND NOT erased "
                "AND source_type = 'consolidation-summary' AND retired_at IS NULL", (db_tenant_id,))
            gists = [(tenant_id, branch, _bytes_to_cid(cid), metadata) for branch, cid, metadata in cur.fetchall()
                     if _single_source_gist(metadata)]
            cur.execute("SELECT propagated FROM deletion_log WHERE tenant_id = %s", (db_tenant_id,))
            ids = _erasure_ids(row[0] for row in cur.fetchall())
            params = {"tenant": db_tenant_id, "calibration": engine._jsonb(_SCRUBBED_CALIBRATION)}
            for table, (where, scrub) in _PG_UNSCRUBBED.items():
                scope = {**params, "ids": sorted(ids[table])}
                sql = f"FROM {table} WHERE tenant_id = %(tenant)s AND id::text = ANY(%(ids)s) AND {where}"
                cur.execute(f"SELECT COUNT(*) {sql}", scope)
                counts["unscrubbed_erasures"] += cur.fetchone()[0]
                if apply:
                    cur.execute(f"UPDATE {table} SET {scrub} WHERE id IN (SELECT id {sql})", scope)
            cur.execute("SELECT COUNT(*) FROM runtime_jobs WHERE tenant_id = %s AND (status = 'complete' OR result IS NOT NULL)",
                        (db_tenant_id,))
            counts["finished_jobs"] += cur.fetchone()[0]
            cur.execute("SELECT id, kind, status, last_error FROM runtime_jobs WHERE tenant_id = %s AND status = 'dead'",
                        (db_tenant_id,))
            killed = [row[0] for row in cur.fetchall() if _cadence_killed(*row[1:])]
            if apply:
                cur.execute("DELETE FROM runtime_jobs WHERE tenant_id = %s AND status = 'complete'", (db_tenant_id,))
                cur.execute("UPDATE runtime_jobs SET result = NULL WHERE tenant_id = %s AND result IS NOT NULL",
                            (db_tenant_id,))
                cur.execute("UPDATE runtime_jobs SET status = 'queued', attempts = 0, last_error = NULL, updated_at = now() "
                            "WHERE id = ANY(%s)", (killed,))
        counts["erased_rows"] += len(erased)
        counts["single_source_gists"] += len(gists)
        counts["cadence_killed_jobs"] += len(killed)
        if apply:
            _forget_again(engine, erased)
            _retire_gists(engine, gists)
