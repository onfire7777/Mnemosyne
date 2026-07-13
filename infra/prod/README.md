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

The MCP ingress uses a short-lived step-ca client certificate. Before any
capture or hardware-intensive run, validate the full client-auth chain and its
six-hour renewal floor:

```bash
SECRETS_DIR=${MNEMO_SECRETS_DIR:-/secure/outside/repo}
infra/validate/validate-production-mcp-client-tls.sh \
  "$SECRETS_DIR/stepca-acme-root.crt" \
  "$SECRETS_DIR/mcp-client.crt" \
  "$SECRETS_DIR/mcp-client.key"
```

`stepca-acme-root.crt` is the exact trust pool Caddy mounts for client-auth;
the broader compatibility bundle is not an admissible substitute. The
validator is fail-closed for exact trust-pool identity, required OpenSSL
features, leaf or chain expiry at the renewal horizon, hostname, client-auth
purpose, chain, key mismatch, symlinks, encrypted keys, and unsafe private-key
permissions. Never place the private key or the step-ca
provisioner password in argv, environment snapshots, logs, evidence bundles,
or the repository.

The R1c blackbox query helper is intentionally non-configurable: it accepts
only the activation start epoch, selects exactly one running `infra` Caddy
container by Compose labels, and queries the fixed internal
`probe_success{job="blackbox-tls",instance="https://mcp.mnemo.local"}` vector.
It rejects stale, ambiguous, oversized, malformed, or non-exact responses and
prints only a fixed success or failure summary. The helper is source-complete
but is not yet wired to live rotation; do not treat its presence as approval
to recreate consumers or mutate the active certificate pair before the later
R1c activation, rollback, and hardware-admission gates are complete.

The rotator's R1c **fixture seam only** now proves the activation custody that
will surround that helper. Before fixture issuance it takes one bounded,
project-scoped Docker snapshot and requires exactly one running `infra` blackbox
exporter plus at most one running `infra` operator by Compose labels. It
validates both external Keycloak password files against the closed mode/length/
ASCII contract and records only prior running-state booleans. Each recreated
fixture consumer receives a short-lived mode-`0600`
dotenv under the external mode-`0700` rotation directory. Before any password
byte is written, the schema-v2 transaction journal durably binds a planned token
and then the exact single-link dotenv inode; a transaction-bound schema-v2
receipt is published only after the payload and `ready` state are durable.
Neither durable record stores password bytes, a password-derived verifier, or
password-length metadata. Sanitized Compose children
receive no ambient environment or password in argv. Cleanup durably enters
`cleanup`, uses no-replace quarantine plus post-rename inode validation, and
clears ownership last. Before fixed-receipt publication, the matching journal
may recover only missing receipt state or exact owner-scoped partial temporary/
quarantine residue. Once the fixed receipt exists, exact schema-v2 transaction/
token/inode/link binding is mandatory; legacy or malformed fixed receipts,
cross-transaction state, extra links, replacements, and foreign artifacts are
preserved and fail closed. After each recreation the fixture takes one equally
bounded snapshot and requires the same categorical consumer state, then
deliberately fails before direct probes, durable commit, or
rollback. The normal production path still returns `staged_only` and cannot
recreate a live consumer, so this source evidence is not authorization to run a
live rotation.

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
