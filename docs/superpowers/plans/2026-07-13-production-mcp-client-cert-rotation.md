# Production MCP Client Certificate Rotation

Status: In Progress
Updated: 2026-07-14

## Objective

Prevent expiry of the short-lived production MCP client certificate without
weakening CA policy, exposing provisioner material, overlapping evidence
capture, or granting Docker or secret-directory authority to an application
container.

The triggering pair was observed to expire at `2026-07-13T22:48:28Z`. That
timestamp records the incident that opened this work; it is not a durable source
of current truth. Every invocation must derive the active pair's lifetime from
the certificate itself.

The permanent design is a host-only, one-shot rotator scheduled hourly by a
macOS LaunchAgent. Each invocation is idempotent and emits at most one terminal
line from the fixed status/exit contract below. Successful completion lines are
keyed by transaction ID and are producer-side at-least-once across invocations:
a crash after stdout but before the durable `emitted` transition may replay the
same key, so receivers must deduplicate `(transaction_id,result)`. There is no
success state after any rollback path.

## Non-negotiable rails

- Preserve every Section 31 invariant and Section 33 test class.
- Never weaken CA duration, provisioner policy, Caddy client authentication,
  trust roots, benchmark custody, or protected-attempt accounting.
- Never rotate while production capture, a protected evaluation, or a runtime
  topology change owns the shared runtime lock.
- Never place passwords or private-key material in argv, environment variables,
  logs, status JSON, repository files, evidence bundles, metrics, or test output.
- Use only Caddy's exact client-auth root
  `${MNEMO_SECRETS_DIR}/stepca-acme-root.crt`; never substitute the broader
  `step-ca-root.crt` compatibility bundle.
- Keep the Docker socket and the external secret root on the host. No
  application or monitoring container gains either authority.
- Preserve whether the profile-gated `operator` consumer was running. Rotation
  must never start it merely to refresh a mounted secret.
- Never auto-steal a stale or malformed lock, auto-repair unrelated certificate
  corruption, prune backups, overwrite an unowned LaunchAgent, force-push,
  delete custody data, or start a protected attempt.
- Do not publish benchmark numbers or public claims from this work. External
  governance and independent reproduction remain human-owned gates.

## Lifetime policy

The active leaf drives the decision after cryptographic validation:

- More than 12 hours remaining: healthy no-op; issuance and Compose are never
  called.
- More than 6 and at most 12 hours: renewal due; attempt a normal rotation.
- More than 2 and at most 6 hours: hard-floor breach; attempt rotation, emit a
  critical status on any deferral/failure, and never relax another rail.
- At most 2 hours or expired: emergency-critical status; attempt only through
  the same fail-closed path. No lock, trust, validation, or hardware bypass is
  permitted.

The requested lifetime remains `24h`. Post-issuance validation, not the request,
is authoritative for actual lifetime, chain, SAN, EKU, key match, mode, and
unencrypted-key requirements.

The existing `infra/validate/validate-production-mcp-client-tls.sh` six-hour
floor remains unchanged. A separate
`infra/validate/diagnose-production-mcp-client-tls-for-rotation.sh` is permitted
only for the current source pair after the normal validator fails solely because
the pair is near expiry or expired. The diagnostic independently proves exact
canonical-root byte identity, chain/signatures at a valid point in the leaf's
lifetime, hostname, client EKU, key match, safe modes, regular non-symlink files,
and an unencrypted key. Every non-time failure is fatal. Staged, published,
committed-recovery, and rollback replacement pairs must pass the unchanged
normal validator with at least six hours remaining.

Focused tests cover source pairs with 13h, 8h, 5h, 1h, and expired lifetimes,
plus wrong-root, wrong-key, wrong-EKU, malformed-chain, unsafe-mode, symlink, and
encrypted-key cases. Only the 5h, 1h, and otherwise-valid expired cases may use
the rotation-only diagnostic.

## Status and exit contract

The rotator writes one terminal `result` enum and exits with the fixed code:

| Result | Exit | Meaning |
|---|---:|---|
| `healthy_noop` | 0 | Valid source pair has more than 12 hours remaining. |
| `staged_only` | 0 | Forced rehearsal issued and validated without publication. |
| `activated` | 0 | New pair, consumers, and every probe are validated. |
| `committed_recovered` | 0 | A committed journal was validated and finalized. |
| `lock_deferred` | 75 | Another cooperative rotator owns the local invocation lock; R2 may later extend this to a recognized shared-runtime owner. |
| `runtime_unavailable` | 69 | Docker/Colima is unavailable; no mutation occurred. |
| `preflight_failed` | 65 | Configuration, trust, input, or validation failed closed. |
| `issuance_failed` | 70 | Staged issuance failed before publication. |
| `publication_failed` | 74 | Publication failed before a committed activation. |
| `rolled_back` | 75 | Activation failed; the old generation was fully restored. |
| `rollback_failed` | 74 | Old-generation restoration or its verification failed. |
| `recovery_failed` | 74 | A recognized journal could not be safely finalized/restored. |

The status reader alone may synthesize `status_absent`, `status_invalid`, or
`status_stale`; those are metrics/alert outcomes and have no process exit code.
The same enums and mapping are asserted by rotator, LaunchAgent, metrics, alert,
and focused tests. A bounded `failure_stage` field records the original failure
without inventing additional terminal results.

## Filesystem and status boundaries

1. The canonical certificate, key, exact root, Keycloak password files, and JWK
   provisioner password remain under the external secret root. Each must be a
   regular non-symlink file with its prescribed safe mode.
2. Sensitive staging, transaction journal, and timestamped old/new generations
   live in a mode-`0700`, non-symlink private rotation directory on the same
   filesystem as the canonical pair. Device identity is checked before any
   publication operation.
3. The persistent local process-lock file
   `${MNEMO_SECRETS_DIR}/.mcp-client-rotation.lock` is a mode-`0600`,
   single-link regular file on the secret-root device. Its device/inode/uid/
   mode/link identity is checked before and after nonblocking `flock`; the
   inherited descriptor is held through the final completion-receipt transition.
   This serializes cooperative rotator invocations only.
4. The R2a shared runtime-lock coordinator is implemented at
   `${MNEMO_CUSTODY_DIR}/locks/runtime-exclusive`; its parent is a mode-`0700`,
   non-symlink directory. The local process lock remains separate. R2b capture
   and rotator callers are merged and source-accepted on
   `main@13d15138a431ecbd4ca2a919cbf05b87a7a9004b`; R2c and R2d caller
   integrations remain open.
5. A separate status-only directory is mounted read-only into `mnemo-metrics`.
   It contains only a schema-validated `status.json`; it contains no
   certificate, key, password, digest, backup, staging, journal, lock, secret
   path, or path to secret material. Status publication uses a sibling temporary,
   file fsync, rename, and parent-directory fsync.
6. The installer copies the existing JWK provisioner password once into the
   external secret root as a regular non-symlink mode-`0600` file without
   output. It refuses to overwrite an existing file or import from an unsafe
   source.

## Issuance contract

Issuance uses the exact digest-pinned `smallstep/step-ca` image declared in
`infra/docker-compose.prod.yml`; it never uses `docker exec` against the live CA
as the permanent path.

Before `docker run`, the rotator must prove:

- Docker context is exactly `colima`.
- Network `infra_internal` exists once and has labels
  `com.docker.compose.project=infra` and
  `com.docker.compose.network=internal`. A same-named foreign network is fatal.
- The image already exists locally at the exact declared digest; no pull or tag
  fallback is allowed.
- The image's `/usr/local/bin/step` reports exactly `Smallstep CLI/0.28.7`.
- Root, password, and unique staging mounts pass regular-file/directory,
  ownership, symlink, mode, and containment checks.

The disposable container contract is fixed:

```text
docker --context colima run --rm --pull never --read-only \
  --user 1000:1000 --pids-limit 64 \
  --cap-drop ALL --security-opt no-new-privileges=true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --network infra_internal \
  --entrypoint /usr/local/bin/step \
  [three declared bind mounts only] \
  <exact digest-pinned image> \
  ca certificate \
  --ca-url https://ca.mnemo.local:9000 \
  --root /run/mnemo/root.crt \
  --provisioner admin \
  --provisioner-password-file /run/mnemo/provisioner-password \
  --san mcp-client.mnemo.local \
  --not-after 24h \
  mcp-client.mnemo.local \
  /work/mcp-client.crt /work/mcp-client.key
```

The three bind mounts are the exact root read-only, provisioner-password file
read-only, and unique staging directory read-write. The command omits
`--password-file`, `--force`, and bundle flags. For this CLI contract, omitting
the output-key password flag produces the required unencrypted key; the staged
validator independently rejects any encrypted PKCS#8 or legacy PEM result. The
host environment passed to Docker is rebuilt from a fixed non-secret allowlist;
shell tracing and interactive fallback are rejected.

## Consumer-consistent, crash-recoverable publication

Two file renames cannot atomically publish a certificate/key pair. The supported
contract is consumer-consistent and crash-recoverable:

1. Validate the current canonical pair and both staged files before mutation.
2. Copy the old pair and stage the new pair in unique private generation files
   on the canonical pair's filesystem. Fsync every file.
3. Write a mode-`0600` transaction journal before the first canonical rename.
   It records schema v2, an unguessable transaction ID, old/new certificate and
   key SHA-256 digests, phase, UTC time, the exact pre-rotation consumer-state
   booleans, and a nullable secret-free Compose ownership substate. It contains
   no password value, password-derived verifier, or password-length metadata.
   Fsync the journal and parent directory.
4. Rename the staged certificate to the canonical certificate, fsync the parent,
   then rename the staged key to the canonical key and fsync the parent.
5. Revalidate the published pair before touching a consumer. Advance and fsync
   the journal after each phase.
6. Force-recreate the required consumers, run direct and blackbox probes, and
   mark the transaction committed. Re-prove the canonical pair against the
   retained `generation.<transaction>.new.{crt,key}` files and the unchanged
   six-hour validator before authorizing either `activated` or
   `committed_recovered`.
7. Durably create or resume a transaction-bound mode-`0600` pending completion
   receipt, including file fsync, no-replace rename, identity revalidation, and
   parent-directory fsync. Only then unlink the transaction journal and fsync
   its parent. Retained generations are never pruned automatically.
8. Emit `mcp-client-rotation result=<result> transaction_id=<id>` once for that
   invocation, then rename pending to `emitted` and fsync the parent. If the
   emitted-parent fsync fails, rename the receipt back to pending, fsync again,
   emit no second result line, and exit 74. `emitted` records producer progress,
   not receiver acknowledgement.

On startup, a valid residual journal is recovered before ordinary current-pair
validation. Recovery depends on the fsynced phase:

- Before `committed`, deterministically restore and normally validate the old
  generation. If activation may have begun, recreate the recorded prior
  consumer set and run every rollback check.
- At `committed`, require matching new digests, normal replacement validation,
  exact expected consumer cardinality, stable restart state, both direct probes,
  and a fresh blackbox sample. If all pass, authorize
  `committed_recovered`, durably publish its pending receipt, and only then
  finalize/remove the journal without restoring an older or expired pair.
- If committed-state validation fails, attempt the full old-generation rollback.
  End as `rolled_back` only if every rollback check passes; otherwise end as
  `rollback_failed` or `recovery_failed`.

A missing, malformed, forged, or digest-inconsistent journal never authorizes
recovery. A mixed/corrupt canonical pair without a recognized journal fails
closed for human review.

Tests interrupt after each canonical rename, each consumer transition, every
receipt create/write/fsync/rename/revalidation window, journal unlink and parent
fsync, keyed stdout, and the emitted-parent fsync. They prove phase-specific
recovery, unchanged canonical/generation identity, no repeated Docker/probe
side effects after success authorization, deterministic replay, and lock
retention through the final durable mark. Owner-token mismatch, unrelated
corruption, and rollback-probe failure are separate critical outcomes.

## Compose and consumer contract

The rotator first selects containers by Docker labels, never by guessed names.
Exactly one running `blackbox-exporter` with project label `infra` must exist
before rotation; otherwise rotation fails rather than starting it. The
profile-gated `operator` service must resolve to exactly zero or one running
container. More than one match is fatal. Zero remains zero.

Required Compose interpolation values are read from the regular mode-`0600`
external files `kc_db_pw` and `kc_admin_pw`. The complete accepted value grammar
is 16–512 bytes matching `[A-Za-z0-9._~!@#$%^&*+=,:/?-]+`; NUL, CR/LF, quotes,
backslash, whitespace, non-printable bytes, and every other byte are rejected.
Accepted values are emitted into a private mode-`0600` temporary dotenv using
single-quoted literal values. The ambient environment is rebuilt from a fixed
allowlist so it cannot override the dotenv.

Before password bytes are written, the schema-v2 transaction journal fsyncs a
`planned` owner token and then an `owned` device/inode/uid/mode/link-count
binding for the empty temporary file. After the payload fsync, the journal moves
to `ready` and a schema-v2 receipt binds the same metadata to the transaction ID;
neither durable object stores password bytes, their hash, or their length. An
owner-token-checked trap advances the journal to `cleanup`, moves each owned
artifact to a deterministic quarantine with a native no-replace rename,
revalidates the open inode after the rename, fsync-removes it, and clears the
journal state last. Before fixed-receipt publication, the matching journal may
recover only missing receipt state or its exact owner-scoped partial temporary/
quarantine residue. Once the fixed receipt exists, its exact schema-v2
transaction/token/inode/link binding is mandatory. Legacy or malformed fixed
receipts, cross-transaction state, extra links, replaced artifacts, and foreign
artifacts are preserved and fail closed before deletion. The rotation directory
is mode `0700` and single-writer; POSIX does not isolate a concurrent malicious
process running as the same uid, and this contract does not claim that stronger
boundary. Fault tests cover every durable create/ready/quarantine/unlink state,
a partial receipt, repeated recovery, and replacement preservation.

The exact recreation shape is:

```text
docker --context colima compose \
  --project-directory /Users/admin/Mnemosyne/infra \
  -p infra \
  --env-file "$PRIVATE_0600_DOTENV" \
  -f /Users/admin/Mnemosyne/infra/docker-compose.prod.yml \
  up -d --no-deps --no-build --force-recreate SERVICE
```

`SERVICE` is first `blackbox-exporter`; `operator` is recreated only if it was
already running, and that command additionally supplies `--profile operator`.
After each command, the same label/cardinality checks must prove exactly the
expected running set.

## Probe and rollback contract

Direct probes use SNI/hostname validation, the exact Caddy root, the newly
published pair, and TLS 1.3 only. The implementation is equivalent to:

```text
curl --silent --show-error --output /dev/null \
  --tlsv1.3 --tls-max 1.3 \
  --resolve mcp.mnemo.local:443:127.0.0.1 \
  --cacert "$ROOT" --cert "$CERT" --key "$KEY" \
  --write-out '%{http_code}' \
  https://mcp.mnemo.local/health
```

The same probe runs for `/stream/healthz`; only `2xx` is accepted. The checked-in
`infra/scripts/query-production-blackbox-probe.sh` helper selects exactly one
running `caddy` container by Compose project/service labels, verifies its fixed
internal HTTP client capability, and issues one constant, URL-encoded instant
query to `http://victoriametrics:8428/api/v1/query` for:

```promql
timestamp(probe_success{job="blackbox-tls",instance="https://mcp.mnemo.local"}[2m])
  if (last_over_time(probe_success{job="blackbox-tls",instance="https://mcp.mnemo.local"}[2m]) == 1)
```

It never accepts caller-supplied URL, host, or query text.

The helper caps transport time, retries, and response bytes; parses JSON with a
checked-in bounded parser; requires HTTP success, top-level `status=success`,
`resultType=vector`, exactly one series with the exact labels, finite numeric
query time, and a finite decimal raw-sample timestamp string. The fixed `if`
expression admits a series only when the latest raw probe value is `1`. The
helper requires the raw sample to be later than the post-stability activation
boundary, no later than query or receipt time, and no older than two scrape
intervals. It emits only a fixed success/failure summary. No monitoring port
is newly published and no ad-hoc inline HTTP program is used.

Any publication, recreation, direct-probe, blackbox-probe, or consumer-state
failure restores the old pair and recreates exactly the old consumer set.
Rollback success additionally requires normal old-pair validation, exact
blackbox/operator cardinality, stable restart state, both direct probes with the
restored pair, and a fresh post-rollback blackbox sample newer than the rollback
recreation start. Rollback success and rollback failure are explicit, mutually
exclusive terminal states. Rotation success is impossible after rollback
begins.

## Shared runtime lock contract

**R2 status: R2a and R2b are merged and source-accepted; R2b landed through PR
#15 on `main@13d15138a431ecbd4ca2a919cbf05b87a7a9004b`; R2c-R2d and live proof
remain open.** The current
`.mcp-client-rotation.lock` prevents overlapping cooperative rotator invocations
and is deliberately held for the whole process, but it does not serialize
capture, evaluation, runtime flip, or rollback workflows. R2a provides the
shared fail-closed coordinator; the capture and rotator callers are integrated
and proven under R2b, while the R2c/R2d callers still must be integrated and
proven. Neither lock claims protection against a malicious process with
the same uid; same-uid execution is inside the trusted operator boundary.

The smallest shared helper is `infra/scripts/runtime-exclusive-lock.sh`. It:

- walks the complete custody ancestry descriptor-relative with `O_NOFOLLOW`,
  permits only root/current-uid safe ancestors (including root-owned sticky
  temporary roots), validates the exact mode-`0700` locks parent, and atomically
  creates the lock directory;
- creates an unguessable ownership token and records operation, PID, process
  start fingerprint, host, and UTC start in mode-`0600` metadata;
- waits for a bounded in-progress owner publication and classifies held partial
  metadata as contention without rewriting it;
- releases only when the caller presents the same token and every ownership
  field still matches;
- removes its own lock on handled signals through an owner-checked trap; and
- fails closed on stale locks, dead PIDs, PID reuse, forged/malformed metadata,
  symlink substitution, unsafe modes, or owner mismatch. It never steals.

The coordinator creates one dedicated child session/process group whose leader
is the primary command. Signal forwarding remains enabled only while that
leader is unreaped; handled signals are blocked across the poll/reap and holder
clear so a recycled numeric PGID can never be signalled. After leader exit, the
coordinator performs only a bounded drain for short-lived residual members; a
drain timeout or any indeterminate group state retains the lock evidence.
This is a trusted synchronous-caller boundary, not daemon supervision: the
primary command must not return while long-running descendants remain, and an
integrated caller or descendant must not call `setsid`/`setpgid`,
detach/daemonize, or transition uid while ownership is active. A pre-launch
`Popen` failure permits owner-checked cleanup; every post-launch uncertainty
retains evidence instead of unlinking it. Every R2b-R2d caller integration must
prove the synchronous completion, no-detach, no-session-change, and
no-uid-transition contract in its focused tests before acceptance.

R2b-R2d must integrate the helper before any side effect in:

- `infra/scripts/rotate-production-mcp-client-cert.sh`;
- `infra/scripts/capture-production-evidence.sh`;
- `eval/datasets/v2/run_grounded_qa_v2.py`, before protected-attempt ledger
  creation, model access, or evaluation output;
- `infra/scripts/apply-perf-runtime.sh`; and
- `infra/scripts/rollback-perf-runtime.sh`.

The rotator revalidates the current pair and recomputes the renewal decision
after lock acquisition. Existing capture output-root locks and protected-attempt
ledgers remain additional controls and are not removed or weakened.

## LaunchAgent lifecycle contract

The managed label is `com.mnemosyne.mcp-client-cert-rotator`. The rendered plist
uses absolute repository, script, Docker, OpenSSL, state, status, and log paths;
a minimal explicit `PATH`; `WorkingDirectory=/Users/admin/Mnemosyne`;
`StartInterval=3600`; `RunAtLoad=true`; `KeepAlive=false`;
`ProcessType=Background`; and low CPU/I/O priority. External stdout/stderr logs
are pre-created as regular non-symlink mode-`0600` files.

The installer validates with `plutil`, refuses an existing plist or loaded label
without its matching external ownership receipt, and never replaces an unowned
job. A managed update backs up the old plist/receipt, boots out the old job,
atomically installs the new plist, and bootstraps it. Any bootout/bootstrap
failure restores and re-bootstraps the prior managed generation. Installation
is complete only after `launchctl print gui/$UID/com.mnemosyne.mcp-client-cert-rotator`
matches the rendered job.

The LaunchAgent is a logged-in-user service and depends on the approved Colima
runtime. If Docker or Colima is unavailable, the one-shot rotator performs no
certificate mutation and still publishes a non-secret `runtime_unavailable`
status for alerting.

## Metrics and alerts contract

Extend the existing `src/mnemosyne/ops_metrics.py` path and
`cmd_ops_metrics_push` in `src/mnemosyne/cli.py`; cover it in
`tests/test_ops_metrics.py`. `mnemo-metrics` receives only the dedicated
status-only directory as a read-only mount.

The status schema is allowlist-parsed and size-bounded. It exports only stable
numeric/enum series for status timestamp, certificate remaining seconds, last
result, consecutive/recent failure count, last successful rotation timestamp,
and rollback failure. Unknown keys, wrong types, oversized input, symlinks,
unsafe files, or stale status fail closed to an explicit invalid-status metric.

`infra/observability/vmalert/mnemosyne.yml` must alert on:

- status absent or older than two scheduled intervals;
- remaining lifetime below 6 hours and below 2 hours;
- last rotation failure;
- any rollback failure; and
- at least three failures in the configured recent window.

## Hardware admission

Documentation, plan review, and static source inspection may proceed without a
workload admission. Every test command below is serialized and may run only
after one fresh targeted sample proves memory-free at least 35%, host one-minute
load at most 10, and no resident model.

Real issuance, any Compose recreation, direct/blackbox live probe, LaunchAgent
bootstrap/kickstart, runtime flip, model action, full suite, index refresh, or
protected/evidence work requires the applicable stronger gate. For this live
runtime change, take three samples 15 seconds apart; every sample must show at
least 55% free memory, one-minute load at most 7, five-minute load at most 8,
no resident model, no competing capture/test/index/benchmark, exactly one
canonical `infra` stack, approved 6-CPU/12-GiB Colima topology, stable service
restarts, and healthy Vault/API/stream/CA surfaces. A low client-certificate
lifetime may trigger this repair but cannot waive any other admission rail.

## TDD and subagent-driven slices

Each slice follows RED -> minimal GREEN -> focused regression -> fresh review.
An implementer never self-approves. No slice may start tests on a failed targeted
hardware sample, and no live side effect occurs before Slice R4.

### R1a — Preflight, renewal decision, and staged issuance

Status: Source-complete on 2026-07-13. The exact focused suite passes 43 tests,
the unchanged production TLS validator regression passes 21 tests, and the
post-fix independent closure review is clean. All Docker/`step` boundaries were
faked; no live issuance, publication, or runtime mutation occurred.

Files:

- `infra/scripts/rotate-production-mcp-client-cert.sh`
- `infra/validate/diagnose-production-mcp-client-tls-for-rotation.sh`
- `tests/test_production_mcp_client_cert_rotator.py`

RED (expected: missing rotator/preflight behavior):

```sh
uv run --locked pytest -q tests/test_production_mcp_client_cert_rotator.py \
  -k 'preflight or lifetime or renewal or issuance'
```

GREEN and focused regression:

```sh
bash -n infra/scripts/rotate-production-mcp-client-cert.sh
bash -n infra/validate/diagnose-production-mcp-client-tls-for-rotation.sh
shellcheck infra/scripts/rotate-production-mcp-client-cert.sh \
  infra/validate/diagnose-production-mcp-client-tls-for-rotation.sh
uv run --locked ruff check tests/test_production_mcp_client_cert_rotator.py
uv run --locked ruff format --check tests/test_production_mcp_client_cert_rotator.py
uv run --locked pytest -q tests/test_production_mcp_client_cert_rotator.py \
  -k 'preflight or lifetime or renewal or issuance'
uv run --locked pytest -q tests/test_production_vault_tls_validator.py
git diff --check
```

No live issuance runs in this slice. Docker and `step` are faked at the process
boundary; argv/env/output redaction and exact command shape are asserted.

### R1b — Journal, publication, and startup recovery

Status: Source-complete on 2026-07-13. The exact R1b selector passes 38 tests,
the complete rotator file passes 81 tests, and the unchanged production TLS
validator plus bootstrap regressions pass 22 tests (21 validator and 1
bootstrap). Bash syntax, ShellCheck, Ruff, and diff hygiene are green, and the
post-fix independent operability and security closure reviews are clean. The
fixture-only publication seam stops before consumer activation and leaves its
durable journal for startup recovery; no live issuance, publication, consumer
recreation, runtime mutation, protected attempt, or external claim occurred.

Files remain the R1a pair.

RED (expected: missing durable transaction/recovery behavior):

```sh
uv run --locked pytest -q tests/test_production_mcp_client_cert_rotator.py \
  -k 'journal or publish or recovery or interrupt or fsync'
```

GREEN and focused regression:

```sh
bash -n infra/scripts/rotate-production-mcp-client-cert.sh
shellcheck infra/scripts/rotate-production-mcp-client-cert.sh
uv run --locked pytest -q tests/test_production_mcp_client_cert_rotator.py \
  -k 'journal or publish or recovery or interrupt or fsync'
uv run --locked pytest -q tests/test_production_vault_tls_validator.py \
  tests/test_prod_bootstrap_tls_staging.py
git diff --check
```

### R1c — Consumer activation, probes, and rollback

Status: The success-completion/committed-finalization source-and-fixture slice
was committed as `8e97442`, with evidence documentation at `6afd3b3`, and
merged through PR #12 as `97f3c66`. Exact-head CI `29313243324` and post-merge
CI `29314015888` are green. Remaining R1c live-readiness work and live proof
remain open. The isolated
blackbox-query helper selects exactly one running `infra` Caddy container,
uses only the fixed BusyBox transport and encoded MetricsQL
`timestamp(probe_success[2m]) if (last_over_time(probe_success[2m]) == 1)`
expression with the exact fixed labels, and validates the raw scrape timestamp
rather than the instant-query evaluation timestamp. Duplicate keys,
non-finite or non-exact values, extra labels, stale samples, and samples outside
`boundary < raw sample <= query time <= receipt time` fail closed. Every child
phase is bounded and only fixed success or failure summaries are emitted. Both
the embedded interpreter and Docker child environment are fail-closed. The R1c
fixture scope implements exact pre/post consumer discovery, symmetric password
validation, private
mode-`0600` dotenv/receipt ownership, sanitized Compose execution, prior-state
preservation, signal/exit cleanup, and recognized startup residue recovery,
including restrictive-umask recovery and one
bounded single-call Docker snapshot of the exact consumer set after each
recreation. The fixture captures a nanosecond boundary after the final
categorical consumer snapshot, then uses the newly published pair and exact
Caddy root for fixed `/health` and `/stream/healthz` requests, accepts only a
strict single `2xx` status, and invokes the fixed blackbox helper exactly once.
Synthetic tests pin the boundary after the final blackbox-only or optional
operator snapshot and before the first direct probe. The working slice fsyncs
`activation_started` immediately before the first consumer touch. The fake-only
path fsyncs `committed` only after both direct probes plus fresh blackbox
evidence, then enters the authorized completion-receipt/finalization protocol.
A same-process failure after durable activation enters
explicit rollback phases, restores and normally validates the old pair,
recreates exactly the recorded prior consumer set, proves stable recreation,
repeats both restored-pair direct probes, and requires a fresh rollback
blackbox sample. It ends only as `rolled_back` or `rollback_failed`.

Fixture startup resumes recognized `activation_started`,
`rollback_restoring_certificate`, `rollback_restoring_key`, and
`rollback_pair_restored` state without reissuing. Phase/pair corruption,
Compose path/digest substitution, foreign residue, and consumer-set expansion
fail closed while retaining evidence. Residual schema-v2
`published_validated` remains compatibility-ambiguous and is preserved.
Residual `committed` is re-proved through canonical/retained-generation
identity, normal validation, exact consumer cardinality and stability, both
direct probes, and fresh blackbox evidence before `committed_recovered` may be
authorized.

For `activated` and `committed_recovered`, the fixture writes a recoverable
transaction-keyed pending receipt before journal unlink, fsyncs every durable
boundary, and emits the keyed result only after the journal is durably absent.
It then records producer progress with the rollback-safe pending-to-`emitted`
transition. A post-output crash or emitted-parent fsync failure may replay the
same key on a later invocation; receivers must deduplicate it. No receiver ack
exists, historical emitted receipts are retained, and rollback terminal
receipts remain open.

Pre-commit working-tree verification based on `82bc5d5e` passes the full
369-test rotator/blackbox
pair, the unchanged 41-test TLS/bootstrap/Compose-policy tier, all 39
section-31 invariant rails, all 7 section-33 harness tests, and both planning
traceability tests. The §33 artifact is separate because the configured default
suite collects `tests/`, not `eval/tests`. A fresh complete strong gate passed
at 64%/64%/64% free memory, load1 3.23/3.69/3.35, load5 3.37/3.46/3.40, zero
models or competing work, one reachable canonical 20-service `infra` project,
initialized/unsealed Vault, stable API/stream identities and restart counts,
and a valid production MCP client chain. The locked configured suite then
collected 2,636 tests: 2,496 passed, 140 expected skips, 0 failures, and 0
errors in 702.564 seconds. These artifacts exercise the pre-commit working tree
based on `82bc5d5e`; the tested source/test bytes were committed unchanged as
`8e97442`, with evidence documentation at `6afd3b3`. Exact-head CI
`29313243324` passed on final PR head `88067bc`; PR #12 then merged as
`97f3c66`, whose post-merge CI `29314015888` passed all six gating jobs. Older
pre-completion evidence is historical only.
A fresh independent read-only security/correctness audit found no actionable
issue in the committed R1c diff. Its residual limits match this contract: same-UID
execution is trusted, producer output has no receiver ack, the local lock is not
R2, injected crash tests are not physical APFS power-loss proof, and R4 live
rehearsal remains required.

Live activation additionally requires a boundary in the VM/VictoriaMetrics
clock domain or a conservative audited skew bound, bounded polling across the
60-second scrape cadence, stable consumer IDs/restart counts, R2 cross-workflow
serialization, and a fresh strong-gate admission. The completed strong
gate used only read-only Docker/Vault/restart/certificate queries; it performed
no issuance, consumer recreation, certificate mutation, model/index action,
protected attempt, or external claim, and the ordinary production path remains
staged-only. Every future merge or live-action head requires its own live
exact-head CI check; no repository edit self-records its own future CI result.

Files:

- `infra/scripts/rotate-production-mcp-client-cert.sh`
- `infra/scripts/query-production-blackbox-probe.sh`
- `tests/test_production_mcp_client_cert_rotator.py`
- `tests/test_production_blackbox_probe.py`
- `infra/prod/README.md`

RED (expected: missing cardinality, exact Compose, probe, or rollback behavior):

```sh
uv run --locked pytest -q tests/test_production_mcp_client_cert_rotator.py \
  tests/test_production_blackbox_probe.py \
  -k 'compose or consumer or probe or rollback or dotenv or freshness'
```

GREEN and focused regression:

```sh
bash -n infra/scripts/rotate-production-mcp-client-cert.sh
bash -n infra/scripts/query-production-blackbox-probe.sh
shellcheck infra/scripts/rotate-production-mcp-client-cert.sh \
  infra/scripts/query-production-blackbox-probe.sh
uv run --locked ruff check tests/test_production_mcp_client_cert_rotator.py \
  tests/test_production_blackbox_probe.py
uv run --locked ruff format --check \
  tests/test_production_mcp_client_cert_rotator.py \
  tests/test_production_blackbox_probe.py
uv run --locked pytest -q tests/test_production_mcp_client_cert_rotator.py \
  tests/test_production_blackbox_probe.py
uv run --locked pytest -q tests/test_production_vault_tls_validator.py \
  tests/test_prod_bootstrap_tls_staging.py \
  tests/test_prod_compose_policy.py
git diff --check
```

### R2a — Runtime lock helper

Status: Baseline `a91da2e`, review hardening `fb713d4`, and final reviewed head
`5bfd53d` are delivered. The committed RED baselines are `199b898` and
`93e0dc6`. Static gates, 55/55 focused tests, 39/39 section-31 rails, 7/7
section-33 tests, 2/2 planning tests, terminal CodeRabbit, and independent
review are green. Exact head `5bfd53d` passed CI `29377793617` and merged
through PR #13 as `33967b1`; that stacked head passed PR #11 CI `29378482152`
and merged to `main` through PR #11 as `79f6b58`. Post-merge main CI
`29379113689` passed all six gating jobs; this reconciliation's
exact-head/final-main CI and an exact-final-main mutable-index refresh complete
the delivery receipt. The live
receipt is owned by the merged reconciliation PR body so a later repository
commit cannot instantly stale the index SHA.

Files:

- `infra/scripts/runtime-exclusive-lock.sh`
- `tests/test_runtime_exclusive_lock.py`

RED (historical baseline: missing helper and owner-token semantics):

```sh
uv run --locked pytest -q tests/test_runtime_exclusive_lock.py
```

GREEN and focused regression:

```sh
bash -n infra/scripts/runtime-exclusive-lock.sh
shellcheck infra/scripts/runtime-exclusive-lock.sh
uv run --locked ruff check tests/test_runtime_exclusive_lock.py
uv run --locked ruff format --check tests/test_runtime_exclusive_lock.py
uv run --locked pytest -q tests/test_runtime_exclusive_lock.py
git diff --check
```

Tests cover normal ownership, acquisition ordering, contention, bounded held
partial publication, stale/dead/PID-reused owners, forged or malformed
metadata, descriptor-relative unsafe/symlink ancestry, pre-launch cleanup,
post-launch uncertainty evidence retention, descendant lifetime with a real
flock probe, an unreaped exited leader as a non-reusable PGID anchor, fixed-path
process-group enumeration, post-exit descendant signal forwarding, bounded
drain, atomic final scan/unpublication/reap, a no-signal post-reap existence
proof, inherited and ordinary child/wrapper signal fidelity, release-driven
bounded cleanup without raw PID/PGID signalling, invalid-usage non-execution,
release tampering, and owner-token, inode, mode, hardlink, parent, and directory
mismatch.

### R2b — Capture and rotator integration

Files:

- `infra/scripts/capture-production-evidence.sh`
- `infra/scripts/rotate-production-mcp-client-cert.sh`
- `tests/test_runtime_exclusive_lock.py`
- `tests/test_production_evidence_preflight.py`

RED/GREEN command:

```sh
bash -n infra/scripts/capture-production-evidence.sh \
  infra/scripts/rotate-production-mcp-client-cert.sh
shellcheck infra/scripts/capture-production-evidence.sh \
  infra/scripts/rotate-production-mcp-client-cert.sh
uv run --locked pytest -q tests/test_runtime_exclusive_lock.py \
  tests/test_production_evidence_preflight.py \
  -k 'capture or rotator or runtime_lock'
```

The RED failure must prove at least one entrypoint can mutate before locking;
GREEN must prove acquisition precedes every side effect.

R2b is merged and source-accepted through PR #15 on
`main@13d15138a431ecbd4ca2a919cbf05b87a7a9004b`. The validated RED baseline and
green focused regression cell prove both callers acquire the shared lock before
side effects, fail closed under contention, retain their existing local
controls, release only on the owner path, and obey the synchronous/no-detach
contract. R2c/R2d and live rotation/no-op proof remain explicitly open.

### R2c — Protected runner integration

Files:

- `eval/datasets/v2/run_grounded_qa_v2.py`
- `tests/test_grounded_qa_v2.py`

RED/GREEN command:

```sh
uv run --locked ruff check eval/datasets/v2/run_grounded_qa_v2.py \
  tests/test_grounded_qa_v2.py
uv run --locked ruff format --check eval/datasets/v2/run_grounded_qa_v2.py \
  tests/test_grounded_qa_v2.py
uv run --locked pytest -q tests/test_grounded_qa_v2.py -k runtime_lock
```

GREEN proves the lock is held before protected-attempt ledger creation, model
access, evaluation output, or any other protected side effect.

### R2d — Performance runtime integration

Files:

- `infra/scripts/apply-perf-runtime.sh`
- `infra/scripts/rollback-perf-runtime.sh`
- `tests/test_perf_runtime_interlock.py`

RED/GREEN commands:

```sh
bash -n infra/scripts/apply-perf-runtime.sh \
  infra/scripts/rollback-perf-runtime.sh
shellcheck infra/scripts/apply-perf-runtime.sh \
  infra/scripts/rollback-perf-runtime.sh
uv run --locked ruff check tests/test_perf_runtime_interlock.py
uv run --locked ruff format --check tests/test_perf_runtime_interlock.py
uv run --locked pytest -q tests/test_perf_runtime_interlock.py
```

GREEN proves the lock precedes state-file writes, Colima changes, Compose calls,
or any runtime mutation in both directions.

### R3a — LaunchAgent installer

Files:

- `infra/launchd/com.mnemosyne.mcp-client-cert-rotator.plist.in`
- `infra/scripts/install-production-mcp-client-cert-rotator.sh`
- `tests/test_production_mcp_client_cert_rotator_install.py`
- `infra/prod/README.md`

RED (expected: missing installer/lifecycle behavior):

```sh
uv run --locked pytest -q \
  tests/test_production_mcp_client_cert_rotator_install.py
```

GREEN and focused regression:

```sh
bash -n infra/scripts/install-production-mcp-client-cert-rotator.sh
shellcheck infra/scripts/install-production-mcp-client-cert-rotator.sh
plutil -lint infra/launchd/com.mnemosyne.mcp-client-cert-rotator.plist.in
uv run --locked ruff check \
  tests/test_production_mcp_client_cert_rotator_install.py
uv run --locked ruff format --check \
  tests/test_production_mcp_client_cert_rotator_install.py
uv run --locked pytest -q \
  tests/test_production_mcp_client_cert_rotator_install.py
git diff --check
```

The test harness fakes `launchctl`; no real job is loaded in R3a.

### R3b — Status metrics and alerts

Files:

- `src/mnemosyne/ops_metrics.py`
- `src/mnemosyne/cli.py`
- `tests/test_ops_metrics.py`
- `infra/docker-compose.prod.yml`
- `infra/observability/vmalert/mnemosyne.yml`
- `tests/test_prod_compose_policy.py`

RED (expected: missing status schema/series/mount/alerts):

```sh
uv run --locked pytest -q tests/test_ops_metrics.py \
  tests/test_prod_compose_policy.py -k 'cert or rotation or status'
```

GREEN and focused regression:

```sh
uv run --locked ruff check src/mnemosyne/ops_metrics.py \
  src/mnemosyne/cli.py tests/test_ops_metrics.py \
  tests/test_prod_compose_policy.py
uv run --locked ruff format --check src/mnemosyne/ops_metrics.py \
  src/mnemosyne/cli.py tests/test_ops_metrics.py \
  tests/test_prod_compose_policy.py
uv run --locked pytest -q tests/test_ops_metrics.py \
  tests/test_prod_compose_policy.py
git diff --check
```

## R4 — Hardware-gated live rehearsal and activation

Prerequisites:

- Every code slice has fresh independent review and exact-head CI is green.
- The three-sample live runtime-change gate passes immediately before action.
- No capture, protected run, runtime change, test, model, or index owns/competes
  for the shared lock.
- CA, canonical Compose stack, Vault, API, and stream are healthy; any
  certificate-lifetime exception is only the repair trigger described above.

Procedure:

1. Run installer preflight and forced staged issuance without publication.
2. Validate the staged 24-hour pair and retain a non-secret receipt outside the
   repository.
3. Run one real rotation under the shared lock.
4. Prove exact-root TLS-1.3 mTLS with HTTP `2xx` on both routes, exact consumer
   recreation, stable restart counts, fresh blackbox success, and no
   secret-bearing output.
5. Run injected crash/rollback rehearsals only against fixtures, never by
   corrupting production.
6. Install/bootstrap the managed LaunchAgent, verify it with `launchctl print`,
   kick it once, and prove the subsequent invocation is an idempotent no-op.
7. Verify the status-only mount, metrics, alerts, external mode-`0600` logs, and
   an unavailable-Colima status rehearsal.

## Definition of Done

- Rotator R1a-R1c, shared lock R2a-R2d, LaunchAgent R3a, observability R3b,
  focused tests, operator documentation, and rollback runbook are merged.
- A hardware-admitted live rotation and subsequent LaunchAgent no-op are
  verified without capture overlap, policy change, secret disclosure, or
  service regression.
- Local focused checks, exact-head GitHub CI, and post-merge main CI are green.
- The working tree, branch, PR, main, and origin are consistent and clean.
- CBM refresh, GSD graph/state, gbrain durable knowledge, and project docs are
  refreshed only after their own hardware/provider admission and contain no
  stale completion claims.
- Project state records the installed label, external non-secret status
  location, live expiry derived at verification time, last successful rotation,
  remaining benchmark gates, and the human-only governance/reproduction items.
- No external performance number or public claim is released by this work.
