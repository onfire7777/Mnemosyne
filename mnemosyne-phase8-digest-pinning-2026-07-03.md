---
type: concept
title: Mnemosyne Phase 8.5 digest pinning refresh
date: '2026-07-03T00:00:00.000Z'
head: cf040ae19e413a3033148c05f4a201de65ecc40f
branch: phase3/providers-consolidation
ci_run: 28681784399
project: mnemosyne
---

# Mnemosyne Phase 8.5 digest pinning refresh

As of 2026-07-03, `/Users/admin/Mnemosyne` is clean and pushed on `phase3/providers-consolidation` at `cf040ae19e413a3033148c05f4a201de65ecc40f`; GitHub Actions run `28681784399` passed for that head.

Source-owned Phase 8.5 supply-chain hardening progressed: every committed production registry image in `infra/docker-compose.prod.yml` is now pinned as `tag@sha256:digest`, and `tests/test_prod_compose_policy.py` rejects tag-only registry images. Local verification passed: compose policy tests, production manifest renderer/runbook consistency bundle, full `ruff check`, `git diff --check`, `docker compose -f infra/docker-compose.prod.yml config --no-interpolate`, and added-line secret scan.

The parent Phase 8.5 supply-chain item is still open because Trivy/Grype/Syft/gitleaks evidence and deploy-time cosign verification still require real operator/deploy surfaces. Tier-B parity is still blocked by external operator evidence: custody remains `ready_for_capture=false`, with six provider manifest env refs blank or unset and 23 missing production input artifacts.
