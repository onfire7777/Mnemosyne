# Self-Hosted Production Stack - Run Guide

Turnkey bring-up for the **self-hosted, no-GPU** production profile. Architecture:
[`docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`](../../docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md).
Plan: [`.planning/phases/08-self-hosted-first-production/`](../../.planning/phases/08-self-hosted-first-production/).

> **Current evidence note:** the profile is now production-attested for Tier-B.
> The 2026-07-07 `capture-bc10` bundle passed a 29-command `deployment-soak`,
> `release-audit` (`ok:true`, 0 findings), and offline
> `production-evidence-verify` (`ok:true`, 0 findings) with bundle fingerprint
> `sha256:6dc117d6bb95e7a683915d432b2d2b21997133e9bfbd53624427a7317eeb2271`.

## What this stack satisfies
- **B1-B10** on real, self-hosted, no-GPU infra, when captured through the
  production evidence wrapper and verified against the retained fingerprint.
- **B9 / FR-21** is satisfied on this profile by the ADR-002 amended CPU-trained
  parametric adapter path. Cloud/GPU remains a scale and quality extension, not
  a prerequisite for the current attested Tier-B closure.

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

On a rerun, bootstrap exports the live Step CA root to
`step-ca-root.crt.next` first. If it differs from the active trust bundle,
bootstrap exits `78` and leaves the active file unchanged. Treat that as a CA
migration checkpoint: validate and rotate every dependent leaf/client
certificate in a maintenance window before publishing the staged root. Never
collapse a compatibility bundle merely because one leaf validates.

## Profile + readiness
```bash
cp infra/profiles/self-hosted.env /secure/outside/repo/production-render.env
# fill non-secret values; bind secrets to Vault/command/_FILE (never inline)
set -a; . /secure/outside/repo/production-render.env; set +a
infra/scripts/render-production-soak-manifest.sh --check-environment   # 0 missing -> ready_for_capture
```

## Capture / Recapture (B1-B10)
Follow [`infra/PRODUCTION-EVIDENCE.md`](../PRODUCTION-EVIDENCE.md): render -> preflight -> capture ->
manifest-bound `release-audit --require-production-validated --require-provider-forbid-local` ->
offline `production-evidence-verify` with the independently retained fingerprint record.
Rows flip Partial->Done only from that real evidence path; `capture-bc10` is the current attested bundle.

## Security gates that MUST hold before capture (see architecture §4)
Fail-closed defaults (MCP `require_session=1`, object encryption `aesgcm`, Vault starts sealed and
serving remains unavailable until operator unseal, MFA-gated elevation, fail-closed provenance);
Postgres least-privilege roles (`roles.sql`) with a live
`rolsuper`/`rolbypassrls` probe; single egress chokepoint; one published port (Caddy); digest-pinned
images + policy-as-code CI; tamper-evident audit log.

Before Tier-B capture, retain the supply-chain gate output outside the repo:

```bash
export MNEMOSYNE_COSIGN_CERTIFICATE_IDENTITY="expected signer identity"
export MNEMOSYNE_COSIGN_CERTIFICATE_OIDC_ISSUER="https://token.actions.githubusercontent.com"
infra/scripts/verify-supply-chain.sh --out-dir /secure/outside/repo-evidence/supply-chain
```

This fails closed unless gitleaks, Trivy, Syft, Grype, and cosign all run and every registry image is
tag+digest pinned and signature-verified.

## Cloud / GPU Extension
```bash
set -a; . infra/profiles/self-hosted.env; . infra/profiles/cloud.env; set +a
```
Same gates, same manifest - values only. Use this when larger accelerator-backed
providers are desired; do not treat it as required for the current B9 attestation.
