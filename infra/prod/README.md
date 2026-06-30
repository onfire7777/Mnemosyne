# Self-Hosted Production Stack — Run Guide

Turnkey bring-up for the **self-hosted, no-GPU** production profile. Architecture:
[`docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`](../../docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md).
Plan: [`.planning/phases/08-self-hosted-first-production/`](../../.planning/phases/08-self-hosted-first-production/).

> **Honesty note:** this is a complete, coherent *scaffold*. First bring-up needs a validation pass
> (init ordering for Vault/Keycloak/step-ca, image digest pinning, realm/policy specifics). It is not
> claimed battle-tested until a real `up` + the `*-ops-check` gates pass — consistent with the project's
> "measure before claiming" rule.

## What this stack satisfies
- **B1–B8 + B10** on real, self-hosted, no-GPU infra.
- **B9 / FR-21 (GPU LoRA / test-time-training) is NOT satisfiable here** — it requires the `cloud`
  profile (`infra/profiles/cloud.env`) with a real GPU trainer, or an explicit ADR changing the strict
  audit. The no-GPU host does **not** reach strict v1.0 100% by itself.

## Prerequisites
- Docker (rootless or Docker Desktop), ~10 GB free RAM headroom, a non-loopback hostname (`MNEMO_HOST`,
  default `mnemo.local`) resolving to this box on the LAN/VPN. A host firewall (DOCKER-USER/pf/nftables)
  for egress-deny — **required**; rootless/Docker-Desktop without it = egress chokepoint NOT achieved.

## Bring-up
```bash
export MNEMO_HOST=mnemo.local
infra/prod/bootstrap.sh                       # step-ca, Vault init, Keycloak realm, secrets (outside repo)
docker compose -f infra/docker-compose.prod.yml up -d
# trust the step-ca root on the host so chains validate (no tls_insecure_skip_verify anywhere)
```

## Profile + readiness
```bash
cp infra/profiles/self-hosted.env /secure/outside/repo/production-render.env
# fill non-secret values; bind secrets to Vault/command/_FILE (never inline)
set -a; . /secure/outside/repo/production-render.env; set +a
infra/scripts/render-production-soak-manifest.sh --check-environment   # 0 missing -> ready_for_capture
```

## Capture (per row, B1–B8 + B10)
Follow [`infra/PRODUCTION-EVIDENCE.md`](../PRODUCTION-EVIDENCE.md): render → preflight → capture →
`production-evidence-verify` → manifest-bound `release-audit --require-production-validated
--require-provider-forbid-local`. Each pass flips its strict-audit row Partial→Done on **real** evidence.

## Security gates that MUST hold before capture (see architecture §4)
Fail-closed defaults (MCP `require_session=1`, object encryption `aesgcm`, sealed Vault, MFA-gated
elevation, fail-closed provenance); Postgres least-privilege roles (`roles.sql`) with a live
`rolsuper`/`rolbypassrls` probe; single egress chokepoint; one published port (Caddy); digest-pinned
images + policy-as-code CI; tamper-evident audit log.

## Cloud / GPU (B9)
```bash
set -a; . infra/profiles/self-hosted.env; . infra/profiles/cloud.env; set +a   # adds the GPU trainer
```
Same gates, same manifest — values only.
