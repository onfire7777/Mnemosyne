# Mnemosyne — Partial-Item Memory Key Schema & Lock Contract (Lane A)

**Date:** 2026-06-23
**Lane:** A (Memory schema) — owns key/title/field/link definitions + the lock contract.
**Type:** Canonical key schema + guardrails. **Not** prose content, **not** ops content.
**Governs:** Bridgememory partial-item entries (`Desktop/Bridgememory/.bridgememory/<key>.md`). This file is the version-controlled source of truth; instantiating entries into the hub follows this schema.
**Imports (never recompute):** `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (10 Partial rows), `.planning/OPS-HANDOFF-AND-OWNERSHIP.md` (lanes + gates). See `[[Ops Handoff & Ownership Registry]]`.

---

## 0. Lane boundary (explicit — read first)

Lane A owns, and ONLY owns:
- the **key** (slug) of each partial item,
- the **title** (the `[[link]]` target),
- the **field set** (frontmatter keys + allowed values),
- the **link relationships** (which edges are required/forbidden),
- the **lock contract** (write authority + mutation protocol).

Lane A does **not** write:
- prose/body sections of an entry → **Lane B (entry templating)**,
- runbook/env/observability/rollback/validation content or operator evidence → **Lanes C–G (ops)**,
- gate-command behavior → frozen shared infra (mirrored read-only).

---

## 1. Key (slug) convention

- Form: `partial-<area>[-<qualifier>]`, lowercase kebab-case, ≤ 40 chars.
- The slug **is** the memory key and the filename: `.bridgememory/<key>.md`.
- **Immutable after mint** (never rename; a wrong slug is deprecated via `status: superseded`, never edited).
- Unique across the hub. One slug ⇄ one parity row (1:1).

## 2. Title convention

- Form: `Partial: <Area Name>` (Title Case). The title is the canonical `[[Partial: …]]` link target.
- Title ⇄ key is 1:1 and **immutable after mint**.

## 3. Field set (frontmatter schema — Lane A owns these keys)

```yaml
key:               # string, == slug, primary key, immutable
title:             # string, == "Partial: <Area>", immutable
kind:              # const: partial-item
parity_row:        # int 1..10, immutable (maps to audit row)
blueprint_anchor:  # string[], e.g. ["§22","§28"] or ["FR-21","§23"], immutable
gate:              # string[], frozen mirror of the row's release-audit command(s); read-only
owner_lane:        # enum A..G, set by coordinator registry; read-only here
status:            # enum: partial | evidence-pending | validated | done | superseded ; default partial
links:             # string[] of [[Title]] — required edges per §5
lock:              # object — see §6
```

Bodies below the frontmatter are **out of Lane A scope** (Lane B).

## 4. Canonical partial-item key registry (the 10 items)

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

`key`, `title`, `parity_row`, `blueprint_anchor` are minted from this table and immutable thereafter. `gate`/`owner_lane` mirror `OPS-HANDOFF-AND-OWNERSHIP.md` read-only.

## 5. Link relationship rules (hub-and-spoke; no mesh)

Each partial-item entry MUST link (and only these):
- `[[Ops Handoff & Ownership Registry]]` — every spoke links up to the hub.
- `[[Strict Blueprint Parity Audit]]` — the source of the row.

Each partial-item entry MAY link:
- `[[Blueprint §N]]` / `[[FR-N]]` anchor node, if such a node exists.

Forbidden edges (guardrails):
- **No spoke→spoke** edges (partial items do not link to each other) — keeps the graph hub-and-spoke, not a fully-connected mesh.
- **No outbound edges into Lane B template nodes or Lane C–G ops artifacts.** Ops/templating nodes reference *up* to the partial item; the partial item never reaches *down* into them. This prevents ownership bleed across lanes.

## 6. Lock contract (write authority + mutation protocol)

### 6.1 Per-field write authority

| field | writer | rule |
|---|---|---|
| `key`, `title`, `kind`, `parity_row`, `blueprint_anchor` | Lane A | write-once at mint, then **immutable / locked** |
| `gate` | none | frozen mirror of `PRODUCTION_RELEASE_REQUIRED_COMMANDS`; changes only if the audit source changes |
| `owner_lane` | coordinator (registry) | read-only in the entry |
| `status` | **Lane G only** | monotonic forward: `partial → evidence-pending → validated → done`; `superseded` for retired keys; any backward move requires a logged Lane G reason |
| `links` | Lane A | required edges per §5; no other lane adds edges |
| body/prose | Lane B | Lane A never writes it |

### 6.2 `lock` frontmatter object

```yaml
lock:
  owner: A                 # schema owner of structural fields
  status_authority: G      # only Lane G may advance status
  holder: null             # terminal id currently editing a mutable field, else null
  acquired_at: null        # iso8601 when holder acquired, else null
```

### 6.3 Mutation protocol (concurrency guardrail)

- **Immutable fields** (§6.1 row 1) are never writable post-mint — they ignore the lock.
- To write any **mutable** field: set `lock.holder = <your-terminal-id>` + `acquired_at`, write the **owned field only**, then clear `holder`/`acquired_at`. If `holder` is non-null and not yours, **do not write** — escalate via the registry for reassignment.
- Stage only the single `<key>.md` file. **Never `git add -A`** (concurrent multi-terminal / Codex-on-main hazard).
- `status` may advance to `validated`/`done` **only** when `release-audit --require-production-validated` passes for that row's `gate`. The lock contract binds the Partial→Done transition to the existing acceptance gate — it does not introduce a new judgment.

### 6.4 Do-not-rederive guardrail (binding)

An entry imports `parity_row`, `gate`, and the settled 70/30 framing; it **must not** restate scores, recompute the split, or re-audit. The schema carries pointers, not re-derivations.

---

## 7. Boundaries with other lanes (explicit, non-overlapping)

- **vs Lane B (entry templating):** A defines *which* fields/links exist and their lock rules; B defines how the markdown body *renders* them. A writes no prose; B adds no fields and no links.
- **vs Lanes C–G (ops):** A defines the key/lock schema only. Runbook/env/observability/rollback/validation content and operator evidence live in C–G; the entry carries only the read-only `gate` mirror + `owner_lane` pointer, never ops content.
- **vs gate binaries:** frozen shared infra; A mirrors gate names read-only and never defines or edits gate behavior.
- **vs the Bridgememory live canvas (`_layout.json`):** A owns the entry **schema**, not canvas positions/topology; positions are managed by the hub app and are out of this spec's scope.
