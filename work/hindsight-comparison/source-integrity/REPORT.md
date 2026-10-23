# Source integrity and document-update groundwork

This pass fixes source-custody and journal defects and adds storage primitives
needed for safe document updates. It uses synthetic local regression tests and
a disposable PostgreSQL instance. No benchmark, Hindsight run or model-provider
inference was performed. No competitive score is claimed.

## Changes

- Sourced assertions and preferences must retain readable, unredacted source custody.
  Previously, removing a raw source could leave an active fact citing an
  incomplete summary; lexical/vector/default retrieval still returned its
  text. The new gate walks remaining lineage and respects current privacy,
  expiry and tenant/branch scope. Independent surviving evidence still works.
  External lexical adapters resolve assertion/preference IDs against native
  records and use authoritative text and provenance. Thin-canary caches also
  invalidate when source evidence changes or its authorization expires.
  Shared source lists are checked once per Local/SQLite scan; focused tests count 12 source
  lookups for 20 facts sharing 12 sources, including thin canaries. This checks
  declared custody, not semantic entailment of every fact by its remaining text.
- Native engines support a narrow `source_transaction` for atomic evidence
  append/read/metadata/erasure groups. Same-scope nesting joins; caught inner
  failures poison the whole group. Unrelated mutators and incompatible guards
  cannot commit part of a group. Journals follow the ledger commit.
- Optional immutable `document_segment_id` participates in owner-scoped CIDs.
  Callers assigning distinct segment IDs can hold equal text without sharing evidence custody.
  Absent identities preserve legacy hashes and serialized record shapes. Old
  tombstones still block replay through newly supplied identities.
- Local erasure now removes plaintext from its journal. Shared journal entries
  survive while another branch retains the same CID. Queued journal failures
  do not skip later erasure attempts. Failed local file replacement cleans up
  the uncommitted temporary store.
- PostgreSQL raw evidence reads no longer issue unrelated entity-table schema
  changes. This prevents a simple MVCC read from unnecessarily waiting on those
  DDL locks. Source-transaction tests cover pooled and fresh connections.
- PostgreSQL CI includes the new live source-transaction, identity and custody
  tests under the existing restricted runtime roles. CI execution is distinct
  from the local verification below.

## Contract and migration

See [source transactions](../../../docs/source-transactions.md) for supported
operations, post-commit journal recovery and limitations. The document registry,
revision CAS, nondestructive retirement, durable operation receipts, revision
merge rules and delta extraction are not implemented by these primitives.
`forget` remains permanent erasure, not revision retirement.

Existing PostgreSQL deployments need the administrator-applied additive column
migration in `sql/schema.sql` before further appends, including legacy-shaped writes:

```sql
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS document_segment_id TEXT;
```

SQLite performs its own additive migration. Old read-only SQLite stores remain
readable. Segment IDs are custody identifiers; they do not grant authorization
or override the source access policy.

## Reproduction

The database setup matches the [previous disposable fixture](../reliability-followup/postgres/REPORT.md),
with container name `mnemosyne-source-integrity-ca7da5ef`. It uses the cached
PostgreSQL 16/pgvector image, loopback port 55434 and tmpfs storage; see
[environment identity](environment.json). No existing database is used.

Set the following variables to this disposable database, with the synthetic
test password `mnemosyne-disposable-test`, then run
`.venv/bin/python work/hindsight-comparison/source-integrity/verify.py`:

| Variable | Login |
| --- | --- |
| `MNEMOSYNE_POSTGRES_DSN` | `consolidator_user` |
| `MNEMOSYNE_POSTGRES_APP_DSN` | `app_user` |
| `MNEMOSYNE_POSTGRES_READONLY_DSN` | `eval_user` |
| `MNEMOSYNE_POSTGRES_ADMIN_DSN` | `postgres` |

The DSN form is `postgresql://LOGIN:PASSWORD@127.0.0.1:55434/mnemosyne`.
The script records the selected modules, raw log, JUnit results, source hashes
and lint status. It neither creates nor removes the database. The live role
probe is preserved in [postgres-role-check.json](postgres-role-check.json).

## Final verification

**2,167 passed, eight skipped, zero failures/errors** across 53 selected modules
in **152.269 seconds**. All **328** source/test/configuration hashes stayed
unchanged during the run. Global Ruff checks and the diff whitespace check
passed. The live role probe passed **9/9** with no findings.

Six skips are deliberately inapplicable Local/SQLite variants of PostgreSQL-only
cached-PPR checks. Two require the uninstalled optional `sqlite-vec` extension;
the default SQLite vector scan is covered. No PostgreSQL check was skipped for
a missing live database. This is a targeted regression result, not full-repository
or production certification.

- [Verification summary](verification.json), [raw log](regression.log),
  [JUnit results](regression.xml), [skip reasons](skips.json).
- [Source manifest](source-manifest.json), [lint output](lint.log),
  [runtime versions](versions.json).
- [Focused PostgreSQL transaction/identity results](postgres-source-transaction.xml)
  and [focused projection/canary results](projection-custody.xml).
- Independent reviews exercised local rollback and guard nesting, PostgreSQL
  connection ownership, SQLite transaction control, journal sequencing and
  cross-branch custody. Findings were fixed and included in the final run.

The disposable PostgreSQL container was removed after verification. Its tmpfs
data was discarded and both pre-existing local services remained running with
their original IDs. [Cleanup verification](cleanup.json).
