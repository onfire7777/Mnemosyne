---
type: milestone
title: Mnemosyne PR 86-87 and Wiki canonical delivery
date: '2026-07-30T00:00:00.000Z'
status: delivered-development-only
tags:
  - canonical-truth
  - development-only
  - mnemosyne
---

# Mnemosyne PR 86-87 and Wiki canonical delivery

PR #86 merged the bounded weekly/manual public-regression source as `661343ce05186e9a7f0f0740d1edef7c23532857`. This is development-only scheduled-regression source: it does not prove a real scheduled event, official benchmark, measured sandbox, publishable result, or launch readiness.

PR #87 merged canonical lifecycle truth as `2ba4ed80f48717e92caaa66aeef48d2d331cb0bc`. Successful post-merge `push` CI run `30566984814` executed at that exact merge SHA and completed the required CI jobs successfully. Run `30565062156` was the successful `pull_request` CI at head SHA `fcecee31672c6d00978b41ec779d68c7ae81be84`, not the post-merge run. The canonical checkout has `main == origin/main == 2ba4ed80f48717e92caaa66aeef48d2d331cb0bc`.

The Wiki checkout has `master == origin/master == 46c34287fe064842e72c3f52a9afad0c822b1846`. Its reconciled Home, Roadmap and Status, Calibration and Evaluation, and Development Guide pages preserve the non-publishable, non-headline, official-evidence-open, and scheduled-event-open boundaries.

Remaining gates are unchanged: Phase 12 measured closure is operator/protected-evidence blocked; the first real weekly cron receipt remains an external event; official MemoryAgentBench and BEAM evidence remains operator/admission blocked; result-v2 remains lease blocked; Phase 14 reproduction evidence and Phase 15 work remain dependency/evidence blocked; publication and launch remain human/evidence gated.

The current dependency and write-lease map admits no new source package and zero new implementation writers. T2 authorized only one deduplicated CBM refresh and this one durable milestone. No sandbox, result-v2, Phase 14-15, measurement, official benchmark, publication, or launch work was started.

## Sources

- `/Users/admin/Mnemosyne/docs/coordination/2026-07-28-remaining-dependency-write-lease-map.md` at `main@2ba4ed80`
- GitHub PR #86 and PR #87 merge/check records for `onfire7777/Mnemosyne`
- `/Users/admin/Mnemosyne.wiki` at `46c34287fe064842e72c3f52a9afad0c822b1846`
