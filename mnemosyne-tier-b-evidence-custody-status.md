---
type: project-status
title: Mnemosyne Tier-B Evidence Custody Status
updated: '2026-07-03T00:00:00.000Z'
tags:
  - custody
  - mnemosyne
  - production-evidence
  - tier-b
---

# Mnemosyne Tier-B Evidence Custody Status

As of 2026-07-03, `/Users/admin/Mnemosyne` is clean and synchronized on `phase3/providers-consolidation` at `61120d315a759c1e21f61efd4ca9b538c0f3a991`, with GitHub CI run `28677518645` passing for that SHA. This does not close Tier-B parity, because the production/operator evidence packet remains blocked.

## Current Blockers

The official custody refresh command exits `78` against `/Users/admin/mnemosyne-tier-b-custody` and reports `ready_for_capture=false` in `reports/tier-b-gap-report.json`.

Provider manifest refs are present as key names in `/Users/admin/mnemosyne-prod-secrets/mnemosyne-production-runtime.env`, but the six required values are blank and not exported in the process environment:

- `MNEMOSYNE_ALLOWED_RESIDENCY_TRANSFERS`
- `MNEMOSYNE_EMBEDDING_API_KEY`
- `MNEMOSYNE_MEDIA_EMBEDDING_COMMAND`
- `MNEMOSYNE_MEDIA_EXTRACTOR_COMMAND`
- `MNEMOSYNE_PARAMETRIC_COMMAND`
- `MNEMOSYNE_RERANKER_API_KEY`

The packet also lacks 23 production input artifacts across rows B1-B10. These are operator-owned production captures, not repo fixtures.

## Evidence Boundary

An ignored local file exists at `/Users/admin/Mnemosyne/production-inputs/provenance-trust-suite.json`, but it is untracked, small, and shaped like a local/sample suite (`cases`, `name`, `tool`). The custody contract for `provenance-trust-suite.json` requires a real row-runbook production artifact retained under `/Users/admin/mnemosyne-tier-b-custody/input-artifacts/`; copying the local ignored file would be a false evidence promotion.

## Documentation And Workflow State

On 2026-07-03 the branch added two documentation checkpoints:

- `8527825497feb73af65e63932391b36897f60965`: clarified in `.planning/ENV-AND-SECRETS.md` and `infra/templates/production-operator-env.inventory.md` that blank runtime env-file values count as missing provider manifest refs.
- `61120d315a759c1e21f61efd4ca9b538c0f3a991`: refreshed `.planning/STATE.md` to match `.planning/ROADMAP.md` counters and record the current Tier-B custody blocker.

## Durable Rule

Do not claim blueprint parity or Tier-B completion until the external custody packet contains real operator-captured production artifacts, non-empty provider env values, a manifest-bound `release-audit`, and offline `production-evidence-verify` evidence with an independently retained fingerprint record.

## Related

- [[Memory system architecture contract]]
- [[Mnemosyne gstack gbrain separation]]
