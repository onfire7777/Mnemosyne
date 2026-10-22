# Evidence reliability follow-up

This pass continues the source-based Hindsight gap analysis by repairing
Mnemosyne's existing write and temporal-recall paths. It does not restart the
cancelled comparison, invoke a model provider, or establish a new ranking.

## Repairs

| Area | Reproduced problem | Result |
| --- | --- | --- |
| Ingestion | Erased replays and budget-deferred evidence still queued consolidation/media extraction; an erased correction could enter the fast path. | Verify a live source after append. Return `stored`, `created` and `idempotent`; gate correction, jobs and background indexing on creation. |
| Local persistence | A failed fsync/rename or JSON serialization left an uncommitted source or metadata update visible in memory. | Restore the prior evidence/metadata, audit suffix and store version on immediate write failure. Preserve monotonic evidence epochs for cache invalidation. |
| Mutable metadata | Nested caller-owned metadata was retained by the current source and its audit event. | Detach the patch and the historical audit snapshot. |
| PostgreSQL | Metadata and privacy backfill could overwrite each other's concurrent changes; two backfills could reduce sensitivity from 4 to 3. | Lock the source row before reading and merging, within the existing audited transaction. Remove an unrelated table-wide preferences lock. |
| PostgreSQL erasure | Deleting an unsupported entity failed because its alias-table owner lacked the permission required by the foreign-key cascade. | Grant DELETE only on the derived `entity_aliases` table to its existing owner; preserve tenant isolation and deny app deletion of entities, evidence, branches and audit rows. |
| Policy restart | JSON converted trust-tier integer keys to strings; ingestion then silently used fallback priority caps and floors. | Normalize canonical tier keys during policy loading while preserving explicit integer precedence and configured values. |
| Time and speaker recall | Host-local day windows reused the current UTC offset across DST; repeated-hour records could sort incorrectly or leak past an explicit query instant; recipient pronouns were mistaken for the speaker. | Resolve local boundaries separately, compare UTC instants and recognize the speaking subject. Keep tool/system records distinct from assistant speech. |
| Explicit chronology | Custom rerankers and later boosts could override first/last ordering. | Preserve temporal and speaker order through ranking and final token budgeting; retain ordinary reranking for queries without explicit chronology. |
| Default temporal search | Supported time phrases were ignored without a configured passage graph or explicit passage mode. | Default search uses the authorized lexical passage fallback, retains empty windows, and avoids mixing in out-of-window sources. Deep/as-of and explicit modes retain their semantics. |

## Verification

Final result: **1,422 passed, 6 skipped, 0 failures/errors** across 33 selected
modules in **208.240 seconds**. The six skips are intentionally inapplicable
Local/SQLite variants of PostgreSQL-only cached-PPR checks. All **323** recorded
source, test and configuration files stayed unchanged during verification.
Repository-wide Ruff and `git diff --check` passed. This is a mixed regression
total, including live PostgreSQL tests, not a benchmark score.

The reproducible combined command is implemented in [verify.py](verify.py).
It records source hashes before and after the selected regression modules,
JUnit results and repository Ruff output. Database provisioning and the
before/after concurrent-writer receipts are in [postgres/REPORT.md](postgres/REPORT.md).
Final counts are recorded in [verification.json](verification.json).
The final role probe passed **9/9** checks with no findings. The disposable
database and its tmpfs storage were removed; both pre-existing PentestSwarm
services remained running with their original container IDs. See
[cleanup.json](cleanup.json).
The first combined pass exposed the entity-erasure failure: 1,244 passed,
one failed and seven skipped. Its [original receipt](before-alias-grant/regression.xml)
is retained. Six skips were deliberately inapplicable Local/SQLite variants
of PostgreSQL-only cached-PPR tests; the seventh lacked the named RLS fixture
role. The final command uses the existing restricted `mnemosyne_consolidator`
role for that RLS check.

Expanding the run to the CI retry tests then exposed two fixture defects:
the PostgreSQL teardown tried to delete whole tenants with restricted runtime
credentials, and deliberate corruption writes omitted the required tenant
context. The [intermediate receipt](before-ci-fixture-fix/regression.xml)
records two failures and 34 teardown errors, all confined to those fixtures.
They now retain unique disposable tenants, set the corruption transaction's
tenant and assert one affected row. All 102 retry tests pass in the
[focused rerun](postgres/idempotency-after.xml); runtime grants were not widened
to make fixture cleanup work.

CI now loads the canonical role definitions and uses separate restricted app,
consolidator and readonly logins for runtime tests, with the administrator DSN
reserved for setup and the isolated schema-migration fixture. Its PostgreSQL
job includes the new ingestion, concurrent-metadata and entity-erasure tests,
plus the role-separation probe. This local run does not claim that GitHub's
new workflow has finished.

After provisioning the documented fixture, run the complete selected suite:

```sh
MNEMOSYNE_POSTGRES_DSN=postgresql://consolidator_user:mnemosyne-disposable-test@127.0.0.1:55434/mnemosyne \
MNEMOSYNE_POSTGRES_APP_DSN=postgresql://app_user:mnemosyne-disposable-test@127.0.0.1:55434/mnemosyne \
MNEMOSYNE_POSTGRES_READONLY_DSN=postgresql://eval_user:mnemosyne-disposable-test@127.0.0.1:55434/mnemosyne \
MNEMOSYNE_POSTGRES_ADMIN_DSN=postgresql://postgres:mnemosyne-disposable-test@127.0.0.1:55434/mnemosyne \
uv run --locked python work/hindsight-comparison/reliability-followup/verify.py
```

Existing PostgreSQL installations need the same narrowly scoped grant applied
by their database administrator; editing this repository does not migrate a
running external database:

```sql
GRANT DELETE ON entity_aliases TO mnemosyne_app;
```

## Boundaries and next capability gap

- Ingestion acknowledgement observes the source before and after append; it is
  not an atomic queue transaction or an exactly-once concurrency guarantee.
  Object externalization and optional media embedding still precede admission.
- Local rollback covers immediate append and metadata writes. It does not turn
  `defer_persistence` into a general rollback transaction. A journal failure
  after a successful store commit still leaves the committed evidence present.
- Calendar fixes cover conversation/source timestamps. Automatic event-time
  extraction and arbitrary natural-language temporal reasoning remain separate
  gaps. Host-local DST fixtures run on this POSIX host; they do not certify
  every operating system's timezone rules.
- A generic growing-document API remains open. `source_identity` is excluded
  from legacy CIDs, so two documents can share evidence. Replacing a document
  by scanning that label and calling `forget` is unsafe. A safe next design
  needs owner-scoped document revisions, ordered segment references, atomic
  compare-and-swap publication and separate retirement versus permanent erasure.
  Unchanged text can reuse existing passage-extraction caches; reintroduced
  content needs an identity that does not bypass erasure replay protection.
- These regression tests establish the repaired cases, not Hindsight parity,
  superior benchmark performance, production throughput or absence of all bugs.
