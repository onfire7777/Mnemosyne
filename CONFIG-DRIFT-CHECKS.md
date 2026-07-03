# Configuration & Drift Checks

This document records where Mnemosyne configuration originates, how sources
resolve, and the checks that detect drift between declared and running
configuration. It compares running state against authoritative sources; it does
not define configuration values, schemas, or operational procedures — those
remain owned by the v2 blueprint (`§19`, `§23.3`, `§23.5`, `§31`, `§32`) and the
modules under `src/mnemosyne/`.

Two reading rules:

- When a check names a key or rail, **the value lives in the cited source, never
  here.** A drift check compares; it does not declare.
- The checklist in [Drift checks](#drift-checks-normative) is **normative** — how
  drift detection should hold once wiring is complete. Where today's code does not
  yet support a check, that is recorded in [Implementation status](#implementation-status),
  not by weakening the check.

## Source Blueprint

The v2 blueprint is the authoritative planning source and controls
implementation. The relevant sections:

- `§31` — configuration layers (tunable vs immutable rails) and the rail values.
- `§32` — deployment topologies and ops/observability signals.
- `§19` / `sql/schema.sql` — memory substrate, stores, canonical schema.
- `§23.5` / `§23.3` — the self-editable surface and the promotion gate.

In-code source of truth:

- `src/mnemosyne/self_optimization.py` — `OperatingPolicy.immutable_rails`,
  `within_invariant_rails(...)`; rejects variants that violate rails.
- `src/mnemosyne/parametric.py` — `ParametricInvariantRails`, `required_rails`;
  promotion boundary ("immutable rails missing").
- `src/mnemosyne/security.py` — write roles, capability mediation,
  `consolidator_only_ops`, signed session identity.

Operational artifacts (this lane):

- `config/drift-baseline.toml` — the **Declared** view the checks compare against.
- `tests/test_config_drift.py` — the runnable drift checks.
- `.github/workflows/ci.yml` — runs them in CI.

## Configuration sources

Two conceptual layers (`§31`): **immutable rails** (bound everything; outside the
self-editable surface, `§23.5`) and **tunables** (changeable within rails —
activation weights, decay `d`, `top_k`, rerank width, RRF `k`, consolidation
cadence, fidelity-demotion schedule, conformal target coverage, prefetch budget).
Realized over these concrete loci:

- **Committed repo config** — the declared source of truth: rails/policy in the
  modules above, `sql/schema.sql`, and tunable defaults.
- **CLI flags** — `--backend`, `--postgres-dsn`, `--queue-backend`,
  `--queue-tenant` on `python -m mnemosyne.cli`.
- **`MNEMOSYNE_POSTGRES_DSN`** — Postgres connection string for the `postgres`
  backend.
- **`MNEMOSYNE_PURE`** — set to `1` to force the pure-Python kernel path:
  `mnemosyne.text` then skips importing the optional `mnemosyne_native`
  extension at import time (`NATIVE = None`); unset, the native kernels are
  active whenever the extension is installed. The two paths are
  byte-parity-proven (`tests/test_native_parity.py`), so this selects speed,
  never behavior; the `mnemosyne.native` logger states the active path once at
  import.
- **`MNEMOSYNE_BENCH_ABSOLUTE`** — set to `1` to opt the benchmark suite
  (`tests/benchmarks/`) into the absolute `§22.5` latency budgets
  (reference-machine nightly); unset, only the relative-regression gate runs
  under `--benchmark-only`, and a plain run skips the suite entirely.
- **`journal_dir`** — optional `LocalMemoryEngine` constructor kwarg
  (`engine.py`): directory for the per-tenant append-only CID journals
  (`journal.py`); unset, no journal is written. Engine erasure wiring lands in
  Phase 2 — enabling `journal_dir` before then means erased ledger content is
  retained in the journal until that wiring exists.
- **`docker-compose.yml`** — declared local-first Postgres service
  (`pgvector/pgvector:pg16`, port `54329`, schema mount).
- **Gitignored `.env`, `.env.*`, secret patterns** (`*.pem`, `*.key`,
  `credentials.json`, `service-account.json`, `secrets.json`) — operator override
  and secret channel, including the consolidator write-authority credential.
- **`.mnemosyne/` runtime state** — `objects/` (content-addressed store) and
  `*.runtime.json`. This is **state, not config**: local, never declared, never an
  implicit config source.
- **Cold-loop tuning** — machine-written tunable adjustments, valid only within
  rails (`self_optimization.py`).
- **Topology selector** — `--backend local` (single-binary, JSON runtime state)
  vs `--backend postgres` (multi-tenant RLS) vs `--backend sqlite` (one SQLite
  file per tenant; `--store` is the per-tenant DB root, and `--queue-backend
  sqlite` uses that file's `runtime_jobs` table). Selects which expectations
  apply, not which value wins. **Production topology stays Postgres-only (`§32`):**
  SqliteEngine is a self-hosted/dev-and-edge lane — running it under a
  production/`postgres` topology is check-D environment drift, exactly like a
  production instance wired to the local JSON store.

## Precedence

For a **tunable** value, resolve most-authoritative first:

1. **Immutable rails (`§31`)** — a hard ceiling/floor. A lower layer that would
   exceed a rail is rejected, not merged (`within_invariant_rails` → variant
   refused).
2. **Operator / committed config and explicit CLI flags** — human overrides
   machine (`§4`, principle 12: "human always wins").
3. **Explicit environment** (`MNEMOSYNE_POSTGRES_DSN`) — connection/secret
   injection.
4. **Cold-loop tuned value** — applies only if within rails and not contradicted
   above.
5. **Shipped default** — `local` backend and bundled defaults.

Two orthogonal axes: **topology** (`--backend`) selects the expectation set
before any value resolves; **user-model preference precedence** (explicit beats
inferred — `§14` FR-5) governs *memory content*, not environment config, and is
named only to keep the two systems unconflated.

## Drift checks (normative)

Each item compares `running value` vs `declared source of truth`. A mismatch is a
finding; the correct value is whatever the cited source declares.

### A. Source-of-truth integrity
- [ ] Effective (booted) config materializes from committed repo config — diff
      the two; any unexplained delta is drift.
- [ ] Nothing in the effective config depends on an un-declared value that exists
      only in `.mnemosyne/` runtime state.
- [ ] No machine-written value has overwritten a human-set value without a
      recorded supersession (principle 12 holds).

### B. Immutable-rail conformance — *values owned by `§31`; compare, do not copy*
- [ ] No `OperatingPolicy.immutable_rails` flag is disabled in the running base
      policy (`self_optimization.py`).
- [ ] No promoted artifact is missing a required rail (`parametric.py`) and no
      policy variant violates one.
- [ ] Each rail (`max_supersession_rate`, `min_corroboration_for_delete`,
      `max_prune_fraction_per_pass`, `monotonic_trust`, `reward_signal`,
      `untrusted_to_system_prompt`, `consolidation_cadence_bounds`) matches its
      committed `§31` value. A **widened** rail is a safety regression, not tuning.
- [ ] No rail was authored by the cold loop — rails live outside the self-editable
      surface (`§23.5`); the change log shows only human commits for rail keys.

### C. Tunable-parameter drift — *within rails*
- [ ] Each tunable (`§31`) is within its rail-imposed bounds and within the last
      operator-approved range.
- [ ] Consolidation cadence falls inside the committed `consolidation_cadence_bounds`.
- [ ] Every tunable changed since the last snapshot has a recorded origin
      (operator edit vs cold-loop pass); an unattributed change is drift.

### D. Topology / backing-service match
- [ ] Configured backing services match the declared topology (`§32`): a
      `postgres`/production instance still pointing at the local store — or a
      `local` instance wired to hosted services — is environment drift.
- [ ] Production topology remains Postgres-only. `sqlite` is a recognized
      self-hosted backend (`backends = [..., "sqlite"]`), but a production/
      `postgres` profile running SqliteEngine is check-D environment drift — the
      same class of drift as production pointing at the JSON store.
- [ ] Isolation matches the topology: per-source trust tiers always enforced
      (`mnemosyne_source_trust_tier`); per-tenant RLS (`mnemosyne_current_tenant()`)
      only where the topology declares it.

### E. Credential / authority scope
- [ ] Write authority is limited to the consolidator/operator roles
      (`consolidator_only_ops`, `security.py`); a non-consolidator path holding
      write authority is drift.
- [ ] The MCP server config is stateless (`§32`); stateful server config is drift.
- [ ] Secrets resolve only from the gitignored env/secret channel — no secret has
      leaked into committed config.

### F. Continuous tripwire signals — *check here; response owned by `§32`*
- [ ] Lesson diversity/entropy not collapsing (model-collapse tripwire).
- [ ] Proxy-vs-true success not diverging (reward-hacking tripwire).
- [ ] Long-horizon no-degradation metric holding.
      Surfaced via `python -m mnemosyne.cli ops-report`. A firing tripwire is a
      drift signal only; the response procedure belongs to `§32`.

### G. Config ↔ schema consistency — *pointer only*
- [ ] Config references only stores/channels that exist in `§19` / `sql/schema.sql`
      — no orphaned or renamed keys. References are verified; the schema is not
      restated.

## CI verification

A drift check compares three views — **Declared** (committed repo config),
**Effective** (config at boot), and **Live** (config in force after cold-loop
tuning). `Declared → Effective` catches materialization drift; `Effective → Live`
catches runtime/cold-loop drift. Detection only — remediation and incident
handling belong to `§32`.

The checks above are operationalized in `tests/test_config_drift.py`, which
compares the running code surface against the committed baseline in
`config/drift-baseline.toml`. They run in CI via `.github/workflows/ci.yml`:

- **lint** — `ruff check .` (the repo's linter; mypy is not configured here).
- **test** — `python -m pytest` over the whole suite, including the drift checks;
  live-Postgres tests self-skip without a DSN.
- **postgres** — a `pgvector/pgvector:pg16` service with the canonical schema
  loaded, exercising the Postgres backend and the `--backend postgres` DSN contract.

Run the drift checks locally:

```bash
python -m pytest tests/test_config_drift.py -q
ruff check .
```

| Check | Gated by (in `tests/test_config_drift.py`) | CI job |
| --- | --- | --- |
| A. Source-of-truth (baseline mirror) | `test_baseline_*` (rail names, security-rail subset, tunable names + defaults, authority ops) | test |
| B. Rail conformance | `test_base_policy_rails_all_enabled`, `test_within_rails_*`, `test_ops_validation_*` | test |
| C. Tunable drift (within rails) | `test_baseline_default_tunables_are_within_rails`, `test_baseline_tunable_defaults_mirror_policy` | test |
| D. Topology / backend selection | `test_default_backend_*`, `test_declared_backends_*`; DSN contract in the Postgres job | test, postgres |
| E. Credential scope | `test_agent_role_denied_*`, `test_consolidator_role_allowed_*`, `test_non_operator_denied_*` | test |
| F. Tripwire signals | `test_tripwire_*` (unit thresholds) | test |
| G. Config ↔ schema | `test_declared_stores_exist_in_schema`, `test_no_undocumented_stores` | test |

Two checks have a production tier beyond the unit gate: **D / provider-fallback**
is enforced by the existing `retrieval-ops-check` CLI (it flags local
lexical/graph or embedding/reranker providers in a production evidence bundle),
and **F** is surfaced for real workloads by `mnemosyne.cli ops-report`. Both run
against live artifacts, not in the unit job.

## Implementation status

What is enforced today vs. what remains. These are **wiring gaps, not blueprint
changes** — `§31`/`§32` remain the owners of values and procedures.

| Check group | Status | Note |
| --- | --- | --- |
| B. Rail conformance | **Wired + CI-gated** | Enforced at runtime via `within_invariant_rails` / the parametric gate, and asserted in `tests/test_config_drift.py`. Caveat: in code, rails are boolean policy flags; the numeric `§31` thresholds (e.g. `max_supersession_rate`) live as enforced constants in `within_invariant_rails` / `validate_policy_ops_bundle`, not as comparable config keys — so the value-match against `§31` is verified behaviorally, not by literal compare. |
| E. Credential scope | **Wired + CI-gated** | Capability mediation (`security.py`) gates `consolidator_only_ops` and the operator-only sinks; asserted in `tests/test_config_drift.py`. "Exactly one credential holder" remains an operational expectation, not statically enforced. |
| G. Config ↔ schema consistency | **Wired + CI-gated** | `tests/test_config_drift.py` parses `sql/schema.sql` and asserts the declared stores match (renames/drops fail the build). |
| A. Source-of-truth integrity | **Partial** | The baseline↔code mirror (rail / tunable / authority names and tunable defaults) is wired and CI-gated. The full Declared→Effective→Live *runtime* diff is not yet mechanizable: config enters via CLI flags + `MNEMOSYNE_POSTGRES_DSN` with no unified settings layer, so there is no single materialization point to diff. |
| C. Tunable drift | **Partial** | Defaults are snapshotted in `config/drift-baseline.toml` and checked against `OperatingPolicy`, and within-rails bounds are tested. A per-change origin log (operator vs cold-loop) does not yet exist. |
| D. Topology / isolation | **Partial** | Backend selection (`MNEME_BACKEND` → `local`/`postgres`) and the DSN requirement are tested; tenant RLS and per-source trust tiers are wired (`postgres_engine.py`, `queue.py`). No declared topology manifest exists, so "configured services match declared topology" is not auto-asserted; production provider-fallback is covered by `retrieval-ops-check`. |
| F. Tripwire signals | **Partial** | `tripwire_check` thresholds (diversity collapse, proxy-vs-true gap) are unit-tested; `ops-report` produces the observability dashboard. Confirm the production no-degradation metric wiring before gating it. |

Cross-cutting gaps:

- **No unified config layer** — config is CLI flags + one DSN env var; a settings
  module would give the single materialization point checks A and C still need for
  a true runtime three-view diff.
- **Deterministic stand-ins** — embedding/reranker/extraction use local
  deterministic fallbacks; a `postgres`/production topology that resolves to
  fallbacks instead of configured providers is caught by `retrieval-ops-check` on a
  production evidence bundle, not by the unit drift job.

## Scope boundaries

- A drift check **compares** running config to a cited source of truth; it never
  declares the right value. When a check names a rail or tunable, the value lives
  in `§31` or the policy modules.
- This document does **not** redefine memory key schemas or guardrails (`§19`,
  `§31`, `§23.5`). Key/rail names appear only to make checks actionable.
- This document does **not** contain deployment or incident procedures (`§32`).
  An ops signal appears as a *check to evaluate*, never a *response to perform*.
