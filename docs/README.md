# Mnemosyne — Documentation index

One-screen map of `docs/`. Lane discipline applies throughout: each document owns its lane, cites siblings by filename, and never redefines another lane's content. When documents conflict, dated specs and decision memos win over derived docs, and the as-built reference wins over plans.

## As-built reference (what the system is today)

| Document | Purpose |
| --- | --- |
| [ARCHITECTURE-OVERVIEW.md](ARCHITECTURE-OVERVIEW.md) | As-built system map generated from the source tree: components, schema, write/read data flows |
| [ENGINE-CONTRACT.md](ENGINE-CONTRACT.md) | Normative `MemoryEngine` storage contract; conformance defined by the shared-contract + parity suites |
| [SELF-HOSTED-PRODUCTION-ARCHITECTURE.md](SELF-HOSTED-PRODUCTION-ARCHITECTURE.md) | Self-hosted-first production architecture (two profiles, one codebase; no gate weakened) |
| [Mnemosyne-Privacy-and-Access-Control-Policy.md](Mnemosyne-Privacy-and-Access-Control-Policy.md) | Access-control policy statement |
| [ROADMAP-TO-100.md](ROADMAP-TO-100.md) | Blueprint-parity tracker; defines the additive / default-off / byte-identical-when-inactive wiring contract |

## Blueprint lane (`blueprint/`) — authoritative design

- [Mnemosyne-v2-Build-Blueprint.md](blueprint/Mnemosyne-v2-Build-Blueprint.md) / `.pdf` — the master blueprint (§1–§38): research → innovations → PRD → architecture → implementation → build plan.
- [Mnemosyne-Performance-and-Refactoring-Blueprint.md](blueprint/Mnemosyne-Performance-and-Refactoring-Blueprint.md) / `.pdf` — v1.1 performance & structural-refactoring program (Waves 0–E; parity-tagged work packages; extends the dated perf/native-accel specs).
- Policy lane deliverables: memory lifecycle, conflict resolution & merge, privacy-redaction-access, evaluation & test plan, rollback guidance, plus the observability / partial-deployment checklists.
- [cognitive-architecture/](blueprint/cognitive-architecture/) — the brain-grounded program (vision, honesty charter, G0 gate). [eval/](blueprint/eval/) — the binding eval contract pack. [earlier-versions/](blueprint/earlier-versions/) — superseded v1 documents.
- See [blueprint/README.md](blueprint/README.md) for that lane's own index.

## Active execution plans (docs root)

| Document | Owns |
| --- | --- |
| [EXECUTION-PLAN-A-Memory-System.md](EXECUTION-PLAN-A-Memory-System.md) / `.pdf` | Building the world-best **capabilities** (S1 multi-hop synthesis, S2 upgrades, S3 security/calibration, S4 perf/scale close-out, S5 activation-memory research) |
| [EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md](EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md) / `.pdf` | **Measurement and publication**: the `eval/public/` harness, the Public-Benchmark Publication Protocol (PBPP), third-party reproduction, and the neutral memory-benchmark leaderboard |

Division of authority: Plan A builds, Plan B proves and publishes — no external claim originates in Plan A, and where either says "measured/published," Plan B is the authority. Both extend the performance blueprint's Waves and the standing dated specs. The original combined plan is archived (below).

## Research (`research/`)

- [AI-Memory-Systems-Market-Research-2026.md](research/AI-Memory-Systems-Market-Research-2026.md) / `.pdf` — the competitive + benchmark landscape (systems, SWOTs, benchmark credibility problems). Ground-truth reference for Execution Plan B.

## Decisions

- [adr/](adr/) — architecture decision records (SQLite per-tenant isolation; B9 parametric-tier scope).
- [decisions/SECTION-17-OPEN-QUESTIONS.md](decisions/SECTION-17-OPEN-QUESTIONS.md) — the §17 decision memo (7/7 resolved; **binding** — new questions get new memos/ADRs; settled ones are not reopened).

## Working specs & phase plans (`superpowers/`)

- `superpowers/specs/` — dated design specs (`2026-07-01` native acceleration, `2026-07-05` performance program, …); each spawns implementation plans in `superpowers/plans/`. These are the source of truth for their programs; the blueprints extend, never duplicate, them.

## Archive (`_archive/`)

Superseded documents, retained verbatim with a supersession banner — e.g. `EXECUTION-PLAN-World-Best-Memory-and-Leaderboard.md` (the combined plan split into Plans A + B).

## Conventions

- **Blueprint-tier documents pair `.md` (editable source) + `.pdf` (rendered)**; policies, specs, ADRs, and roadmaps are `.md`-only. When a paired `.md` changes, re-render its `.pdf` in the same commit.
- Durable docs: `Mnemosyne-<Topic>-<Type>.md` (Title-Case-hyphenated) in `blueprint/`. Dated working specs: `superpowers/specs/YYYY-MM-DD-<topic>-design.md`. Checklists: lowercase-hyphenated.
- Statuses: **Proposed → Ratified → Superseded** (superseded docs move to `_archive/` or `blueprint/earlier-versions/` with a banner).
