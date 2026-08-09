---
type: milestone
title: Mnemosyne whole-memory common ABI delivery
date: '2026-07-28T00:00:00.000Z'
project: Mnemosyne
tags:
  - common-abi
  - mnemosyne
  - source-delivery
  - whole-memory
---

# Mnemosyne whole-memory common ABI delivery

Mnemosyne delivered the closed `wmbs/0.1-draft` whole-memory common ABI to `main` through PR #79 on 2026-07-28. This is a source-delivery milestone only: it does not establish a benchmark score, superiority claim, production readiness, publication readiness, or result-v2 completion.

## Source evidence

- PR: https://github.com/onfire7777/Mnemosyne/pull/79
- Delivered head: `8d64f554c565edeb0c43868ff6d436e6e09df33a`
- Normal merge commit on `main`: `a95fe4d291093253f8ce49adff32ba875a35e884`
- Schema: `eval/public/schema/wmbs-0.1-draft.schema.json`
- Standard-library reference validator: `eval/public/adapters/whole_memory_reference.py`
- Contract tests: `tests/test_public_whole_memory_reference.py`
- Frozen schema SHA-256: `cbf79292ef6e9840b2b148e1457699e6aace33e10f9389895c661b1aa3d29376`
- Focused ABI suite: 67 passed.
- Exact-head PR CI: run `30410191434`, successful.
- Post-merge CI on `a95fe4d291093253f8ce49adff32ba875a35e884`: run `30411040920`, successful; the nightly chaos soak was skipped as explicitly non-gating.
- CodeRabbit approved the exact head, Greptile was green, and all 23 review threads were resolved before merge.

## Boundary and next dependency

The delivered slice defines closed operations, envelopes, evidence definitions, canonicalization, ordering, replay/idempotency, deadline, finalization, and bounded in-memory validation behavior. Result-v2 remains the next dependency. Official and enhanced benchmark tracks must remain separate, and this milestone must not be cited as benchmark or publication proof.
