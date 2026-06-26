# Cognitive Architecture — Design & Specification

**Location:** `docs/blueprint/cognitive-architecture/` · **Status:** Complete initial set · **Owner:** onfire7777 · **Updated:** 2026‑06‑25

The consolidated design + specification set for evolving Mnemosyne into a **recursive, self‑improving memory system with a functional sense of consciousness**. It **builds on — and does not contradict —** the **v2 Build Blueprint** (`../Mnemosyne-v2-Build-Blueprint.md`): same substrate (immutable evidence ledger + rebuildable projections, AGM belief‑revision core, branchable memory, bitemporal facts, fidelity‑tiered forgetting, conformal abstention, dual user model, capability‑secured writes, profile‑guided self‑optimization — the blueprint's innovations **I1–I12**). What it adds on top: the brain‑by‑brain research grounding, the **cognitive‑architecture** framing (a small always‑on workspace controller + on‑demand specialists), the operationalised "sense of consciousness," an objective decision record, and a reliability‑first **gated execution program**.

> Design docs live here under `docs/blueprint/`. The runnable **code** is at the repo root: `src/mnemosyne/`, `sql/`, `eval/`.

---

## North star

Take the best mechanisms of human memory and the latest memory science, make each **better than the brain** (keep the function, delete the failure mode), and unify them into a memory that is **self‑improving, self‑learning, self‑adapting, and self‑optimizing**, with **complete retention** and best‑achievable recall — plus a continuous, self‑modelling **workspace loop** that yields a *functional* sense of consciousness. Pursue the whole vision; ship it reliability‑first and metric‑gated; never overstate what is proven. Full statement: `00-VISION-AND-CHARTER.md`.

## Document map (reading order)

| # | File | Purpose |
|---|---|---|
| 00 | `00-VISION-AND-CHARTER.md` | The goal in full + the five self‑* properties + the anti‑yes‑man honesty charter |
| 01 | `01-PRIMER.md` | Plain‑English description of Mnemosyne **as it exists today** — the substrate we build on |
| 02 | `02-DESIGN-BRAIN-TO-ARCHITECTURE.md` | Core design: element‑by‑element brain↔system comparison, target cognitive architecture, anti‑goals, rationality layer, execution plan |
| 03 | `03-ADR-001-DECISION.md` | The architecture **decision** (Accepted): full vision, reliability‑first, metric‑gated (Option E) |
| 04 | `04-G0-BENCHMARK-SPEC.md` | The **G0** gate — freezes a baseline on the eval lane and adds a few program‑specific metrics; blocks every later stage |
| 05 | `05-GLOSSARY-AND-SOURCES.md` | Shared vocabulary + consolidated reputable bibliography |

New readers: 00 → 01 → 02 → 03 → 04. Implementers start at 03 (decision) then 04 (first buildable unit).

## Non‑negotiables (apply to every doc and every gate)

1. **Reliability is the invariant.** No change ships if it regresses faithfulness, calibration, or a §31 rail.
2. **Honesty charter (anti‑yes‑man).** Build and *measure* functional signatures; never claim verified *phenomenal* experience; every "better than the brain" claim must be a benchmark number. Full charter in `00`.
3. **The §31 invariant rails hold everywhere** — including for the system's own self‑generated thoughts.

## How this builds on existing work (no contradiction)

- **Design:** `../Mnemosyne-v2-Build-Blueprint.md` is the authoritative design. This set **extends** it (brain grounding + cognitive‑architecture layer + gated program); the substrate and innovations I1–I12 are shared, not replaced.
- **Evaluation:** `../Mnemosyne-Evaluation-and-Test-Plan.md` and the `../eval/` spec suite are the authoritative eval lane; **`04` reuses them** and adds only a few brain‑program‑specific metrics. They wire into the repo's real eval harness at the root — `eval/g0/` (already scaffolded), `eval/harness/`, `eval/calibration/`, `eval/run_eval.py`.
- **Code (repo root):** `src/mnemosyne/` (`engine.py`, `consolidation.py`, `belief.py`, `calibration.py`, `security.py`, `lifecycle.py`, `gate.py`…), `sql/schema.sql`, `eval/`.
- **Two restructurings (⟳):** `src/mnemosyne/providers/` → a typed **specialist‑module registry** (Layer 3); a new always‑on **workspace controller** (Layer 4) that acts only through the engine contract + rails. The substrate is never rewritten. Detail: `02` §1–§2.

## Related docs in this workspace

- `../Mnemosyne-v2-Build-Blueprint.md` (+ `.pdf`) — the authoritative v2 design (research → I1–I12 → PRD → architecture → implementation → build plan).
- `../Mnemosyne-Evaluation-and-Test-Plan.md` + `../eval/` — the evaluation lane that `04` builds on.
- `../Mnemosyne-Conflict-Resolution-and-Merge-Policy.md`, `../Mnemosyne-Memory-Lifecycle-Policy.md`, `../Mnemosyne-Privacy-Redaction-Access-Policy.md`, `../Mnemosyne-Rollback-Guidance.md` — policy lanes the anti‑goals (`02` §4) and rails must respect.
- `../earlier-versions/` — the v1 design (superseded by v2).

## Status & next step

Documentation & spec **complete**; pre‑build. The single blocking next deliverable is **G0** (`04`): freeze a baseline and gate. Note the repo already has an `eval/g0/` folder — extend it rather than starting fresh. Only when G0 is green does G1 begin. This folder is the canonical home for the cognitive‑architecture program.
