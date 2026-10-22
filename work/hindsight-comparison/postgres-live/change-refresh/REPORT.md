# Source-change refresh: live PostgreSQL verification

The opt-in `MentalModelRefreshWorker(check_changes=True)` extension was tested
against a disposable PostgreSQL 16.15 database with the current repository schema
and restricted runtime roles. No external provider, inference benchmark, or
production database was used. The earlier 235-test receipt in the parent
directory remains historical and unchanged.

Four new live tests verify:

- A source inserted through a second database session triggers an early refresh
  after the 60-second minimum spacing, while the default worker still waits for
  the scheduled interval.
- Two unchanged models share one authorized source snapshot and cause no provider
  construction or model-record writes.
- When a competing session refreshes after the first worker's source scan, the
  first worker's obsolete model version cannot claim work or overwrite the winner.
- New source changes do not bypass a failed refresh's persisted retry backoff.

The complete eight-module `tests/test_postgres*.py` run passed **239 tests,
0 skipped, 0 failures/errors, in 59.271 seconds**. This is a mixed live/unit total;
the live mental-model module now has **20 cases**, including the four new cases.
The role probe passed **9/9 checks** with no findings. Ruff and `git diff --check`
passed. All **98 recorded source/schema/test files** were unchanged during the
full run.

- [Full test receipt](postgres-final.xml)
- [Machine-readable verification](verification.json)
- [New-case receipt](focused.xml)
- [Role probe](role-check.json)
- [Environment and image pin](environment.json)
- [Source hashes](source-manifest.json)
- [Cleanup verification](cleanup.json)

The runtime tests used non-superuser, non-BYPASSRLS consolidator/app/readonly
logins. Only the isolated schema migration fixture used the administrator DSN.
Provider replies were deterministic in-process fixtures. Schedule spacing and
lease transitions used a controlled UTC clock with real database transactions;
the existing lock-timeout test used the actual five-second PostgreSQL timeout.
This run does not establish production throughput or other PostgreSQL versions.

The container was bound only to `127.0.0.1:55432`. It and its tmpfs database were
removed after verification. The pre-existing PentestSwarm PostgreSQL and Redis
containers were preserved.
