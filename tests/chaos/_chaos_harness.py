"""Seeded DST workload generator + differential-oracle normaliser (Task 11).

This module is shared by ``test_sqlite_chaos.py`` and
``test_differential_oracle.py``. It is imported via an explicit ``sys.path``
insert (``tests/`` is not a package), never collected as tests.

Design contract
---------------
* **Deterministic given a seed.** ``build_workload(seed, tenant=...)`` returns a
  plain-data op list (no engine coupling). The SAME op list replays identically
  onto a ``LocalMemoryEngine`` and a ``SqliteEngine``. Symbolic refs (evidence
  indices) are resolved at apply time to the content-derived, cross-engine-equal
  ``evidence_cid``.
* **All input timestamps are pinned** to ``_EPOCH + N days`` (never wall-clock),
  and all assertion/relation ids are pinned (``as-<seed>-<i>`` / ``rel-...``),
  so the ONLY fields that can differ between the two engines are the ones each
  engine generates internally (``utc_now()`` / ``new_id()``) plus the one
  documented timestamp-format delta (branch ``created_at``: ``isoformat`` on
  Local vs ``dt_to_json``'s ``Z`` on SQLite). See ``normalise_export``.
* **Fresh model instances per op per engine** — ``upsert_assertion`` mutates the
  incoming object (status/version/transaction_time), so a shared instance would
  cross-contaminate the two engines. ``apply_workload`` builds a new object each
  time from the op's plain data.
"""
from __future__ import annotations

import copy
import json
import random
from datetime import timedelta
from typing import Any

from mnemosyne.models import Assertion, Evidence, Relation, parse_dt
from mnemosyne.privacy import ErasureMode

# Fixed epoch: every input timestamp is derived from this, never wall-clock.
_EPOCH = parse_dt("2026-01-01T00:00:00Z")

# Small symbol namespaces so supersede/contest actually collide across ops.
_SUBJECTS = ["beacon", "orchid", "harbor", "cobalt", "lantern"]
_PREDICATES = ["is", "has", "near"]
_OBJECTS = ["topaz", "rare", "north", "bright", "old"]
_REL_PREDICATES = ["in", "near", "of"]


def build_workload(
    seed: int,
    *,
    tenant: str,
    n_ops: int | None = None,
    honeytoken_marker: str | None = None,
    allow_branches: bool = True,
    allow_assertions: bool = True,
) -> list[dict[str, Any]]:
    """Deterministically build a replayable op sequence for one tenant.

    Op kinds: ``evidence`` / ``assertion`` / ``relation`` / ``branch`` /
    ``merge`` / ``forget`` (spec §8). ``honeytoken_marker`` (when given) is
    appended to the FIRST evidence op's content only.

    The two flags carve out the WELL-DEFINED slices the DIFFERENTIAL ORACLE needs
    (see below); single-engine callers (chaos / lane invariants) leave both
    ``True`` and exercise the full, adversarial mix (assertions on scratch
    branches, merged back, etc.).

    Why the oracle must split them
    ------------------------------
    ``SqliteEngine.branch`` regenerates assertion/relation ids on clone while
    ``LocalMemoryEngine.branch`` PRESERVES them — a *documented, shipped*
    difference (``test_branch_keeps_evidence_cid_fresh_ids_for_assertions_relations``).
    Because merge reinforcement matches on id, that id delta cascades into
    divergent (but each internally-correct) supersession outcomes on merge-back —
    and note it fires even when nothing is upserted on the branch, since the
    branch CLONE itself copies main's assertions with fresh ids. No id-scrub can
    reconcile the resulting status/count differences. Evidence, by contrast, keeps
    its content-addressed cid across branches, so evidence branch/merge/forget IS
    deterministic. Hence:

    * ``allow_branches=False, allow_assertions=True`` → assertions/relations/forget
      on ``main`` only (deterministic ids; full supersession/contest/erasure parity);
    * ``allow_branches=True, allow_assertions=False`` → evidence + branch + merge +
      forget (cid-stable; full branch/merge/erasure parity), no assertions.

    Together they cover every op kind cross-engine over deterministic ground.
    """
    rng = random.Random(seed)
    if n_ops is None:
        n_ops = rng.randint(20, 38)

    ops: list[dict[str, Any]] = []
    branches = ["main"]
    ev_count = 0            # evidence appended so far (index space)
    ev_branch: list[str] = []  # index -> branch it was appended on
    marker_used = honeytoken_marker is None

    kinds = ["evidence", "evidence", "forget"]
    if allow_assertions:
        kinds += ["assertion", "assertion", "relation"]
    if allow_branches:
        kinds += ["branch", "merge"]

    for i in range(n_ops):
        kind = rng.choice(kinds)

        # Ops with preconditions degrade to an evidence append when unmet, so the
        # sequence is always well-formed and replay never references a missing id.
        if kind == "merge" and len([b for b in branches if b != "main"]) == 0:
            kind = "evidence"
        if kind == "forget" and ev_count == 0:
            kind = "evidence"

        if kind == "branch":
            name = f"b{i}"
            frm = rng.choice(branches)
            ops.append({"op": "branch", "tenant": tenant, "name": name, "frm": frm})
            branches.append(name)

        elif kind == "merge":
            frm = rng.choice([b for b in branches if b != "main"])
            ops.append({"op": "merge", "tenant": tenant, "frm": frm, "into": "main"})

        elif kind == "forget":
            idx = rng.randrange(ev_count)
            ops.append({"op": "forget", "tenant": tenant, "evidence_index": idx})

        elif kind == "assertion":
            branch = rng.choice(branches)
            k = min(ev_count, rng.randint(0, 2))
            cids_idx = rng.sample(range(ev_count), k) if ev_count and k else []
            ops.append(
                {
                    "op": "assertion",
                    "tenant": tenant,
                    "id": f"as-{seed}-{i}",
                    "branch": branch,
                    "subject": rng.choice(_SUBJECTS),
                    "predicate": rng.choice(_PREDICATES),
                    "object": rng.choice(_OBJECTS),
                    "confidence": rng.choice([0.6, 0.7, 0.8, 0.9]),
                    "trust_tier": rng.choice([0, 1, 2]),
                    "valid_from_days": rng.randint(0, 400),
                    "cids_idx": cids_idx,
                }
            )

        elif kind == "relation":
            branch = rng.choice(branches)
            k = min(ev_count, rng.randint(0, 2))
            cids_idx = rng.sample(range(ev_count), k) if ev_count and k else []
            ops.append(
                {
                    "op": "relation",
                    "tenant": tenant,
                    "id": f"rel-{seed}-{i}",
                    "branch": branch,
                    "source": rng.choice(_SUBJECTS),
                    "predicate": rng.choice(_REL_PREDICATES),
                    "target": rng.choice(_OBJECTS),
                    "valid_from_days": rng.randint(0, 400),
                    "cids_idx": cids_idx,
                }
            )

        else:  # evidence (chosen or degraded-to)
            branch = rng.choice(branches)
            content = f"note-{seed}-{i} concerning the {rng.choice(_SUBJECTS)} and the {rng.choice(_OBJECTS)}"
            if not marker_used:
                content = f"{content} {honeytoken_marker}"
                marker_used = True
            ops.append(
                {
                    "op": "evidence",
                    "tenant": tenant,
                    "branch": branch,
                    "content": content,
                    "sensitivity": rng.choice([0, 0, 1]),
                }
            )
            ev_branch.append(branch)
            ev_count += 1

    return ops


def apply_workload(engine: Any, ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay ``ops`` onto ``engine``. Returns a replay log usable by invariants.

    ``appended_cids`` is index -> evidence_cid (content-derived, so identical on
    both engines); ``forgotten`` is the set of cids that were tombstoned.
    """
    appended_cids: list[str] = []
    ev_branch: list[str] = []
    forgotten: set[str] = set()

    for op in ops:
        kind = op["op"]
        tenant = op["tenant"]

        if kind == "evidence":
            ev = Evidence(
                tenant_id=tenant,
                user_id="u",
                actor="user",
                source_type="chat",
                content=op["content"],
                sensitivity=op["sensitivity"],
                trust_tier=1,
                access_policy={"tenant": tenant},
                created_at=_EPOCH,
            )
            cid = engine.append_evidence(ev, branch=op["branch"])
            appended_cids.append(cid)
            ev_branch.append(op["branch"])

        elif kind == "assertion":
            a = Assertion(
                tenant_id=tenant,
                user_id="u",
                subject=op["subject"],
                predicate=op["predicate"],
                object=op["object"],
                confidence=op["confidence"],
                trust_tier=op["trust_tier"],
                valid_from=_EPOCH + timedelta(days=op["valid_from_days"]),
                status="active",
                source_evidence_cids=[appended_cids[j] for j in op["cids_idx"] if j < len(appended_cids)],
                access_policy={"tenant": tenant},
                id=op["id"],
            )
            engine.upsert_assertion(a, branch=op["branch"])

        elif kind == "relation":
            r = Relation(
                tenant_id=tenant,
                source=op["source"],
                predicate=op["predicate"],
                target=op["target"],
                valid_from=_EPOCH + timedelta(days=op["valid_from_days"]),
                source_evidence_cids=[appended_cids[j] for j in op["cids_idx"] if j < len(appended_cids)],
                access_policy={"tenant": tenant},
                id=op["id"],
            )
            engine.add_relation(r, branch=op["branch"])

        elif kind == "branch":
            engine.branch(op["name"], frm=op["frm"], tenant_id=tenant)

        elif kind == "merge":
            engine.merge(op["frm"], into=op["into"], tenant_id=tenant)

        elif kind == "forget":
            idx = op["evidence_index"]
            if idx < len(appended_cids):
                cid = appended_cids[idx]
                # TOMBSTONE_RECOMPUTE keeps the row + real cid (deterministic,
                # byte-parity across engines). Hard-delete's HMAC deletion-record
                # id is non-deterministic BY DESIGN and is exercised separately.
                engine.forget(tenant, cid, branch=ev_branch[idx], erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
                forgotten.add(cid)

    return {"appended_cids": appended_cids, "ev_branch": ev_branch, "forgotten": forgotten}


# --------------------------------------------------------------------------- #
# Differential-oracle normalisation.
#
# With every INPUT pinned (timestamps, assertion/relation ids), the ONLY fields
# that may legitimately differ between LocalMemoryEngine and SqliteEngine are:
#
#   (documented cross-engine FORMAT delta)
#   * branch ``created_at`` — Local serialises with ``datetime.isoformat()``
#     (``+00:00``); SQLite stores ``dt_to_json`` (trailing ``Z``). Subsumed by
#     dropping ``created_at`` below (evidence ``created_at`` is pinned identical,
#     so dropping it loses no signal).
#
#   (engine-internal NON-DETERMINISTIC / wall-clock values — present identically
#    on BOTH engines, independently generated, therefore never comparable; this
#    is exactly the volatile set the SHIPPED parity oracles scrub —
#    tests/test_sqlite_assertions.py::_normalise and
#    tests/test_sqlite_ledger.py::_normalise_export)
#   * ``id``        — audit/deletion/justification-record uuid4 (new_id()).
#                     NB: assertion/relation ``id`` are PINNED inputs and are
#                     re-validated by ``assertion_identity`` below (not by this
#                     scrub), so dropping ``id`` here does not weaken that check.
#   * ``at``            — audit/deletion wall-clock stamp.
#   * ``transaction_time`` — upsert sets = utc_now().
#   * ``last_accessed``    — reinforce sets = utc_now().
#   * ``justification_id`` — supersede/contest sets = new_id().
#   * ``valid_from`` / ``created_at`` — pinned identical (dropped defensively).
#   * ``valid_to`` / ``superseded_by`` / ``expired_at`` / ``target_id`` —
#     deterministic in most supersessions but wall-clock/link-volatile in the
#     historical-supersede and forget-cascade paths (the shipped oracle adds
#     exactly these as its volatile "extra"); the supersession OUTCOME is still
#     pinned via ``status`` + ``version`` (kept).
#
# Any divergence surviving this scrub is a REAL SqliteEngine bug.
# --------------------------------------------------------------------------- #
_VOLATILE = frozenset(
    {
        "id",
        "at",
        "transaction_time",
        "last_accessed",
        "justification_id",
        "created_at",
        "valid_from",
        "valid_to",
        "superseded_by",
        "expired_at",
        "target_id",
    }
)


def _scrub(obj: Any, volatile: frozenset[str]) -> Any:
    if isinstance(obj, dict):
        return {k: _scrub(v, volatile) for k, v in obj.items() if k not in volatile}
    if isinstance(obj, list):
        return [_scrub(v, volatile) for v in obj]
    return obj


def normalise_export(export: dict, *, extra: frozenset[str] = frozenset()) -> dict:
    """Return ``export`` with only the documented deltas normalised, lists sorted."""
    volatile = _VOLATILE | extra
    out = _scrub(copy.deepcopy(export), volatile)
    if "tenants" in out:
        out["tenants"] = [normalise_export(item, extra=extra) for item in out["tenants"]]
    for key, value in out.items():
        if isinstance(value, list):
            out[key] = sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
    return out


# --------------------------------------------------------------------------- #
# Targeted parity projections — deterministic, NOT scrubbed. These re-validate
# the load-bearing content that ``normalise_export`` drops (ids, ordering), so a
# divergence the scrub might mask is still caught.
# --------------------------------------------------------------------------- #
def assertion_identity(export: dict) -> set[tuple]:
    """Deterministic identity of every assertion: pinned id + content + outcome."""
    return {
        (
            a["id"],
            a["subject"],
            a["predicate"],
            a["object"],
            a["status"],
            a["version"],
            tuple(sorted(a.get("source_evidence_cids", []))),
        )
        for a in export.get("assertions", [])
    }


def relation_identity(export: dict) -> set[tuple]:
    return {
        (r["id"], r["source"], r["predicate"], r["target"], tuple(sorted(r.get("source_evidence_cids", []))))
        for r in export.get("relations", [])
    }


def evidence_identity(export: dict) -> set[tuple]:
    """Active (non-erased) evidence: cid + content are content-addressed & pinned."""
    return {(e["cid"], e["content"]) for e in export.get("evidence", [])}
