---
type: concept
title: Mnemosyne Phase 8 Supply Chain Gate
date: '2026-07-03T00:00:00.000Z'
repo: /Users/admin/Mnemosyne
branch: phase3/providers-consolidation
commit: 58fa10b93f424c6abdffede9fb0fa76f902efd1c
status: source-control-progress
project: Mnemosyne
---

# Mnemosyne Phase 8 Supply Chain Gate

On 2026-07-03, Mnemosyne Phase 8.5 source hardening added `infra/scripts/verify-supply-chain.sh` on branch `phase3/providers-consolidation`.

The gate is intentionally fail-closed and operator-facing:

- requires an explicit external `--out-dir` or `MNEMOSYNE_SUPPLY_CHAIN_OUT`, so scanner artifacts are not written into the repo;
- requires `docker`, `gitleaks`, `trivy`, `syft`, `grype`, and `cosign`;
- requires a cosign public key or keyless identity plus OIDC issuer policy;
- runs gitleaks over git history and current tree;
- runs Trivy, Syft, and Grype over the repo and digest-pinned registry images from `infra/docker-compose.prod.yml`;
- records local compose-built image names as source-scanned local builds instead of pretending they are registry-signed.

Verification in Codex before push:

- `uv run --locked ruff check` passed.
- `uv run --locked pytest tests/test_prod_compose_policy.py tests/test_production_runbook_consistency.py tests/test_infra_script_hardening.py -q` passed.
- `git diff --check` passed.
- `uv run --locked pytest -q` passed.

Boundary: this does not complete Tier-B or Phase 8. Scanner/signature evidence still has to be operator-retained from a machine with Trivy, Syft, Grype, and cosign installed, and production custody remains blocked by blank provider env refs plus missing production input artifacts.
