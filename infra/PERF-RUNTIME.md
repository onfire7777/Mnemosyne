# PERF-RUNTIME — VM resize + host-Metal LLM flip (Lane E, P1/P2)

Runbook for `infra/scripts/apply-perf-runtime.sh` / `rollback-perf-runtime.sh`
and the resource-ceiling edits in `infra/docker-compose.prod.yml`. Everything
here is **prepared on the branch only — nothing has been applied to the live
stack**. All probes used to write this document were read-only.

## When to run

**ONLY AFTER the pending production evidence capture is complete.** The apply
script resizes the colima VM (full stop/start of all containers) and
`up -d` recreates every service that gained a `cpus:`/`mem_limit:` ceiling.
Any Tier-B evidence capture in flight at that moment is invalidated. Do not
run while the remaining ops bundles (auth-ops assembly, policy-ops,
privacy-ops, multimodal-ops, consolidation-ops, provenance pair, row-10) are
being captured against the current runtime.

Both scripts print their full plan and refuse to act unless `MNEMO_CONFIRM=1`.

## Why: measured host-Metal throughput vs in-VM (2026-07-05)

Host ollama 0.24.0 (`/opt/homebrew/bin/ollama`, brew service, Metal GPU),
`/api/generate`, `num_predict=200`, `temperature=0`, tok/s =
`eval_count / eval_duration * 1e9`:

| model      | run           | tok/s | load_duration | prompt_eval |
|------------|---------------|-------|---------------|-------------|
| qwen3:4b   | 1 (cold load) | 27.4  | 3.45 s        | 0.96 s      |
| qwen3:4b   | 2 (warm)      | 23.8  | 0.27 s        | 0.11 s      |
| qwen3:0.6b | 1 (cold load) | 75.2  | 21.3 s        | 0.88 s      |
| qwen3:0.6b | 2 (warm)      | 52.9  | 0.53 s        | 0.10 s      |

The documented in-VM figure for qwen3:4b under full-stack load is
**~0.5 tok/s** (see the consolidator's compose comments). Host Metal is
therefore **~48–55x faster for qwen3:4b** — a warm 4b role call that took
95–133 s in the VM lands in ~2–4 s on the host. Post-flip, `qwen3:4b`
becomes a viable role model again and the 280–320 s ladder/subprocess
timeouts on the consolidator can eventually be shrunk (separate,
evidence-gated change — do not bundle it into the flip).

## VM → host reachability (probe-verified, read-only)

| From                                          | `host.docker.internal`       | `host.lima.internal` |
|-----------------------------------------------|------------------------------|----------------------|
| fresh container w/ `--add-host=…:host-gateway`| **OK** (ollama 0.24.0)       | no DNS               |
| `infra-mnemo-api-1` (edge+internal+datasec)   | **OK, resolves natively** → 192.168.65.254 | no DNS |
| `infra-operator-1` (edge+internal+datasec)    | **OK, resolves natively**    | —                    |
| `infra-mnemo-consolidator-1` (internal+datasec only) | FAIL — no DNS, and direct IP 192.168.65.254 is `Network is unreachable` | FAIL |
| `infra-role-http-1` (internal only)           | FAIL — no DNS                | —                    |

Conclusions:

- The working alias is **`host.docker.internal`** (colima's dockerd resolves
  it natively for containers on at least one non-internal network;
  `host.lima.internal` only exists inside the Lima VM itself, not in
  containers).
- `internal: true` networks have **no route to the host gateway by design**,
  so the LLM clients (consolidator, role-http) can never talk to host ollama
  directly — and must not be given edge membership (policy gate:
  `test_network_segmentation_holds` pins the consolidator off `edge`).
- Hence the **`host-llm-proxy` relay** (profile `host-llm`, default OFF): a
  digest-pinned caddy `reverse-proxy` on `edge` + the dedicated `hostllm`
  client network (`internal: true`), forwarding
  `http://host-llm.mnemo.local:11434` → `host.docker.internal:11434`. Only
  the relay gains host egress; the clients merely gain `hostllm` membership.
- The relay is deliberately **NOT on the general `internal` network**: the
  VM→host bridge it exposes is unauthenticated, so its reach is narrowed to
  the sanctioned LLM clients only — consolidator, role-http, and the
  operator bastion are the sole services attached to `hostllm`.
  caddy/api/metrics (and everything else on `internal`) cannot reach it
  (policy gate: `test_host_llm_relay_network_is_least_privilege`).

## What the compose edits do (committed, NOT applied)

Ceilings added in `docker-compose.prod.yml` (a plain `up -d` after the VM
resize applies them):

| service            | cpus | mem_limit | note                          |
|--------------------|------|-----------|-------------------------------|
| ollama             | 3.0  | 6g (kept) | heaviest burner, can't starve the stack |
| embedder           | 2.0  | 4g (kept) |                               |
| postgres           | 2.0  | 2g (new)  |                               |
| mnemo-api          | 2.0  | 1g (new)  |                               |
| mnemo-consolidator | 2.0  | 1g (new)  |                               |
| host-llm-proxy     | —    | 256m      | profile-gated relay           |

Against the 12 GiB VM target the explicit ceilings sum to 15 GiB nominal
(6+4+2+1+1+1 incl. keycloak's pre-existing 1g) — ceilings are guards, not
reservations; with the host-LLM flip active, in-VM ollama is stopped and the
nominal sum drops to 9 GiB. The small stdlib services (mnemo-metrics,
alert-sink, mnemo-stream, role-http, parametric-http) and the profile-gated
bastions (operator, test-runner — these run whole capture/test suites and a
cap risks OOM-killing evidence runs) stay uncapped deliberately.

Also in this change: `parametric-http` now uses the same
`build: {…, target: runtime}` stanza as role-http instead of
`image: infra-role-http`, which violated the digest-pin policy gate
(`test_every_registry_image_is_digest_pinned` was RED at the branch base) and
silently depended on the compose project name. Identical layers via build
cache.

## Applying (operator action)

```sh
export MNEMO_SECRETS_DIR="$HOME/mnemosyne-prod-secrets"
MNEMO_CONFIRM=1 infra/scripts/apply-perf-runtime.sh              # resize + ceilings only
MNEMO_CONFIRM=1 infra/scripts/apply-perf-runtime.sh --host-llm   # …plus the host-LLM flip
```

Steps (each echoed): record current colima size → state file; `colima stop
&& colima start --cpu 6 --memory 12`; `up -d`; optional flip (verify host
ollama serves, start relay under `COMPOSE_PROFILES=host-llm`, overlay
`OLLAMA_URL=http://host-llm.mnemo.local:11434` onto
consolidator/role-http/operator, `stop ollama`); post-checks (`compose ps`
+ role-LLM `/api/version` probe through role-http's active URL).

The overlay is generated at runtime (mktemp) and mirrors the commented
`OLLAMA_URL` flip lines in the compose file, so the committed default
topology stays byte-identical to what is deployed today.

Knobs (documented here per the config-drift rules; also registered in
`CONFIG-DRIFT-CHECKS.md`):

- `MNEMO_CONFIRM` — must be `1` for either script to act (default: refuse).
- `MNEMO_PERF_VM_CPUS` / `MNEMO_PERF_VM_MEMORY` — resize target (default 6 / 12 GiB).
- `MNEMO_PERF_STATE_FILE` — where the prior VM size is recorded
  (default `~/.mnemosyne-perf-runtime-state`); rollback reads it.

Caveats:

- A later plain `docker compose up -d` **restarts in-VM ollama** (it is
  deliberately not profile-gated, to keep the committed default topology
  unchanged) and drops the OLLAMA_URL overlay on recreate — re-run
  `apply-perf-runtime.sh --host-llm` after any manual full `up -d`.
- `mnemo-consolidator` keeps `depends_on: ollama`; starting it by name will
  also start in-VM ollama. Harmless (idle ollama uses little CPU), but stop
  it again if memory headroom matters.

## Rolling back

```sh
MNEMO_CONFIRM=1 infra/scripts/rollback-perf-runtime.sh [ref]
```

Restores the recorded prior VM size (fallback: the measured pre-flip
4 CPU / 10 GiB), checks out `infra/docker-compose.prod.yml` from `ref`
(default `ee30b5b`, the perf-branch base), then
`up -d --remove-orphans` — which restarts in-VM ollama and removes the relay.

## Evidence-bundle re-drill implications

The flip changes the role-LLM serving path (in-VM container → host Metal via
relay), its latency class, and the deployed compose topology. After applying:

- **consolidation-ops / worker-ops** — MUST be re-drilled: the live
  consolidate_evidence drill, ladder timeout facts (sized to ~0.5 tok/s), and
  queue/latency evidence all describe the old runtime.
- **hosted-llm manifest / role-http checks** — MUST be re-drilled: role-http's
  upstream is now the relay; hosted-llm-check + soak evidence must be
  recaptured against the new path.
- Any bundle asserting container topology or restart counts (e.g.
  ops-dashboard probes) should be sanity-rechecked after the VM restart.

Evidence captured BEFORE the flip remains valid for the old runtime — which
is exactly why the flip must wait for the pending capture to finish.
