# Mnemosyne — project folder

A self-optimizing memory architecture for AI agents: complete recall + precise retrieval, safe self-improvement, and personalization. An eclectic synthesis of proven memory research (cognitive science, retrieval/RAG, self-improving agents, ~20 real systems), pushed conceptually but grounded in existing, citable work.

## What's here

**Final deliverable (start here):**

- **`Mnemosyne-v2-Build-Blueprint.pdf`** — the polished 38-page document: research → conceptual innovations → product spec (PRD) → architecture → implementation (schemas, code, deployment, tests) → build plan. Read this to read; build from the source below.
- **`Mnemosyne-v2-Build-Blueprint.md`** — the same document as editable Markdown source.

**Earlier work (archived in `earlier-versions/`):**

- `Mnemosyne-Recursive-Memory-System-Design.md` — the v1 design document (superseded by v2; v2 reframes the system as a "self-optimizing compiler for experience," adds the belief-revision core, branchable memory, fidelity-tiered forgetting, confidence/abstention, and a full implementation + build plan).
- `Mnemosyne-Architecture-Blueprint.html` — the v1 interactive architecture explorer (open in a browser). Visual companion only; the v2 document is authoritative.

**Forward program (extends v2):**

- **`Mnemosyne-Performance-and-Refactoring-Blueprint.md`** / **`.pdf`** — the performance and structural-refactoring program layered on top of v2. It preserves strict byte-parity and local-first defaults while planning native-default execution, graph/retrieval depth, provider/runtime, benchmark, and refactoring waves.
- **`cognitive-architecture/`** — the brain‑grounded cognitive‑architecture program: vision & honesty charter, the element‑by‑element brain↔system design, the accepted decision (ADR‑001), the **G0** benchmark gate, and a glossary. Builds on this blueprint (innovations I1–I12) and the `eval/` lane; start at `cognitive-architecture/README.md`.

## The one-paragraph summary

MemPalace remembers (lossless verbatim), GBrain organizes (compiled current truth + hybrid retrieval). Mnemosyne keeps both — an immutable, content-addressed evidence ledger plus rebuildable typed projections — and adds what neither has: a truth-maintenance + AGM belief-revision core (clean updates, no silent corruption), git-like branchable memory (reversible by construction), bitemporal "as-of-time" queries, fidelity-tiered forgetting, calibrated confidence with abstention, a dual user model that adapts to you, and a profile-guided loop that improves its own policies — all under a structurally-enforced safety invariant.

## Maturity (honest)

Phases 0–3 (lossless memory, precise retrieval, personalization) are buildable engineering. Phases 4–5 (validated lessons/skills, and the self-optimizing loop) are applied/research-track and are designed to run shadow-first behind hard safety rails. See §38 of the build blueprint.

*Codename "Mnemosyne" is a placeholder — rename freely.*
