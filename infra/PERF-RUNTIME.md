# PERF-RUNTIME — VM resize + host-Metal LLM as the default (Lane A/E, P1/P2)

Runbook for `infra/scripts/apply-perf-runtime.sh` / `rollback-perf-runtime.sh`
and the resource-ceiling + default-topology edits in
`infra/docker-compose.prod.yml`.

**host-Metal LLM serving is now the COMMITTED DEFAULT topology.** A plain
`docker compose -f infra/docker-compose.prod.yml up -d` brings up the
`host-llm-proxy` relay and leaves in-VM `ollama` OFF (opt-in `in-vm-llm`
profile). There is **no overlay and no manual flip** — the fragile runtime
`OLLAMA_URL` overlay that the earlier `--host-llm` path generated is GONE.

The resource ceilings and the VM resize are the only things `apply-perf-runtime.sh`
still does that a bare `up -d` cannot (the VM resize needs a colima stop/start).
Everything here is **committed on the branch; the VM resize + recreate has not
been forced onto the live stack** — a later controlled phase applies it. All
probes used to write this document were read-only.

## When to run

**ONLY AFTER the pending production evidence capture is complete.** The apply
script resizes the colima VM (full stop/start of all containers) and
`up -d` recreates every service that gained a `cpus:`/`mem_limit:` ceiling and
starts the default host-Metal relay. Any Tier-B evidence capture in flight at
that moment is invalidated. Do not run while the remaining ops bundles
(auth-ops assembly, policy-ops, privacy-ops, multimodal-ops, consolidation-ops,
provenance pair, row-10) are being captured against the current runtime.

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
95–133 s in the VM lands in ~2–4 s on the host. Because host Metal is now the
default path, `qwen3:4b` is the committed role model. The 280–320 s
ladder/subprocess timeouts on the consolidator can eventually be shrunk
(separate, evidence-gated change — do not bundle it into this topology change).

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
- Hence the **`host-llm-proxy` relay** (now DEFAULT-ON): a digest-pinned caddy
  `reverse-proxy` on `edge` + the dedicated `hostllm` client network
  (`internal: true`), forwarding `http://host-llm.mnemo.local:11434` →
  `host.docker.internal:11434`. Only the relay gains host egress; the clients
  merely gain `hostllm` membership. The relay carries a healthcheck (`wget`
  the host `/api/version` through its own :11434 listener) so its serve state
  is visible; nothing `depends_on` that health.
- The relay is deliberately **NOT on the general `internal` network**: the
  VM→host bridge it exposes is unauthenticated, so its reach is narrowed to
  the sanctioned LLM clients only — consolidator, role-http, and the two
  profile-gated bastions (operator, test-runner) are the sole services
  attached to `hostllm`. test-runner already holds `edge` (direct host
  access), so `hostllm` grants it no new reach — only relay-alias resolution.
  caddy/api/metrics (and everything else on `internal`) cannot reach it
  (policy gate: `test_host_llm_relay_network_is_least_privilege`).

## What the compose edits do

Default-topology + ceiling edits in `docker-compose.prod.yml` (a plain `up -d`
after the VM resize applies them all):

| service            | cpus | mem_limit | note                          |
|--------------------|------|-----------|-------------------------------|
| host-llm-proxy     | —    | 256m      | **DEFAULT-ON** relay to host-Metal ollama |
| ollama (in-VM)     | 3.0  | 6g (kept) | **OFF by default** — opt-in `in-vm-llm` profile |
| embedder           | 2.0  | 4g (kept) |                               |
| postgres           | 2.0  | 2g (new)  |                               |
| mnemo-api          | 2.0  | 1g (new)  |                               |
| mnemo-consolidator | 2.0  | 1g (new)  |                               |

Because in-VM `ollama` is now `profiles: ["in-vm-llm"]` (OFF by default), its
6g is freed on a plain `up -d`. The explicit ceilings of the default set sum to
~10 GiB nominal (4 embedder + 2 postgres + 1 api + 1 consolidator + 1 keycloak
+ 0.25 relay) against the 12 GiB VM target — ceilings are guards, not
reservations. Bring in-VM `ollama` back (its 6g re-enters the budget) only if
host Metal is unavailable. The small stdlib services (mnemo-metrics,
alert-sink, mnemo-stream, role-http, parametric-http) and the profile-gated
bastions (operator, test-runner — these run whole capture/test suites and a
cap risks OOM-killing evidence runs) stay uncapped deliberately.

The LLM clients (mnemo-consolidator, role-http, operator, test-runner) set
`OLLAMA_URL: http://host-llm.mnemo.local:11434` as the committed default. The
in-VM fallback (see below) repoints them at `http://ollama.mnemo.local:11434`.

Also in this change (earlier perf work, retained): `parametric-http` uses the
same `build: {…, target: runtime}` stanza as role-http instead of
`image: infra-role-http`, which violated the digest-pin policy gate
(`test_every_registry_image_is_digest_pinned`) and silently depended on the
compose project name. Identical layers via build cache.

## Applying (operator action)

```sh
export MNEMO_SECRETS_DIR="$HOME/mnemosyne-prod-secrets"
MNEMO_CONFIRM=1 infra/scripts/apply-perf-runtime.sh          # resize + ceilings + default host-Metal relay
```

`--host-llm` is still accepted but is a **no-op** (host-Metal is the default
now); the script prints a notice and proceeds identically.

Steps (each echoed): record current colima size → state file; `colima stop
&& colima start --cpu 6 --memory 12`; `up -d` (applies ceilings, starts the
host-llm-proxy relay, leaves in-VM ollama off); post-checks (`compose ps` +
a role-LLM `/api/version` probe run inside role-http against its active
`OLLAMA_URL`, i.e. through the relay to host Metal).

There is **no runtime overlay** — the default `OLLAMA_URL` values are committed
in the compose file, so what `up -d` renders is exactly the deployed topology.

Knobs (documented here per the config-drift rules; also registered in
`CONFIG-DRIFT-CHECKS.md`):

- `MNEMO_CONFIRM` — must be `1` for either script to act (default: refuse).
- `MNEMO_PERF_VM_CPUS` / `MNEMO_PERF_VM_MEMORY` — resize target (default 6 / 12 GiB).
- `MNEMO_PERF_STATE_FILE` — where the prior VM size is recorded
  (default `~/.mnemosyne-perf-runtime-state`); rollback reads it.

## In-VM ollama fallback (opt-in)

If host Metal is unavailable, restore in-VM serving with the `in-vm-llm`
profile and repoint the clients:

```sh
COMPOSE_PROFILES=in-vm-llm docker compose -f infra/docker-compose.prod.yml up -d ollama
# then set OLLAMA_URL=http://ollama.mnemo.local:11434 on the LLM clients (and drop
# the role model to qwen3:0.6b — in-VM 4b serving is ~0.5 tok/s / unusable).
```

Notes:

- A plain `docker compose up -d` **keeps host Metal as the default** and does
  NOT start in-VM ollama (it is `profiles: ["in-vm-llm"]`). This is the
  inverse of the old overlay behavior — no re-flip is needed after a recreate.
- The LLM clients no longer `depends_on: ollama`, so starting a client by name
  never drags the in-VM ollama profile in. Bring ollama up explicitly (command
  above) when you want the fallback.

## Rolling back

```sh
MNEMO_CONFIRM=1 infra/scripts/rollback-perf-runtime.sh [ref]
```

Restores the recorded prior VM size (fallback: the measured pre-perf
4 CPU / 10 GiB), checks out `infra/docker-compose.prod.yml` from `ref`
(default `ee30b5b`, the perf-branch base — before the ceilings AND before
host-Metal became the default), then `up -d --remove-orphans` — which reverts
to in-VM ollama as the default LLM path and prunes the now-orphaned
host-llm-proxy relay container.

## Evidence-bundle re-drill implications

Making host Metal the default changes the role-LLM serving path (in-VM
container → host Metal via relay), its latency class, and the deployed compose
topology. After applying:

- **consolidation-ops / worker-ops** — MUST be re-drilled: the live
  consolidate_evidence drill, ladder timeout facts (sized to ~0.5 tok/s), and
  queue/latency evidence all describe the old runtime.
- **hosted-llm manifest / role-http checks** — MUST be re-drilled: role-http's
  upstream is now the relay; hosted-llm-check + soak evidence must be
  recaptured against the new path.
- Any bundle asserting container topology or restart counts (e.g.
  ops-dashboard probes) should be sanity-rechecked after the VM restart.

Evidence captured BEFORE this change remains valid for the old runtime — which
is exactly why the default-topology recreate must wait for the pending capture
to finish.
