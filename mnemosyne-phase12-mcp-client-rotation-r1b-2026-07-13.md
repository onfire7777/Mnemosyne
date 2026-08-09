---
type: project-status
title: Mnemosyne Phase 12 MCP Client Rotation R1b 2026-07-13
date: '2026-07-13T00:00:00.000Z'
project: Mnemosyne
---

# Mnemosyne Phase 12 MCP Client Rotation R1b 2026-07-13

Production MCP client certificate rotation R1b is source-complete and exact-head verified in `/Users/admin/Mnemosyne`.

## Evidence

- Branch: `codex/phase12-candidate-v19-custody`
- Commit: `b4547479224da94289f30550ebba8cb951c12eef`
- Draft PR: https://github.com/onfire7777/Mnemosyne/pull/11
- Exact-head CI: https://github.com/onfire7777/Mnemosyne/actions/runs/29238993180
- Required CI jobs and CodeRabbit passed.
- Local verification: 38 focused R1b cases, all 81 rotator cases, and 22 unchanged TLS/bootstrap regressions; Bash syntax, ShellCheck, Ruff, and diff hygiene passed.
- Independent operability and security closure reviews were clean after fixing a retained-old-generation digest revalidation gap.

## Durable Contract

R1b writes a strict bounded mode-0600 secret-free transaction journal and retains fsynced mode-0600 old/new certificate/key generations on the canonical filesystem before publication. Canonical certificate then key renames are parent-fsynced and phase-journaled. Startup recovery runs before ordinary pair validation, accepts only exact phase-reachable digest states, restores and normally validates the old pair, and removes the journal only after fsync. Malformed, unsafe, forged, mutated, mixed, or unreachable evidence fails closed without overwrite.

The R1b publication seam is fixture-only and intentionally stops before consumer activation. No live issuance, publication, Docker/Colima mutation, LaunchAgent action, model/index operation, exact-scale run, held-out attempt, protected attempt, external benchmark number, or public claim occurred.

## Next Gate

R1c owns exact Compose consumer activation, direct TLS 1.3 probes, bounded fresh blackbox verification, committed recovery, and full rollback. Live action remains deferred to the later three-sample hardware/runtime gate. CBM index refresh also remains deferred until its stronger hardware admission passes.

## Related

- [[Mnemosyne Tier-B Evidence Custody Status]]
- [[Memory system architecture contract]]
