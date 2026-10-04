# WMB M16 — Backend and Transport Parity Implementation Plan

Date: 2026-10-04. Base inspected: `origin/main@3c21be5d`.
Status: **bounded development harness implemented**; focused validation recorded below.
Full M16 remains partial; this is not measured admission evidence.

## Goal and authority

Implement the smallest common public cassette that compares Local and SQLite
through CLI subprocesses and plain local MCP stdio. Reuse existing product
operations and contract tests; do not create a new memory backend, protocol,
benchmark framework, or direct-engine substitute for a transport.

The authority is M16 in
`docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`
(section “Backend and transport parity”), C18/C20, and WMBS-E. Required
acceptance is 100% deterministic semantic, error-class, and authorization
agreement with **at least five runs per executed backend/transport pair**.
A deterministic test run is development validation, not a measured admission
receipt. PostgreSQL and hosted HTTP retain their separate resource gates.

The owner's October 4 request authorizes advancing remaining development
plans. Creating this missing plan satisfies GOAL.md's missing-plan step;
it does not manufacture a historical approval, measured result, registry
admission, or publication permission. No existing plan is rewritten here.

## Existing implementation to reuse

- `eval/harness/cli_driver.py`: `MnemoCLI.run`, JSON decoding, timeout and
  subprocess environment. It passes `--store` automatically only for Local;
  the SQLite cassette must pass `--store <isolated-root>` explicitly in
  `global_flags`. Do not accidentally use the default user store.
- `src/mnemosyne/mcp_server.py`: `serve` is newline-delimited JSON-RPC;
  `initialize`, `notifications/initialized`, and `tools/call` already exist.
  `prepare_tool_arguments` binds signed session tokens; success exposes
  `result.structuredContent`, failure `result.isError` and text content.
- `src/mnemosyne/cli.py`: `mcp-serve --transport stdio` invokes that server.
  Both Local and SQLite accept a durable store path. Keep one MCP child per
  run and close it before reopening its store.
- `eval/public/action_cli.py`: `mint_session_token` supplies harness-owned
  HMAC session identities without importing product engines. Reuse it.
- `tests/test_parity_mcp.py`: operation/schema parity and FR-9
  capture/search/explain/correct/forget lifecycle; these are in-process MCP
  facade tests, not a subprocess backend-by-transport cassette.
- `tests/test_cli_mcp_serve.py`: launch argument and module-entry tests;
  these do not establish successful end-to-end transport parity.
- `tests/test_prospective_memory_api.py`: signed schedule/update/evaluate
  contracts, including wrong session/role/agent denial. Reuse the argument
  shapes, not its direct-engine seed helpers or in-process CLI calls.
- `tests/test_shared_engine_contract.py`: Local/SQLite/Postgres engine
  contract, including prospective, erasure and authorization checks. It skips
  Postgres when `MNEMOSYNE_POSTGRES_DSN` is unavailable.
- `tests/completion/portability/test_cross_engine_parity.py` and
  `_portability.py`: existing engine-level comparison. Do not duplicate its
  broad method coverage or use its normalization as a transport proof.
- `tests/test_session_aware_reads.py`: session opt-in and isolation semantics.
  A signed token proves identity; it does not silently request session-filtered
  retrieval. Cassette reads must name the intended scope explicitly.

## Exact scope and deliverables

Implemented source write set (one serialized owner):

1. Create `eval/public/wmbs_m16.py`: versioned cassette, strict observation
   projection, pair/repeat comparison and a development-only module CLI.
2. Create `eval/public/adapters/backend_transport_parity.py`: CLI dispatch and
   bounded plain-stdio MCP subprocess dispatch using the existing public API.
3. Create `tests/test_public_wmbs_m16.py`: pure contract and subprocess tests.

No registry/scoring/runner/bundle/README/schema/result-v1/result-v2 changes in
this tranche. Python constants plus strict validation are sufficient for this
small development cassette; do not add a schema dependency or a second runner.
Do not import product engines, private stores or `MemoryTools` into the adapter.
Product defects discovered by the cassette are separate narrowly scoped fixes
with failing tests, not normalized away by this plan.

## Declared pairs and unavailable pairs

Execute these four cells separately with fresh stores:
`local/cli`, `sqlite/cli`, `local/mcp-stdio`, `sqlite/mcp-stdio`.
Run each cell five times, preserving all 20 observations. The same semantic
inputs, fixed virtual timestamps, operation order and signed principals apply
to every cell. Only storage paths, transport encoding and returned opaque
handles differ. Runtime processes are sequential, not 20 parallel writers.

List `postgres/cli`, `postgres/mcp-stdio`, and every hosted HTTP/SDK transport
as `not_executed` with a pair-specific reason. Merely setting a DSN must not
silently execute a service against an unapproved database. PostgreSQL needs a
pinned service/image, isolated database, disclosed runtime and resource receipt;
hosted HTTP additionally needs endpoint and identity/custody admission. Missing
optional SDK packages defer that transport only. A launched cell that fails is
`failed`, never `unavailable` or silently dropped from the denominator.

## Common cassette and semantic observation contract

Use first-party inert literals only, with fixed tenant/user/agent/session IDs
inside the fresh store. Token secrets are transient, never serialized. Record
symbolic principals, not tokens. Use one facts tenant and a separate isolation
tenant. Use signed operator/evaluator and reader identities; no ambient role.

Each operation yields a closed record:
`case_id`, `status` (`ok` or `error`), `error_class` (`null`, `authorization`,
`validation`, `not_found`, `transport`, `unclassified`), `authorization`
(`allowed`, `denied`, `not_applicable`), and `semantic` (case-specific object).
Capture the original transport envelope in a separate local raw artifact.
Unknown fields or missing required semantic fields fail validation. Do not
compare only “has hits” or replace all nonempty results with true.

Minimum ordered cases:

- Capture two fixed facts via `capture`; retain each returned CID under its
  cassette label. Read with `get` and search a unique exact keyword via
  `search`; compare content, tenant, branch and provenance labels. Scores,
  latency, wall-clock creation timestamps and transport envelopes are not
  semantic values; preserve them separately rather than deleting raw evidence.
- Correct a fixed subject/predicate using `correct`, then query the changed
  fact. Compare the resulting assertion's subject, predicate, object and
  provenance links. Keep a literal expected object so agreement on the same
  wrong answer fails.
- Forget a captured fact using `forget`, then verify `get` and search no longer
  expose it. Compare erasure boolean and retained visible content/provenance.
  Do not require random hard-delete placeholders to match across runs.
- Schedule one exact-time intention with `intention-schedule` /
  `schedule_intention`; evaluate through `intention-evaluate` /
  `evaluate_intentions` before, at and again at a fixed due timestamp. Compare
  ordered data-only action references: empty, one expected reference, empty.
  Use `prospective:evaluate` only on the evaluator principal.
- Seed one task-scoped working item using `working-seed` / `working_seed`,
  query through `working-query` / `working_query` before and after its fixed
  expiry. Compare item category, content, scope and provenance; expected
  visibility is present then absent. Do not invoke automatic promotion.
- Repeat a protected intention update with wrong session, wrong agent and
  reader identities, then query the owner state to prove no mutation.
  Add a cross-tenant read that returns no foreign fact. Compare denial and
  resulting state, not merely transport status.
- Submit a known invalid recurrence interval (zero) and a malformed argument
  type. Compare validation rejection, followed by a clean read proving no
  partial write. Choose inputs rejected at both exposed API boundaries;
  record different rejection layers as diagnostics.

Capture returned IDs in a per-run bijection from observed ID to cassette
label; replace only declared identity/reference fields. An unknown provenance
ID, duplicate ID assigned to distinct labels, missing field, unexpected result
or ordering difference fails. Preserve ranked search order. Sort only sets
whose public contract explicitly treats them as unordered. Never globally
strip every key named `id`, `time`, `score` or `error`.

### Concrete unresolved protocol boundaries

MCP currently drops Python exception type in `_tool_error`; CLI subprocesses
may expose it only in stderr. Consequently this tranche's `error_class` is a
**cassette classification**, not a claimed public machine-readable error ABI.
Freeze a finite case-specific classifier using the actual raw envelopes first:
required rejection marker plus state non-mutation; unrecognized or ambiguous
responses become `unclassified` and fail. Never map every nonzero exit or MCP
`isError` to the expected class. A future general-purpose error ABI requires
its own CLI/MCP source contract; this plan does not secretly add one.

No equivalent public CLI/MCP cross-backend import/migration command was found
in the inspected command surface. `export` alone cannot prove migration
fidelity. Record migration as `not_executed: public migration seam absent`;
require a separately frozen public import/snapshot contract before claiming
that M16 dimension. Restart persistence is useful but must not be renamed
migration. Full M16 remains partial while that required dimension is absent.

## Repetition, diagnostics, resource and admission contract

Every result records cassette version/digest, source commit, Python/platform,
backend, transport, repeat index 0–4, operation IDs, expected/observed semantic
projections, raw-envelope artifact digests, and completion/failure reason.
Compare every repeat with its literal oracle and with `local/cli` repeat 0.
Do not average away one failed semantic/error/auth case: acceptance requires
all intended comparisons pass (1.0). Report executed/missing/failed cells and
operation denominators explicitly. No score for a cell with zero observations.

Development safety ceilings: 32 tool operations per cassette, 1 MiB per raw
response, 30 seconds per operation and 15 minutes for the whole four-cell
job. These are chosen guardrails, not measured L16-DEV acceptance budgets.
On timeout/output overflow terminate and reap the owned child, retain bounded
diagnostics, mark failure. Paths remain within the supplied output/temp root.
Use no shell evaluation and never execute fixture strings.

Record monotonic per-operation wall milliseconds and count CLI/MCP calls as
local diagnostics. Price/token/provider costs are `null/not_applicable`, never
invented zero-dollar performance claims. Peak RSS/disk/energy are `not_measured`
unless actually metered with a validated per-process mechanism. Resource
admission stays open for each cell without its required measured receipt.
There is no claimed physical 8-GiB, production PPR or Postgres equivalence.

## Implementation sequence and runnable checks

### Task 1 — Freeze projection, pair and error contracts

Write failing tests in `tests/test_public_wmbs_m16.py` first. Hand-authored
observations must catch changed fact text, foreign provenance, unknown IDs,
different rejection class, silently missing repeats and a failed cell omitted
from comparison. Then implement only the pure cassette/projection/comparator
in `eval/public/wmbs_m16.py`. One mismatched repeat must fail the run.

Run: `uv run --locked python -m pytest tests/test_public_wmbs_m16.py -k contract -q`.
Expected: named contract failures before implementation; all contract cases
pass afterwards. Fixture/expected values must not be computed by the projector.

### Task 2 — Public CLI cassette, Local then SQLite

Add real subprocess tests before the adapter. Dispatch the case-specific
public CLI commands via `MnemoCLI`, use isolated explicit store paths for both
backends, and reuse harness session signing. Test the full semantic oracle,
denial/non-mutation and invalid input. Do not mock the product CLI.

Run: `uv run --locked python -m pytest tests/test_public_wmbs_m16.py -k cli -q`.
Expected: both backend cells match literal expected results; absent store-path
forwarding, foreign identity acceptance or wrong content fails the tests.

### Task 3 — Plain MCP stdio and bounded subprocess cleanup

Add tests for the same cassette through `python -m mnemosyne.mcp_server`
with explicit backend/store flags and signed token metadata. Initialize the
process, correlate monotonically increasing request IDs and decode one JSON
line per response. Exercise malformed/overlarge response and timeout with a
small test-only subprocess, proving termination and no synthetic success.
Reuse the existing public server; do not call `server.handle` in the adapter.

Run: `uv run --locked python -m pytest tests/test_public_wmbs_m16.py -k 'stdio or transport' -q`.
Expected: both MCP cells agree with the CLI semantic oracle; transport failures
remain failures, and every spawned child is closed and reaped.

### Task 4 — Five-repeat comparison and honest result

Add tests that reducing any cell below five runs cannot yield passed; preserve
explicit unavailable external pairs and missing migration/resource dimensions.
Implement the development command:
`python -m eval.public.wmbs_m16 --output-dir <new-isolated-directory>`.
It executes exactly the four local cells with five fresh-store repeats and
emits a development report plus bounded raw artifacts. A passing deterministic
cassette reports `development_conformance: passed`, `admission_state: PROPOSED`,
`publishable: false`, `pbpp_headline_eligible: false`, and overall M16 `partial`
while migration/resource/external cells remain open.

Run: `uv run --locked python -m pytest tests/test_public_wmbs_m16.py -q`.
Expected: all contract and subprocess tests pass, including the 20-run matrix.
Then run existing focused regressions:
`uv run --locked python -m pytest tests/test_parity_mcp.py tests/test_cli_mcp_serve.py tests/test_prospective_memory_api.py -q`.
The integration owner runs the repository suite once at the stable final head.
Record exact outcomes; no tests or measured cassette were run by authoring
this plan. A fresh reviewer checks the public seam, projection exclusions,
classifier fail-closed behavior and honest unavailable-pair denominators.

## Completion boundaries

This source tranche is complete when those three files implement and test the
four-cell public cassette, five repetitions, fail-closed comparison and honest
partial report. Full M16 additionally needs public migration fidelity,
per-executed-pair resource receipts and separately admitted external cells.
Registry integration is a subsequent explicit change using the existing public
harness; no benchmark label, score or public claim is granted by plan placement.

## Implementation rulings and validation (2026-10-04)

The implementation uses a closed case-to-value observation mapping and a
literal expected mapping, with original per-call envelopes retained separately.
Ruling: retain this compact representation instead of repeating the planned
six-field envelope for every case. Error cases encode the finite error class;
protected updates additionally prove unchanged owner state, and successful
cases compare the exact semantic value. Missing or extra case keys fail the
whole comparison. This costs generic per-operation interchange compatibility;
no public error ABI or general-purpose observation schema is claimed.

Search projection preserves text, tenant, branch, provenance and ranked order.
Only declared opaque provenance references are replaced by per-run labels;
unknown references fail. The invalid working-write case reads the original
item after rejection. The bounded cassette executes 25 operations per repeat,
500 in the complete matrix, with each raw artifact stored under its own pair
and repeat. Initialization is protocol setup outside this tool-call count.

Ruling: reuse the existing MnemoCLI argv/environment construction but execute
those argv through the bounded child helper; MnemoCLI.run's buffered capture
does not enforce the response-size ceiling. The MCP server is invoked through
its public module entry point. No direct engine calls substitute for either
transport. The implementation adds no package dependencies.

Source provenance includes HEAD, a dirty-working-tree flag and hashes of the
two harness files. Ruling: label this explicitly as a working-tree snapshot,
not an immutable complete product snapshot; these are development diagnostics
and cannot serve as an admitted reproducibility receipt. Ambient MNEMOSYNE_*
configuration is removed; transient signing secrets and tokens are redacted
from retained call envelopes.

Validation: the deliberately failing search-projection test passed after
implementation. New invalid-write non-mutation and malformed-stdio cleanup
tests first failed, then passed with the other non-matrix tests. The complete
matrix and focused regression result is recorded in the execution ledger;
controller review and the repository-wide suite remain separate gates.
