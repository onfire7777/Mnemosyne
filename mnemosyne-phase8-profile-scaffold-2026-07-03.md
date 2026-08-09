---
type: concept
title: Mnemosyne Phase 8.1 status refresh
date: '2026-07-03T00:00:00.000Z'
head: aaf13422a4f79d15ac5f3083cfad4d6f1bb8949d
branch: phase3/providers-consolidation
ci_run: 28681189928
project: mnemosyne
ingested_via: put_page
ingested_at: '2026-08-09T03:48:33.330Z'
source_kind: put_page
---

# Mnemosyne Phase 8.1 status refresh

As of 2026-07-03, `/Users/admin/Mnemosyne` is clean and pushed on `phase3/providers-consolidation` at `aaf13422a4f79d15ac5f3083cfad4d6f1bb8949d`; GitHub Actions run `28681189928` passed for that head.

Phase 8.1 self-hosted profile scaffold is complete: stale completion/status docs were archived under `docs/_archive/2026-07-03/`, `infra/docker-compose.prod.yml` gained internal-only `vmalert`, `infra/observability/vmalert/mnemosyne.yml` defines stale ops report and release-gate alerts, `infra/profiles/self-hosted.env` now carries explicit `forbid_local:true` guidance, and focused compose/runbook policy tests cover the new contract.

Tier-B parity is still blocked by external operator evidence, not by local code cleanliness. The custody verifier against `/Users/admin/mnemosyne-tier-b-custody` still reports `ready_for_capture=false`, six provider manifest env refs blank or unset, and 23 missing production input artifacts. Do not claim blueprint parity or Tier-B completion until the operator-owned packet is populated and the custody verifier passes.
