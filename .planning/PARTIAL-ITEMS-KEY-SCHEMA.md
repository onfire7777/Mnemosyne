# Mnemosyne — Partial-Item Memory Key Schema & Guardrail Contract (Lane A)

**Spec version:** 2.0 (2026-06-23) — supersedes 1.0 (`f470de7`); see Appendix R for the reconciliation log.
**Lane:** A (Memory schema) — owns key/title/field/link **definitions** + the guardrail/lock contract. One owner per lane; A never writes another lane's artifact.
**Type:** Canonical schema + guardrails. **Not** prose/body content (Lane B), **not** ops content (Lanes C–G).
**Source of truth:** this file. It is **published into the hub as two read-only mirror nodes** Lane B references by exact title: **`[[Memory Key Schema]]`** (Parts 1–5) and **`[[Memory Guardrails]]`** (Parts 6–10). Those titles are canonical and binding; the hub nodes mirror this file and add nothing.
**Governs:** the *definition* of Bridgememory partial-item entries. Entries are instantiated by **Lane B** under `Desktop/Bridgememory/.bridgememory/` and must conform to this contract.

**Authoritative file-imports (read-only; never recompute, never restate):**
- `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` — the 10 "Partial" rows (scope source).
- `.planning/OPS-HANDOFF-AND-OWNERSHIP.md` — lane registry + frozen gates (owner of the A/B/C–G split; read-only to A).

> These are **file imports of this spec**, not hub `[[wiki]]` edges. Hub edges (§5) resolve only to nodes that exist inside `.bridgememory/`. Do not confuse the two.

---

## 0. Lane boundary (explicit — read first)

Lane A owns, and ONLY owns:
- the **key** (slug) of each partial item (§1),
- the **title** / hub-node identity (the `[[Title]]` link target) (§2),
- the **logical field set** — which fields exist, their types/enums/defaults/immutability (§3),
- the **canonical registry** of the 10 partial items (§4),
- the **link-relationship contract** — which edges are required/forbidden (§5),
- the **guardrail/lock contract** — per-field write authority, status lifecycle, integrity invariants, conformance predicate, and amendment governance (§6–§10).

Lane A does **NOT** author:
- the entry **body/prose, the rendered front-matter values, naming, or the cross-link edges themselves** → **Lane B (entry templating; surface `*.md`)**. A defines the schema; B instantiates entries that conform.
- runbook / env-and-secrets / observability / rollback / validation content or operator evidence → **Lanes C–G (ops)**.
- **gate-command behavior** → frozen shared infra (A mirrors names read-only).
- `_layout.json` **canvas positions/topology rendering** → the hub app (§11).

---

## 1. Key (slug) convention

- Grammar: `^partial-[a-z0-9]+(-[a-z0-9]+)*$` — i.e. `partial-<area>[-<qualifier>…]`, lowercase kebab-case, **≤ 40 chars**.
- The slug **is** the memory key and the entry filename stem: `.bridgememory/<key>.md` (filename instantiated by Lane B).
- **Immutable after mint.** Never rename. A wrong slug is retired via `status: superseded` + a fresh key — never edited in place.
- **Unique across the hub.** One slug ⇄ one parity row, 1:1 (§8).

## 2. Title convention (= hub-node identity)

- Grammar: `^Partial: <Area Name>$`, Area in Title Case. The title **is** the entry H1 and therefore the canonical `[[Partial: <Area Name>]]` wiki-link target (the hub resolves links by title; see `welcome.md`).
- Title ⇄ key ⇄ parity_row are mutually 1:1 and **immutable after mint**.

## 3. Logical field set (representation-neutral — Lane A owns the *definition*; Lane B owns the rendering)

A conforming entry MUST carry these logical fields with these value rules. **Lane A does not mandate a serialization** (YAML front-matter vs. a Markdown bullet list vs. a definition list) — Lane B chooses the rendering in its template, but may not add, drop, or rename fields.

| field | type / allowed values | required | mutability | writer |
|---|---|---|---|---|
| `key` | slug per §1; == filename stem; primary key | yes | immutable post-mint | Lane A |
| `title` | per §2; == entry H1 / link target | yes | immutable post-mint | Lane A |
| `kind` | const `partial-item` | yes | immutable | Lane A |
| `parity_row` | integer `1..10`; maps to audit row | yes | immutable post-mint | Lane A |
| `blueprint_anchor` | `string[]`, e.g. `["§22","§28"]` or `["FR-21","§23"]` | yes | immutable post-mint | Lane A |
| `gate` | `string[]`; frozen mirror of the row's `release-audit` required command(s) | yes | frozen (mirror) | none — mirrors audit |
| `owner_lane` | non-empty subset of `{C,D,E,F,G}` (ops lanes only; never A or B) | yes | read-only mirror | coordinator (Lane G registry) |
| `status` | `partial \| evidence-pending \| validated \| done \| superseded`; default `partial` | yes | lifecycle per §7 | **Lane G only** |

Required **edges** (`[[Title]]` links) are part of the entry but governed separately in §5. The entry **body/prose** is out of Lane A scope (Lane B).

## 4. Canonical partial-item registry (the 10 items)

`key`, `title`, `parity_row`, `blueprint_anchor` are **minted from this table and immutable** thereafter. `gate` and `owner_lane` are **read-only mirrors** of `OPS-HANDOFF-AND-OWNERSHIP.md` (§3 gate table + ownership table).

| key | title | parity_row | blueprint_anchor | gate (frozen) | owner_lane |
|---|---|---|---|---|---|
| `partial-retrieval-postgres` | Partial: Production Postgres Retrieval | 1 | §22, §28 | `retrieval-ops-check` | C,D,E,G |
| `partial-auth-tenant` | Partial: Tenant Isolation & Auth | 2 | §27, §31 | `auth-ops-check` | C,D,E,F,G |
| `partial-mcp-runtime` | Partial: CLI/MCP Runtime Coverage | 3 | §18, §30 | `mcp-ops-check` | C,E,G |
| `partial-consolidation-roles` | Partial: Consolidation Role Pipeline | 4 | §21 | `consolidation-ops-check` | C,D,E,F,G |
| `partial-provenance-signed` | Partial: Signed Provenance | 5 | §27, §20 | `provenance-ops-check` | C,D,G |
| `partial-multimodal-retrieval` | Partial: Multimodal Retrieval | 6 | §20, §22 | `multimodal-ops-check` | C,D,E,G |
| `partial-privacy-erasure` | Partial: Privacy & Erasure | 7 | §25, §27 | `privacy-ops-check` | C,D,F,G |
| `partial-observability-dashboards` | Partial: Observability Dashboards | 8 | §32 | `ops-dashboard-check` | E,G |
| `partial-parametric-tier` | Partial: Parametric Tier | 9 | FR-21, §23 | `parametric-trainer-check` | C,D,F,G |
| `partial-live-parity-suite` | Partial: Live Parity Suite | 10 | §33 | `belief-revision-check` (+ full compose suite) | G |

## 5. Link-relationship contract (hub `[[Title]]` edges; hub-and-spoke, no mesh)

Edges are **title-based `[[wiki-links]]` placed in the entry by Lane B**; Lane A defines which are required, optional, and forbidden. Edges resolve only to nodes that exist inside `.bridgememory/`. `[[Target|Display]]` aliasing is permitted for display only and does not change the resolved target.

**REQUIRED up-links (every entry MUST carry exactly these governance edges):**
- `[[Memory Key Schema]]` — this contract, Parts 1–5.
- `[[Memory Guardrails]]` — this contract, Parts 6–10.

(These two are the nodes Lane B's category template already references. They make every partial item self-describing: an entry points at the schema and guardrails it conforms to.)

**OPTIONAL up-links:**
- `[[Strict Blueprint Parity Audit]]` — the scope-source node, **iff** a hub node with that exact title exists (it mirrors the audit file). When absent from the hub, the scope source is carried by the immutable `parity_row` field, not by an edge.
- `[[Blueprint §N]]` / `[[FR-N]]` — an anchor node for an entry's `blueprint_anchor` value, iff such a node exists. Canonical titles: `Blueprint §<N>` and `FR-<N>`.

**FORBIDDEN edges (guardrails — enforce the topology):**
- **No spoke→spoke.** Partial items never link each other. The graph is hub-and-spoke, not a mesh.
- **No down-edges into ops (Lanes C–G) artifacts.** Ops/observability/rollback nodes reference *up* to the partial item; the partial item never reaches *down* into them.
- **No edge that introduces an ownership claim on another lane's surface.** Category bucketing in Lane B's template is Lane B's organizational structure, expressed by where the entry lives — not by a Lane-A-mandated edge.
- The read-only `gate` / `owner_lane` fields carry the relationship to the ops registry; the entry needs **no** wiki-edge to the coordinator registry (avoids a dangling/duplicated edge).

## 6. Write-authority & lock contract (guardrail core)

### 6.1 Per-field write authority

| field(s) | writer | rule |
|---|---|---|
| `key`, `title`, `kind`, `parity_row`, `blueprint_anchor` | Lane A | write-once at mint, then **immutable / locked** (§8) |
| `gate` | none | frozen mirror of `PRODUCTION_RELEASE_REQUIRED_COMMANDS`; changes only if `OPS-HANDOFF-AND-OWNERSHIP.md` changes |
| `owner_lane` | coordinator (Lane G registry) | read-only in the entry; mirrors the registry |
| `status` | **Lane G only** | lifecycle per §7; bound to `release-audit` (§7); any backward move requires a logged Lane G reason |
| required link edges (§5) | Lane B (instantiation) | exactly the edges §5 requires/permits; B may add **no** new edge **types** |
| body/prose, rendered field values, naming | Lane B | conforms to §1–§5; B adds **no** fields and **no** new states |

### 6.2 Ownership lock (replaces a per-entry mutex)

Concurrency is governed by **one-owning-lane-per-artifact** (per `OPS-HANDOFF-AND-OWNERSHIP.md` §2), not a per-entry holder field:
- Each field is writable by exactly one lane (§6.1). A lane MUST NOT write a field it does not own; if it believes a field is wrong, it **escalates via the coordinator registry** rather than editing.
- **Stage only the specific file you own.** **Never `git add -A`** (concurrent multi-terminal / agent-on-main hazard).
- Immutable fields (§6.1 row 1, §8) are never writable post-mint by anyone — a wrong mint is retired (`status: superseded` + new key), never edited.

### 6.3 Status authority is the only gate this contract adds

`status` advances **only** as in §7, and the Partial→Done transition is bound to the **existing** acceptance gate (`release-audit --require-production-validated` for the row's `gate`). This contract introduces **no new judgment** — it points at the gate that already exists.

## 7. Status lifecycle (and reconciliation with the audit's binary)

Monotonic forward, Lane G only:

```
partial ──▶ evidence-pending ──▶ validated ──▶ done
   └────────────────── superseded (retired key; terminal)
```

- `evidence-pending` and `validated` are **Lane-A-defined sub-states of the audit's "Partial"** for tracking progress; they do **not** reclassify the row.
- A row may reach `validated`/`done` **only** when `release-audit --require-production-validated` passes for that row's `gate` with real-infra operator evidence (per the ops handoff's universal acceptance pattern). `done` ⇔ the audit's "Done".
- Reconciliation: `{partial, evidence-pending, validated}` ⊂ audit-"Partial"; `done` ⇔ audit-"Done". The authoritative Partial/Done flip remains the audit's; this lifecycle never re-derives the split (§10).
- `superseded` is terminal and only for a retired/mis-minted key.

## 8. Integrity invariants (the registry is valid iff all hold)

1. **Key grammar:** every key matches `^partial-[a-z0-9]+(-[a-z0-9]+)*$`, length ≤ 40.
2. **Title grammar:** every title matches `^Partial: .+$`.
3. **Bijections:** `key ↔ title ↔ parity_row` are mutually 1:1.
4. **Completeness:** `parity_row` values are exactly `{1,…,10}` — all ten present, no duplicates, no extras.
5. **Mirror consistency:** each row's `gate` and `owner_lane` equal the corresponding values in `OPS-HANDOFF-AND-OWNERSHIP.md` (read-only mirror); `owner_lane ⊆ {C,D,E,F,G}`.
6. **Uniqueness:** keys and titles are globally unique across the hub.
7. **Immutability:** §6.1-immutable fields are byte-stable across an entry's life (until `superseded`).

## 9. Conformance predicate (machine-checkable)

A **partial-item entry conforms** iff:
1. it carries every required logical field (§3) with a type/enum-valid value;
2. its `key`, `title`, `parity_row`, `blueprint_anchor` equal the §4 registry row for its `parity_row`;
3. `status` ∈ the §7 enum, and any advance to `validated`/`done` is backed by passing `release-audit` evidence for the row's `gate`;
4. it carries the §5 **required** edges, only §5-**optional** edges beyond them, and **no forbidden** edge;
5. it introduces **no** field, edge type, or status outside this contract.

The **registry conforms** iff §8 holds. The ops "validate conformance to key schemas" check (`partial-deployment-validation-checklist.md`) verifies conformance against this predicate; it does not redefine it.

## 10. Versioning & amendment governance

- This spec is versioned (`spec_version`, header). It is amended **only by Lane A**.
- The §4 registry (`key`/`title`/`parity_row`/`blueprint_anchor`) changes **only if** `STRICT-BLUEPRINT-PARITY-AUDIT.md` changes; `gate`/`owner_lane` change **only if** `OPS-HANDOFF-AND-OWNERSHIP.md` changes. A is a mirror, never an originator, of those.
- **Do-not-rederive (binding):** entries and this spec import `parity_row`, `gate`, and the settled scope split; they **must not** restate scores, recompute the split, re-audit, or add new `*-ops-check` gates. The schema carries pointers, not re-derivations.
- No lane (A or B) may add fields, edge types, or status values; such a change is a spec amendment by A, ratified against the imports above.

## 11. Boundaries with other lanes (explicit, non-overlapping)

- **vs Lane B (entry templating):** A defines *which* fields/edges/states exist and their rules; **B instantiates** entries — renders the fields in B's chosen Markdown shape, writes bodies, and places the `[[wiki]]` edges — conforming to A. A writes no prose and no entry files; B adds no fields, no new edge types, no new states. (Resolves the registry's A↔B seam: field-set *definition* = A; *rendering* = B.)
- **vs Lanes C–G (ops):** A defines schema only. Runbook / env-and-secrets / observability / rollback / validation content and operator evidence live in C–G; the entry carries only the read-only `gate` mirror + `owner_lane` pointer, never ops content.
- **vs gate binaries:** frozen shared infra; A mirrors gate names read-only and never defines or edits gate behavior.
- **vs the hub app (`_layout.json`):** A owns hub **structure as schema** — node identity (titles), required/forbidden edges, and the `index.json` shape contract. A does **not** own `_layout.json` **canvas positions or topology rendering** (x/y and the visual graph), which are app-managed and out of scope.

---

## Appendix R — Reconciliation log (v1.0 `f470de7` → v2.0)

Every divergence from the committed v1.0, with rationale and source evidence. Revert any item if Lane A's owner disagrees.

| # | v1.0 | v2.0 | Why |
|---|---|---|---|
| R1 | Mandated a YAML **front-matter** field set + `lock:` object on entries. | **Representation-neutral** logical field set (§3); rendering is Lane B's. | Real hub entries use no front-matter (H1 + body + `## Related`); `OPS-HANDOFF` assigns per-entry front-matter/rendering to **Lane B**. Mandating YAML intruded on B's surface. |
| R2 | Links via a front-matter `links:` array. | Edges are **title-based `[[wiki-links]]` in the body** (§5), placed by Lane B. | The hub resolves `[[Title]]` links (`welcome.md`; the real entry's `## Related`). |
| R3 | Required up-link `[[Ops Handoff & Ownership Registry]]`. | **Dropped as an edge**; relationship carried by the read-only `gate`/`owner_lane` fields + a spec file-import. | That title does not match the ops file's H1 and `.planning/*.md` are not hub nodes, so the edge **dangled**. |
| R4 | No declared Lane A hub nodes. | Declares canonical hub titles **`[[Memory Key Schema]]`** + **`[[Memory Guardrails]]`** and makes them the **required** entry edges (§5). | Lane B's category template references those two titles; without them the references dangle. |
| R5 | Per-entry `lock:{holder,acquired_at}` mutex + acquire/release protocol. | Folded into **one-owner-per-lane** + stage-only-owned-file (§6.2). | A per-entry mutex is redundant with the registry's one-terminal-per-lane model and put Lane-A state into B's front-matter. The real hazard the v1 named (`git add -A`) is kept as an explicit rule. |
| R6 | Status lifecycle stated; relation to audit Partial/Done implicit. | Explicit lifecycle + **audit reconciliation** (§7): sub-states ⊂ "Partial". | Prevents the lifecycle from looking like a re-derivation of the settled split. |
| R7 | No integrity invariants, conformance predicate, or versioning. | Added §8 invariants, §9 machine-checkable predicate, §10 versioning/governance. | "No-compromise complete": makes the contract auditable and the ops conformance check well-defined. |
| R8 | `_layout.json` "positions/topology" out of scope (one line). | Split (§11): A owns structure-as-schema (titles, edges, `index.json` shape); app owns positions + topology rendering. | Reconciles with `OPS-HANDOFF` listing `{_layout.json,index.json}` as Lane A's surface while positions stay app-managed. |

**Preserved unchanged from v1.0:** key/title grammar; the 10-row registry (keys, titles, parity rows, anchors, gates, owner lanes — all cross-checked 1:1 against both imports); hub-and-spoke/no-mesh topology; `status` = Lane G only, bound to `release-audit`; the do-not-rederive guardrail; the lane-boundary posture.
