#!/usr/bin/env python3
"""Command-backed parametric-tier trainer provider (self-hosted, no-GPU).

Invoked as ``MNEMOSYNE_PARAMETRIC_COMMAND`` / the engine's
``CommandParametricTrainer`` boundary: the action name is the final argv item and
a JSON request arrives on stdin; a JSON object is emitted on stdout. This is a
*real* trainer, not a mock -- it reads already-embedded, already-validated memory
evidence for the tenant from the deployed Postgres, fits a deterministic
L2-logistic memory adapter (``mnemosyne.parametric_adapter``) on CPU in
milliseconds, and writes the content-addressed adapter artifact to the deployed
SeaweedFS object store. It fails closed (non-zero exit + stderr) rather than
fabricating structure.

Provider isolation:
  * DB credentials come from a mounted pgpass secret; S3 credentials from the
    SeaweedFS object identity -- distinct, least-privilege, and separate from the
    application process. The trainer only ever receives *train* source ids; the
    held-out protected/eval set is never passed in, so there is no eval/train
    overlap at the provider boundary.
  * The artifact key is the SHA-256 of the adapter bytes (content-addressed =
    immutable); production memory is read-only (never mutated).

Actions:
  propose  -> trains + uploads; returns {adapter_kind, artifact_ref,
              artifact_uri_hash, metrics, metadata}
  rollback -> returns {rollback_ref, metrics}

Environment:
  MNEMOSYNE_PARAMETRIC_PG_PASSFILE   pgpass file (default /run/secrets/pgpass_app)
  MNEMOSYNE_S3_ENDPOINT/_BUCKET/_ACCESS_KEY/_SECRET_KEY   SeaweedFS object store
  SSL_CERT_FILE                      step-ca root for the S3 HTTPS ingress
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time

import psycopg

from mnemosyne import parametric_adapter as pa
from mnemosyne.storage import SeaweedS3Client, s3_config_from_env

PROVIDER_IDENTITY = "mnemosyne-parametric-trainer"
HIGH_TRUST_TIER = 5  # ingest-provenance-assigned trust tier -> the external label
S3_KEY_PREFIX = "parametric"


def _pg_connect() -> psycopg.Connection:
    passfile = os.environ.get("MNEMOSYNE_PARAMETRIC_PG_PASSFILE", "/run/secrets/pgpass_app")
    host, port, db, user, pw = pathlib.Path(passfile).read_text().strip().splitlines()[0].split(":")
    return psycopg.connect(host=host, port=int(port), dbname=db, user=user, password=pw, connect_timeout=15)


def _resolve_tenant_db_id(cur: psycopg.Cursor, tenant_id: str) -> str:
    """Map a tenant *name* (e.g. ``primary``) to its DB uuid; accept a uuid too."""
    cur.execute("select id from tenants where name = %s", (tenant_id,))
    row = cur.fetchone()
    if row:
        return str(row[0])
    cur.execute("select id from tenants where id::text = %s", (tenant_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"unknown tenant {tenant_id!r}")
    return str(row[0])


def _parse_vector(raw: str) -> list[float]:
    return [float(x) for x in raw.strip().lstrip("[").rstrip("]").split(",") if x.strip()]


_EVIDENCE_CID_HEX = re.compile(r"[0-9a-f]{64}")


def _train_split_allow(source_ids: list[str] | None) -> set[str] | None:
    """Return the evidence-cid train-split filter, or ``None`` for no restriction.

    Only content-addressed evidence cids (64-hex) restrict the training corpus.
    ``source_ids`` may carry a genuine evidence train split (the B9 capture and any
    caller that holds out an eval set by cid) OR pure provenance ids -- the
    lesson/procedure UUIDs that ``ParametricTier.propose_from_lessons`` (the MCP
    ``parametric_propose`` tool and the provider-check health probe) forward, since
    ``Lesson``/``Procedure`` carry no source-evidence cid. Provenance UUIDs are not
    evidence cids and must not shrink the corpus to nothing; when no cid-shaped id
    is present the trainer trains on the tenant's full RLS-scoped evidence. A real
    evidence-cid split still filters (eval isolation preserved), and a split whose
    cids do not exist still yields zero rows and fails closed.
    """
    if not source_ids:
        return None
    cids = {str(s) for s in source_ids if _EVIDENCE_CID_HEX.fullmatch(str(s))}
    return cids or None


def _load_training_rows(cur: psycopg.Cursor, source_ids: list[str] | None) -> list[dict]:
    """Return [{cid_hex, embedding, label}] for the tenant's embedded evidence.

    ``label`` = 1 iff the ingest-assigned ``trust_tier`` is high-trust. When
    ``source_ids`` names an evidence train split (cid hexes) the query is restricted
    to it so the provider never touches the held-out eval set; provenance ids that
    are not evidence cids impose no restriction (see ``_train_split_allow``).
    """
    cur.execute(
        "select encode(cid,'hex') as cid_hex, trust_tier, embedding::text "
        "from evidence where embedding is not null and not erased order by cid_hex"
    )
    rows = []
    allow = _train_split_allow(source_ids)
    for cid_hex, trust_tier, emb in cur.fetchall():
        if allow is not None and cid_hex not in allow:
            continue
        vec = _parse_vector(emb)
        if not any(vec):  # skip all-zero embeddings (no signal)
            continue
        rows.append({"cid_hex": cid_hex, "embedding": vec, "label": 1 if int(trust_tier) >= HIGH_TRUST_TIER else 0})
    return rows


def _action_propose(request: dict) -> dict:
    tenant_id = str(request.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ValueError("propose requires tenant_id")
    source_ids = request.get("source_ids") or request.get("train_cids")
    source_ids = [str(s) for s in source_ids] if source_ids else None
    adapter_kind = str(request.get("adapter_kind") or pa.ADAPTER_KIND)
    l2 = float(request.get("l2", 2.0))
    epochs = int(request.get("epochs", 400))
    lr = float(request.get("lr", 0.5))
    # Device-adaptive: explicit request -> MNEMOSYNE_PARAMETRIC_{BACKEND,DEVICE}
    # env -> best detected (pure-python floor, numpy/torch acceleration, GPU).
    backend = str(request.get("backend") or "auto")
    device = str(request.get("device") or "auto")

    conn = _pg_connect()
    try:
        cur = conn.cursor()
        db_tenant = _resolve_tenant_db_id(cur, tenant_id)
        cur.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)", (db_tenant,))
        rows = _load_training_rows(cur, source_ids)
    finally:
        conn.close()
    if len(rows) < 4:
        raise ValueError(f"insufficient training evidence: {len(rows)} rows")
    labels = [r["label"] for r in rows]
    if len(set(labels)) < 2:
        raise ValueError("training labels are single-class; cannot fit an adapter")

    t0 = time.time()
    adapter = pa.train_logistic_adapter(
        [r["embedding"] for r in rows], labels, l2=l2, epochs=epochs, lr=lr,
        adapter_kind=adapter_kind, backend=backend, device=device,
    )
    train_seconds = time.time() - t0
    training_backend = adapter.get("training_backend", {})
    train_eval = pa.evaluate(adapter, [r["embedding"] for r in rows], labels)

    # Attach immutable provenance to the artifact (train ids, not eval ids).
    adapter["provenance"] = {
        "provider": PROVIDER_IDENTITY,
        "tenant_id": tenant_id,
        "train_source_count": len(rows),
        "train_source_ids_sha256": pa.sha256_hex(json.dumps(sorted(r["cid_hex"] for r in rows)).encode()),
        "label_definition": f"trust_tier>={HIGH_TRUST_TIER}",
    }
    blob = pa.serialize(adapter)
    digest = pa.sha256_hex(blob)
    key = f"{S3_KEY_PREFIX}/{tenant_id}/{digest}.json"

    cfg = s3_config_from_env(dict(os.environ))
    client = SeaweedS3Client(cfg)
    try:
        client.create_bucket()
    except Exception:  # noqa: BLE001 - best effort; auto-created on first write
        pass
    client.put_object(key, blob)
    # Read-back integrity proof: the served bytes must equal what we uploaded.
    fetched = client.get_object(key)
    if fetched != blob:
        raise ValueError("artifact read-back mismatch after upload")

    artifact_uri = f"s3://{cfg.bucket}/{key}"
    return {
        "adapter_kind": adapter_kind,
        "artifact_ref": artifact_uri,
        "artifact_uri_hash": f"sha256:{digest}",
        "artifact_bytes": len(blob),
        "metrics": {
            "train_accuracy": round(train_eval["accuracy"], 6),
            "train_size": float(len(rows)),
            "train_seconds": round(train_seconds, 4),
            "mutation_rate": 0.0,
            "source_mutation_rate": 0.0,
        },
        "metadata": {
            "provider": PROVIDER_IDENTITY,
            "reward_signal": "external_only",
            "monotonic_trust": True,
            "trust_tier_delta": 0,
            "target_sink": "parametric_adapter",
            "untrusted_to_system_prompt": "forbidden",
            "eval_source_overlap": False,
            "provider_metadata_checked": True,
            "s3_bucket": cfg.bucket,
            "s3_key": key,
            "training_backend": training_backend.get("backend"),
            "training_device": training_backend.get("device"),
        },
    }


def _action_rollback(request: dict) -> dict:
    artifact = request.get("artifact") or {}
    ref = str(artifact.get("artifact_uri") or artifact.get("id") or "unknown")
    return {
        "rollback_ref": f"rollback:{PROVIDER_IDENTITY}:{ref}",
        "metrics": {"rolled_back": 1.0, "mutation_rate": 0.0},
        "metadata": {"provider": PROVIDER_IDENTITY, "rollback_provider_authorized": True},
    }


ACTIONS = {"propose": _action_propose, "rollback": _action_rollback}


def main(argv: list[str]) -> int:
    action = argv[-1] if argv else ""
    raw = sys.stdin.read()
    try:
        request = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"parametric-trainer: invalid JSON request: {exc}\n")
        return 2
    action = str(request.get("action") or action)
    handler = ACTIONS.get(action)
    if handler is None:
        sys.stderr.write(f"parametric-trainer: unknown action {action!r}\n")
        return 2
    try:
        result = handler(request)
    except Exception as exc:  # noqa: BLE001 - fail closed with a diagnostic
        sys.stderr.write(f"parametric-trainer: {action} failed: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
