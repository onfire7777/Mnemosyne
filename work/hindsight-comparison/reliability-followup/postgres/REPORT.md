# PostgreSQL metadata concurrency repair

The real PostgreSQL tests reproduced three lost-update cases: a metadata patch
could erase concurrently added privacy metadata; a privacy backfill could erase
a concurrent metadata patch; and two privacy backfills could lower sensitivity
from 4 to 3. Both operations read the row and later replaced metadata using that
old snapshot. They now lock the evidence row before reading, merging and auditing
within one transaction. A waiter reads the committed predecessor's new values.

The metadata method also no longer issues an unrelated `ALTER TABLE preferences`.
That operation incidentally serialized two metadata calls using a table-wide lock,
but did not protect against privacy backfill. No preference initialization is
required by an operation that only reads and updates evidence and appends audit.

## Evidence

- `initial-patch-only.log`: the initial two-metadata-writer probe passed before
  the repair because of the incidental preference-table lock. This was not
  reported as a reproduced failure.
- `before.log` and `before.xml`: two failures exposed privacy metadata overwritten
  by a patch, in pooled and fresh-connection modes.
- `reverse-before.log` and `reverse-before.xml`: four failures after the metadata
  method was fixed but before the privacy method was fixed, covering lost metadata
  and lowered sensitivity.
- `after.log` and `after.xml`: all 12 live cases pass after both fixes. They cover
  both writer orders, two metadata writers, sensitivity monotonicity, transaction
  rollback on audit failure, released row locks, and erased-evidence rejection.

Tests use a delayed audit hook to hold the first transaction open and observe
`pg_blocking_pids` to confirm the competing operation actually waits. They do not
depend on a scheduling sleep to establish the race and invoke no model provider.

## Entity-alias erasure permissions

The combined restricted-role integration run exposed another existing defect:
forgetting an entity's final source failed with `permission denied for table
entity_aliases`. The foreign-key cascade executes as the table owner, which had
its DELETE permission revoked by the role setup. The entire erasure transaction
correctly rolled back, but the requested source removal could not complete.

`roles.sql` now grants the owner DELETE on this derived cascade target alongside
the existing narrow exceptions. The role-check CLI's default allowlist and tests
include `entity_aliases`. It still denies app DELETE on entities, evidence,
branches and audit rows, and all TRUNCATE privileges. FORCE RLS remains enabled.

`entity-before.xml` records three pre-fix failures under the original grant:
tombstone erasure, legal hard deletion and the expected tenant-scoped alias
deletion. Readonly alias deletion remained denied. `entity-after.xml` records
21 passing checks: the four new live cases, the role-check unit suite and the
original failing shared-engine contract. `entity-role-check.json` records the
live role check. The live cases verify another tenant's aliases remain untouched
and all four protected table DELETE attempts still fail for the app role.

The disposable database received precisely this migration after the failing
checks were captured:

```sql
GRANT DELETE ON entity_aliases TO mnemosyne_app;
```

## Disposable database setup

The container is `mnemosyne-reliability-pg-1f2e3f3c`, bound only to
`127.0.0.1:55434`, with tmpfs database storage. It uses the existing
`colima-pentestswarm` Docker context and cached `pgvector/pgvector:pg16` image.
The repository's `sql/schema.sql` and `infra/postgres/roles.sql` were mounted as
ordered initialization scripts. Existing PentestSwarm services were preserved.
Its database is `mnemosyne`. Its disposable test-only password is
`mnemosyne-disposable-test` for `postgres`, `consolidator_user`, `app_user`, and
`eval_user`. These credentials are solely for this synthetic local database.

From the repository root, recreate the disposable fixture with the recorded image:

```sh
docker --context colima-pentestswarm run -d \
  --name mnemosyne-reliability-pg-1f2e3f3c \
  -p 127.0.0.1:55434:5432 --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=mnemosyne -e POSTGRES_PASSWORD=mnemosyne-disposable-test \
  -v "$PWD/sql/schema.sql:/docker-entrypoint-initdb.d/05-schema.sql:ro" \
  -v "$PWD/infra/postgres/roles.sql:/docker-entrypoint-initdb.d/10-roles.sql:ro" \
  sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a
docker --context colima-pentestswarm exec mnemosyne-reliability-pg-1f2e3f3c \
  pg_isready -U postgres -d mnemosyne
```

After the initialization scripts complete and the database is ready, set only
these disposable login passwords:

```sh
docker --context colima-pentestswarm exec mnemosyne-reliability-pg-1f2e3f3c \
  psql -U postgres -d mnemosyne -v ON_ERROR_STOP=1 -c \
  "ALTER ROLE app_user PASSWORD 'mnemosyne-disposable-test'; ALTER ROLE consolidator_user PASSWORD 'mnemosyne-disposable-test'; ALTER ROLE eval_user PASSWORD 'mnemosyne-disposable-test';"
MNEMOSYNE_POSTGRES_DSN=postgresql://consolidator_user:mnemosyne-disposable-test@127.0.0.1:55434/mnemosyne \
  uv run --locked python -m pytest -q tests/test_postgres_metadata_live.py \
  --junitxml=work/hindsight-comparison/reliability-followup/postgres/after.xml
```

The container was kept for the combined integration check, then removed after
the final passing run. Its tmpfs database was discarded and the pre-existing
services were preserved; see [cleanup verification](../cleanup.json).
The cleanup command targets only this named disposable container:

```sh
docker --context colima-pentestswarm rm -f mnemosyne-reliability-pg-1f2e3f3c
```
