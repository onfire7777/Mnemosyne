"""Bounded, source-preserving semantic backfill. Dry-run unless --apply."""

from __future__ import annotations

import argparse
import base64
from datetime import UTC
import hashlib
import json

from mnemosyne.memory_formation import (
    _eligible_user_source, preview_direct_user_memory, reproject_direct_user_memory,
)


def _cursor(key):
    return base64.urlsafe_b64encode(json.dumps(key, separators=(",", ":")).encode()).decode()


def run_backfill(facade, tenant_id, user_id, *, cursor=None, limit=20, apply=False):
    """One ordered batch; report identifiers/counts, never private source text."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    after = ("", "")
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor))
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError("invalid backfill cursor") from exc
        if not isinstance(decoded, list) or len(decoded) != 2 or not all(isinstance(item, str) for item in decoded):
            raise ValueError("invalid backfill cursor")
        after = tuple(decoded)
    engine = facade.engine
    config = getattr(engine, "_learning_configuration", {})
    options = {"semantic_proposer": config.get("semantic_proposer"), "semantic_reviewer": config.get("semantic_reviewer"),
               "timezone": config.get("source_timezone"),
               "agent_id": "codex", "session_id": "semantic-backfill"}
    eligible = []
    for row in engine.export_tenant(tenant_id).get("evidence", []):
        if row.get("user_id") != user_id or row.get("branch", "main") != "main":
            continue
        source = engine.get_evidence(tenant_id, row["cid"])
        if source is None or not _eligible_user_source(source):
            continue
        key = (source.created_at.astimezone(UTC).isoformat(), source.cid)
        if key > after:
            eligible.append((key, source.cid))
    eligible.sort()
    batch = eligible[:limit]
    report = {"mode": "apply" if apply else "dry_run", "projection_version": 3,
              "sources": [], "processed": 0, "has_more": len(eligible) > limit, "next_cursor": cursor}
    for key, cid in batch:
        outcome = reproject_direct_user_memory(engine, tenant_id, cid, **options) if apply else None
        preview = outcome["preview"] if outcome else preview_direct_user_memory(engine, tenant_id, cid, **options)
        summary = {"source_cid": cid, "reason": preview["reason"],
                   "assertion_ids": [row["id"] for row in preview["assertions"]],
                   "relation_ids": [row["id"] for row in preview["relations"]],
                   "intention_ids": [row["intention_id"] for row in preview["intentions"]],
                   "obsolete_assertion_ids": preview["obsolete_assertion_ids"],
                   "obsolete_relation_ids": preview["obsolete_relation_ids"],
                   "unresolved_count": len(preview["unresolved"]),
                   "preview_digest": hashlib.sha256(json.dumps(preview, sort_keys=True, default=str).encode()).hexdigest()}
        if outcome:
            summary.update(applied=outcome["applied"],
                           retired_assertion_ids=outcome["retired_assertion_ids"],
                           retired_relation_ids=outcome["retired_relation_ids"],
                           created_count=outcome.get("projection", {}).get("created_count", 0))
        report["sources"].append(summary)
        report["processed"] += 1
        report["next_cursor"] = _cursor(key)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    mode.add_argument("--apply", action="store_true", help="apply the bounded versioned projection")
    parser.add_argument("--cursor")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    from runtime import TENANT, USER, open_facade
    with open_facade() as facade:
        report = run_backfill(facade, TENANT, USER, cursor=args.cursor, limit=args.limit, apply=args.apply)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
