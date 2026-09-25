# Activation-memory research (Phase 15 S5)

Internal index for the CAP-009 cartridge comparison and the CAP-010
activation-space diagnostics. Task `15-04-05` is the decision owner.

This directory is evaluation-only. It sits off the product write path.
It makes no consciousness claim and no authorization claim. Nothing here
grants write, trust, capability, mutation, or promotion authority.

## Decision

The authoritative closure is [GO-NO-GO.md](GO-NO-GO.md). It states one
decision for each path: cartridge A/B, J-lens tripwire, and persona drift.
Each decision is exactly one of `adopt`, `research-only`, or `reject`.
Those decisions are relative to evidence tip
`097bd6828c190e28261d799f4b57c4b3d038ec52` and do not adopt any path into
the product.

## Contract

`research/activation-memory/contract.py` validates reduced external JSON
observations (`schema_id` `activation-memory-development/observations/0.1`).
It does not import model libraries, store raw activations, or expose a
product write path. Development pins live in
`research/activation-memory/fixtures/development.json`.

## Receipts

| Path | Role |
| --- | --- |
| `eval/benches/reports/phase15-s5-cartridge.json` | CAP-009 cartridge A/B receipt (`mnemosyne.cap009.cartridge-receipt/v1`) |
| `research/activation-memory/reports/phase15-s5-j-lens.json` | J-lens tripwire receipt (`activation-memory-development/j-lens-tripwire/0.1`) |
| `research/activation-memory/reports/phase15-s5-persona-drift.json` | Persona-drift receipt (`activation-memory-development/persona-drift-diagnostic/0.1`) |

Cite those files by the identity hashes recorded inside them. See
[GO-NO-GO.md](GO-NO-GO.md).

## Non-goals

No production activation capture, concept injection, model-weight write,
memory mutation, automatic quarantine, automatic abstention, provider
promotion, core model dependency, official score, public claim, or launch
gate. Requirements CAP-009 and CAP-010 in `.planning/REQUIREMENTS.md` stay
unsatisfied as capability claims; this index only points at the research
artifact.
