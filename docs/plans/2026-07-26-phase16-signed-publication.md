# Phase 16 L2 Signed Publication Gate Plan

P16-L2-D closes the narrow integration gap between the already-merged signed
run ledger and static renderer. It composes their public APIs; it does not add a
schema, framework, service, database, or benchmark execution path.

## Exact Flow

`leaderboard.publish.publish_site(ledger, public_key, traces, destination)`:

1. verifies the ledger through `leaderboard.ledger.verify_ledger`;
2. determines the entries superseded by later verified entries;
3. selects active entries whose status is `succeeded` and whose embedded result
   exists;
4. rejects duplicate active `record_id` values or an empty active result set;
5. passes those embedded records and the unchanged trace input to
   `leaderboard.render.render_site`.

The existing ledger verifier remains authoritative for signatures, hashes,
roster completeness, entry shape, result validation, and supersession
invariants. The existing renderer remains authoritative for trace validation,
deterministic HTML, and atomic publication.

## TDD Tasks

1. Add `tests/test_leaderboard_publish.py` with synthetic ephemeral keys and a
   real signed ledger. Prove success, supersession exclusion, invalid-signature
   failure without destination mutation, no-active-success rejection,
   duplicate active-result rejection, and CLI exit behavior.
2. Add the minimum `leaderboard/publish.py` composition and make the focused
   suite green.
3. Run native review and all delivery gates. Repair only confirmed findings
   inside the lease.

## Acceptance Commands

```sh
uv run pytest -q tests/test_leaderboard_publish.py
uv run ruff check leaderboard/publish.py tests/test_leaderboard_publish.py
uv run --extra mcp pytest -q
uv run ruff check .
git diff --check
git diff --name-only "$(git merge-base HEAD origin/main)"..HEAD
```

The changed-file set must remain a subset of:

- `GOAL.md`
- `leaderboard/publish.py`
- `tests/test_leaderboard_publish.py`
- `docs/plans/2026-07-26-phase16-signed-publication.md`

Before commit, inspect the complete diff and scan the lease for credentials,
private keys, secret-like tokens, generated artifacts, oversized files, and
unintended lockfile churn.

## Explicit Gates

Phase 12 protected production evidence, Phase 15 physical hardware proof,
Register A publication readiness, reproduction by construction, and any
external public release remain separate. Synthetic local fixtures are not
evidence for any of them.
