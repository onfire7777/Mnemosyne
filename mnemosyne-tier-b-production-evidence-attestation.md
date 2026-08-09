---
type: concept
title: Mnemosyne Tier B Production Evidence Attestation
---

# Mnemosyne Tier-B production evidence attestation

As of 2026-07-07, the canonical Mnemosyne checkout is /Users/admin/Mnemosyne on main at e2a2795371ee710adfc26cc239703d6e5dc56e37. The branch is clean and even with origin/main.

Tier-B production evidence is attested by capture-bc10. The retained offline verifier report is /Users/admin/mnemosyne-evidence-out/verify-bc10-rerun-20260707T224653Z.json and returned ok:true with 0 findings. The bundle fingerprint is sha256:6dc117d6bb95e7a683915d432b2d2b21997133e9bfbd53624427a7317eeb2271. The row review reports 10 complete rows and no incomplete rows.

The GitHub CI run for e2a2795 is https://github.com/onfire7777/Mnemosyne/actions/runs/28904081989 and concluded success. Jobs included lint, unit plus drift checks, Postgres integration, and native wheel builds for Ubuntu and macOS.

The GitHub wiki was updated and pushed at 77252ed50749751b7b6575b505a385e974d1113f. CBM project Users-admin-Mnemosyne is ready, with ADR content updated to reflect capture-bc10, ADR-002 B9 CPU-parametric scope, and the supply-chain evidence caveat.

Important boundary: do not claim every Phase 8 security/supply-chain checklist item is closed from capture-bc10 alone. Supply-chain scanner/signature artifacts were not present in the retained capture, so that checklist remains an explicitly separate operator-evidence item unless later retained artifacts prove it.

## Related
[[docs/roadmap-to-100]]
[[docs/adr/adr-002-b9-parametric-tier-scope]]
[[infra/production-evidence]]
