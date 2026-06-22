# Local <-> Postgres cross-engine portability suite (G8 / NFR portability)

Blueprint refs: **G8** (engine portability), **NFR portability**, **FR-2 / FR-3 / FR-8 / FR-10**.

This suite broadens G8 coverage **beyond** the existing parametrized shared contract at
`tests/test_shared_engine_contract.py`.

## Why this exists (the gap it closes)

The existing shared contract (`test_shared_engine_contract.py`) uses a fixture
parametrized as `params=["local", "postgres"]`. That means each test runs against **one
engine at a time** and proves that engine *independently* satisfies the contract. It is
valuable, but it has a structural blind spot: **it never instantiates both engines in the
same test, so it cannot prove the two backends produce the *same observable result* for
the same inputs.** Two engines can each be "internally valid" while disagreeing with each
other.

This suite is **cross-engine**. Every parity case:

1. builds **both** a `LocalMemoryEngine` and (when enabled) a `PostgresEngine`,
2. drives them with the **same string tenant/user IDs** and the **same operations**, then
3. asserts their **normalized observable outputs are identical**.

## How the Postgres half is gated

- The **local half always runs now** (no database required) — this is what `pytest` runs
  in CI/dev by default.
- The **Postgres half is gated on the `MNEMOSYNE_POSTGRES_DSN` environment variable.**
  When it is unset, each parity case still runs its local half and asserts engine-agnostic
  invariants; the cross-engine equality assertion is simply not performed. The dedicated
  `test_postgres_half_runs_when_dsn_present` test `skip`s (rather than silently passing) so
  the gate is visible in the report.

Run the full cross-engine parity (requires a reachable Postgres with the Mnemosyne schema):

```bash
export MNEMOSYNE_POSTGRES_DSN="postgresql://user:pass@localhost:5432/mnemosyne"
PYTHONPATH=src .venv-eval/bin/python -m pytest tests/completion/portability/ -q
```

Run the local half only (default; no database):

```bash
PYTHONPATH=src .venv-eval/bin/python -m pytest tests/completion/portability/ -q
```

## Normalization contract

Two independent backends/runs are allowed to differ on volatile fields. Before comparison
the harness (`_portability.normalize`) strips/rewrites:

- freshly-minted UUID `id`s and bare-UUID scalars -> `"<uuid>"`,
- wall-clock timestamps (`at`, `valid_from`, `transaction_time`, `last_accessed`,
  `detected_at`, ...) -> `"<timestamp>"`,
- volatile id *values* that are part of the contract by presence (`superseded_by`) ->
  `"<id>"` / `None`,
- float jitter on scores/confidence -> rounded to 6 dp,
- collection ordering for content-addressed records -> sorted by `cid`.

Content-addressed `cid`s are **deterministic and identical across engines**, so they are
intentionally **kept** and used as the stable anchor for equality.

The harness machinery is self-validated: pointing the "postgres half" at a second
independent `LocalMemoryEngine` makes all parity cases perform the real cross-engine
equality assertion, and they all pass — proving normalization is neither too loose nor too
strict.

## Methods with proven cross-engine parity

All **26 public methods common to both engines** are exercised in cross-engine mode here:

`append_evidence`, `get_evidence`, `set_evidence_embedding`, `update_evidence_metadata`,
`upsert_assertion`, `add_justification`, `add_contradiction`, `as_of`, `add_relation`,
`graph_ppr`, `lexical_search`, `vector_search`, `retrieve`, `explain`, `set_calibration`,
`deep_search`, `add_preference`, `correct`, `register_entity`, `branch`, `discard`,
`merge`, `forget`, `export_tenant`, `export_all`, `to_json`.

When `MNEMOSYNE_POSTGRES_DSN` is set, each of the above has its local and Postgres
observable outputs asserted identical (after normalization). When it is unset, the local
half + invariants run, and the cross-engine assertion is deferred to a DSN-enabled run.

## Remaining gaps / non-goals

- The two `PostgresEngine`-only methods `connect` and `ensure_tenant_and_branch` are
  infrastructure entry points with no `LocalMemoryEngine` counterpart, so they are out of
  scope for cross-engine parity by definition.
- Parity here is asserted on **observable results** (return values + `export_*` projections
  + audit rows), not on internal storage representation. Two engines may store data
  differently as long as their observable contract matches — that is the portability
  guarantee G8 cares about.
- Throughput/latency SLOs are **not** covered by this suite (NFR portability is about
  behavioral equivalence, not performance).
