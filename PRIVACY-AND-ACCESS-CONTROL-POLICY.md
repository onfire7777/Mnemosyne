# Mnemosyne — Privacy & Access Control Policy

> **Lane scope.** This document defines **how sensitive a memory is, who may read it, and when it must be redacted before disclosure.** It assigns meaning to the existing `sensitivity` and `access_policy` columns and the `privacy.py` primitives, specifies the normative `access_policy` object, and states — honestly and with file:line evidence (§11) — which rules the code enforces today versus which are policy targets. It is a classification-and-disclosure governance policy, not a security-architecture spec.
>
> **What this lane does _not_ own (read those first):**
> - **Security & governance** (Build Blueprint **§27**, `src/mnemosyne/security.py`) — trust tiers, capability-mediated writes, write authorization (`authorize_write`), the quarantine LLM, data-never-instruction sanitization, signed provenance, and **secret/credential detection and handling**. This lane *consumes* `trust_tier` and `capability_tags` as inputs; it does not define how writes are gated or how secrets are detected.
> - **Forgetting & lifecycle** (Build Blueprint **§25**, `ErasureMode` in `src/mnemosyne/privacy.py`) — transitive crypto-shred erasure and fidelity demotion. Redaction here is a non-destructive *view transform*; **erasure is not redaction** (§5.3).
> - **Retrieval engine** (Build Blueprint **§22**) — channels, ranking, and assembly. This lane defines the access predicate applied at **§22.3 (filter, security-before-ranking)** and the masking applied at **§22.6 (assembly)**; it does not redefine the pipeline.
> - **Data model / DDL** (Build Blueprint **§29**, `sql/schema.sql`) — column definitions. This lane gives *semantics* to `sensitivity`, `access_policy`, `pii_tags`, and `residency`; it adds no columns.
> - **User model** (Build Blueprint **§24**) — the six preference categories. Preference rows are classified through their existing `scope`/`access_policy`; this lane adds no parallel model.
>
> If a sentence here starts to read like a write-gating rule, a secret-detection routine, an erasure procedure, or a schema change, it belongs in one of those lanes, not this one.

---

## 0. The one thing to internalize first

**Trust and sensitivity are orthogonal axes. Never collapse them.**

- **Trust tier** (`trust_tier`, 0–5, lower is better; §27) answers *inbound*: *may this content influence behavior?* It exists to stop poisoning. A direct-user note is tier `0`; untrusted external content is tier `5`.
- **Sensitivity** (`sensitivity`, this lane) answers *outbound*: *to whom may this content be disclosed?* It exists to stop leakage.

A password the user typed is **fully trusted** (tier `0`) **and** maximally sensitive (`S4`). A scraped marketing page is **untrusted** (tier `5`) **and** non-sensitive (`S0`). Each axis is gated by a different lane. This document owns only the second, and at retrieval the two axes are enforced **together** by a single filter (§4, §11).

## 1. The two axes

| | Trust tier (§27 — *not this lane*) | Sensitivity (this lane) |
|---|---|---|
| Question | May it influence behavior / writes? | To whom may it be disclosed? |
| Fields | `trust_tier`, `capability_tags` | `sensitivity`, `access_policy`, `pii_tags`, `residency` |
| Scale | 0 = direct user … 5 = untrusted external | S0 = public … S4 = secret-referenced |
| Failure prevented | Memory poisoning / prompt injection | Disclosure to an unauthorized principal |
| Enforced at | Write gate; retrieval trust ceiling | Retrieval sensitivity ceiling (§22.3); assembly mask (§22.6); export |

The enforcement mechanism today is a **ceiling**: every read carries a `max_trust_tier` and a `max_sensitivity`, and a candidate is dropped if `trust_tier > max_trust` **or** `sensitivity > max_sensitivity` (`engine.py:1177`; SQL `AND e.trust_tier <= %s AND e.sensitivity <= %s`, `postgres_engine.py:691,740`). This policy's job is to specify **what those ceilings must be set to, per principal**, and what `access_policy` carries beyond the ceiling.

## 2. Privacy classification levels

These levels are the defined meaning of the `sensitivity SMALLINT` column (default `0`). They do not change the column; they say what each value means.

### 2.1 The levels

- **S0 — Public.** Non-personal, freely shareable (public facts, documentation, the agent's own non-sensitive procedures). The schema default.
- **S1 — Internal.** Ordinary personal/operational content with no special-category data (general chat, task context, non-sensitive preferences). The working default for user-authored content.
- **S2 — Confidential / personal.** Personal data and contact identifiers — anything carrying a `pii_tags` entry. Today `data_class` is set to `"pii"` whenever `sensitivity` is non-zero (`ingestion.py:156`).
- **S3 — Restricted / regulated.** Special-category or regulated data: precise health, financial-account detail, government identifiers, biometrics, anything residency-controlled.
- **S4 — Secret-referenced.** Content that **is or quotes a live secret/credential** (keys, tokens, passwords). Detection and credential-grade handling live in **§27 / `security.py`** — this lane fixes only the *disposition*: S4 content is pointer-only at rest, never materialized into a projection in plaintext, and never reaches the system prompt (§4.4).

### 2.2 PII taxonomy & the detector-coverage gap (stated honestly)

The intended mapping from data category to minimum level:

| Category | Examples | Min level |
|---|---|---|
| Contact identifiers | email, phone, handles, postal address | S2 |
| Direct identifiers | full name + DOB, government ID, SSN/NI | S3 |
| Financial | account/card numbers, balances | S3 |
| Health | diagnoses, medications, precise conditions | S3 |
| Biometric / geolocation | face/voice prints, precise GPS history | S3 |
| Credentials / secrets | passwords, API keys, tokens, private keys | S4 |

**Known limitation.** The shipped detector, `classify_privacy` (`privacy.py:16–43`), only recognizes **email and phone** by regex. Every other category above currently reaches its level **only if the caller passes `--sensitivity` explicitly** or an upstream classifier sets it. Until detector coverage expands (§12), operators handling regulated data MUST set ingest-time `--sensitivity` floors by source, and MUST NOT assume automatic S3/S4 escalation. This gap is a disclosure risk, not a cosmetic one.

### 2.3 Assignment, effective sensitivity & monotonic escalation

- **Assigned at ingest.** Effective sensitivity is `max(caller-supplied, detector-derived)` — already implemented: `sensitivity = max(request.sensitivity, int(classification["sensitivity"]))` (`ingestion.py:152`).
- **Effective sensitivity = `max`(stored, detector/`pii_tags` floor).** A row left at S0 that carries a `pii_tags` entry is treated as **≥ S2** by every disclosure check. An un-escalated classification thus **fails safe**, not open.
- **Derived memory inherits the max.** Consolidated items take the **highest** sensitivity among their evidence — implemented: `max(int(item.sensitivity) …)` (`consolidation.py:727`, `_max_evidence_sensitivity` `:1505`, candidate path `:1447`). Consolidation can escalate; it can never silently declassify.
- **Declassification is explicit and authored.** Lowering a row's `sensitivity` requires an operator/owner action recorded in the audit log; the self-optimizer cannot touch it (§31 rails; §11).

## 3. The `access_policy` object (normative shape)

`access_policy` (JSONB, present on evidence, assertions, relations, preferences, entities) is the per-row carrier of disclosure rules. **Today it is populated minimally** — `{"tenant": tenant_id}` (`engine.py:780`, `belief.py:167`, and throughout). This section defines the **normative target shape** the writers should converge on; unknown/absent keys fall back to the role-ceiling defaults (§4.2) and fail-closed (§11).

```jsonc
{
  "tenant": "tenant-a",            // REQUIRED — hard isolation key (§4.1); never relaxable
  "owner": "user-a",               // data subject; basis for owner-full-access (§4.3)
  "min_role": "agent",             // lowest role permitted to read at all
  "max_sensitivity": 2,            // ceiling this row may be disclosed under, per principal class
  "mask_fields": ["email","phone"],// pii_tags spans to field-mask when masking (§5.2)
  "system_prompt_eligible": false, // false ⇒ never injected as instruction (S3+/untrusted force false)
  "export_eligible": true,         // may leave the system via `export` (subject to redaction-on-export)
  "residency": "local",            // pin; cross-region disclosure is a redaction/deny trigger (§8)
  "break_glass": false             // if true, exceptional access is permitted under §9 dual-control + audit
}
```

Rules for the object:
- `tenant` is mandatory and authoritative; no other key can widen disclosure across the tenant boundary.
- Missing key ⇒ the **more restrictive** of (role-ceiling default §4.2, this policy's level rule §2). Never the more permissive.
- On **derived** items, `access_policy` MUST be the **most-restrictive merge** of the contributing evidence, mirroring the `max` sensitivity rule. Today the code takes the **first** evidence's policy instead (`_first_access_policy`, `consolidation.py:1511`) — a known asymmetry tracked in §12.

## 4. Data access rules (boundaries)

Access is decided **before ranking** at §22.3 and recorded per row in `access_policy`. The decision is `allow | mask | deny`.

### 4.1 Hard isolation (absolute, never crossed)

Tenant and per-user/source isolation are prior to everything below and apply at **every** sensitivity level. No classification, role, mask setting, or break-glass ever permits a cross-tenant read. This is owned by §27 / Postgres RLS / signed-session tenant binding and verified by `auth-ops-check`; this lane neither relaxes nor restates it.

### 4.2 Role → sensitivity-ceiling binding

The roles are the real session roles `reader | agent | consolidator | operator` (`security.py:62`). The code uses them today to gate **writes** (`authorize_write`, `consolidator_only_ops` `:877`); this policy binds each role to a **read ceiling** (`max_sensitivity`) that the caller's filter MUST be set to. Wiring these as the per-role default ceiling is a §12 hardening item; until then the ceiling is supplied per request (`--max-sensitivity`, `cli.py:11341`).

| Role | Read ceiling (`max_sensitivity`) | Notes |
|---|---|---|
| `reader` | S1 | Untrusted/low-privilege surface; never sees PII without explicit grant. |
| `agent` (user-facing, in-session) | S2 (S3 masked) | Acts for the owner; S3 gist/pointer only; S4 pointer only. |
| `consolidator` | S4 | Needs all evidence to compile; outputs inherit max sensitivity; under capability mediation. |
| `operator` | metadata only | Infra/audit; never raw S2+ payloads — fingerprints/tags only. |

### 4.3 The need-to-know matrix (effective level × principal)

| Effective level | Owner (subject) | `agent` in-session | `consolidator` | `operator` | External / cross-user |
|---|---|---|---|---|---|
| S0 Public | allow | allow | allow | allow | allow (if explicitly public) |
| S1 Internal | allow | allow | allow | metadata only | deny |
| S2 Confidential | allow | allow, **field-masked** PII unless task-justified | allow (outputs inherit S2) | metadata only | deny |
| S3 Restricted | allow | **gist/pointer only**, owner-confirmed for plaintext | allow under capability mediation | redacted evidence only | deny |
| S4 Secret-referenced | pointer only | **never plaintext**; pointer only | pointer only | never raw; fingerprint only | deny |

"metadata only" / "fingerprint only" reflects the repository's standing rule that audit and ops surfaces never echo raw sensitive payloads (the redaction flags asserted by `privacy-ops-check`, `auth-ops-check`, and the ops bundles).

### 4.4 The system-prompt boundary

- **S3 and S4 content never enters the system prompt** (`system_prompt_eligible` forced `false`). It may appear in the answer body to an authorized principal, but never as instruction.
- **Untrusted-derived memory never enters the system prompt at any sensitivity** — the §31 invariant rail `untrusted_to_system_prompt: forbidden` and the MemoryTrap fix (§27). Stated here only because it bounds disclosure; the rail itself is owned by §27/§31.

### 4.5 Capability tags as read constraints

`capability_tags` (`quarantined`, `data-only`, `no-write-authority`, `provenance-untrusted`; set at `ingestion.py:137–150`) are primarily an inbound/write concept (§27). For disclosure, only their **read** consequence is in scope: a `quarantined` tag (or `quarantine_reason` metadata) excludes the row from default retrieval unless `include_quarantined=true` is explicitly requested by an authorized principal (`engine.py:1169–1179`). This lane adds no new tags.

## 5. Redaction rules & triggers

Redaction is the `mask` outcome of §4: the row is *retrieved* but *transformed* before it reaches the principal.

### 5.1 Triggers

Redact when **any** holds:

1. Effective sensitivity exceeds the principal's ceiling (§4.2/§4.3) → mask down to the highest level the principal may see.
2. The destination is an **export** to a lower-trust target, or a **cross-residency** transfer that `enforce_residency` / `enforce_residency_transfer` denies (§8).
3. The content is bound for the **system prompt** and is S3+ or untrusted-derived (§4.4).
4. The sink is an **audit / `explain` / ops** surface — raw S2+ payloads are never logged; emit tags, counts, and fingerprints.

### 5.2 The redaction ladder (a view transform, never a ledger edit)

Applied at §22.6 assembly and at export, strongest-allowed first:

```
full text → field-mask (drop pii_tags / mask_fields spans) → gist only → pointer only (verbatim drawer withheld) → withhold + abstain
```

Evidence is sacred (principle 1): redaction **never mutates the ledger**. It transforms the *view* produced for one principal on one read. The same row may be returned full to its owner and pointer-only to an agent in the same session. **Status today:** the retrieval path enforces the *ceiling* (drop-above-level) but does **not** yet implement field-masking or gist substitution — above-ceiling rows are dropped, not masked (§11, §12). Until masking ships, "mask" degrades safely to "deny," which is conservative but lossy.

### 5.3 Redaction vs. fidelity demotion vs. erasure (three different things)

- **Redaction (this lane)** — disclosure-driven, reversible, per-principal, per-read. A verbatim-fidelity row can still be redaction-masked.
- **Fidelity demotion (§25)** — *utility*-driven storage compaction (verbatim → gist → trace). Orthogonal to who may read.
- **Erasure (§25, `ErasureMode`: `tombstone_recompute` | `hard_delete_legal`, `privacy.py:11–13`)** — destructive crypto-shred + transitive recompute along provenance. **Erasure is not a redaction outcome.** "Stop showing me X" is redaction/scope; a right-to-be-forgotten request is §25 erasure. Do not conflate them.

## 6. Data lifecycle & state transitions

Sensitivity and access travel with the memory across its whole life:

- **Belief revision / contest (§I2).** A superseded or contested fact **retains** its sensitivity; it does not declassify by losing currency. A contested S3 belief surfaces (to authorized principals) as alternatives, each at S3.
- **Branches (§I3).** Branch isolation is orthogonal to disclosure: a branch never lowers a row's ceiling. Cross-branch reads obey the same matrix as cross-anything reads.
- **Bitemporal / as-of (§I5).** "As-of-T" queries return the classification that was in force **as of T**; a later declassification does not retroactively expose a snapshot, and a later escalation does apply to historical reads (escalate-only, §2.3).
- **Consolidation (§21).** Derived items inherit `max` sensitivity (implemented, §2.3) and MUST inherit the most-restrictive `access_policy` merge (target; today first-evidence, §3/§12).
- **Prefetch (§I10, `prefetch.py`).** Anticipatory warming MUST apply the requesting context's ceiling **before** materializing anything into a cache. **Status today:** `prefetch.py` performs **no** sensitivity/trust filtering (grep-confirmed) — a real gap (§12); until fixed, prefetch must run with the most restrictive ceiling of any consumer it warms for.
- **Export & subject rights (`export`, §22 API).** Export is a disclosure event: apply §5 redaction-on-export and honor `export_eligible`. Subject-access/portability requests return the owner's own data at full fidelity within the tenant; they never cross isolation.
- **Retention.** Situational/temporary preferences and `valid_to`/`expired_at` bound how long a sensitive row stays live; expiry reduces exposure surface but is **not** erasure (§5.3).

## 7. Derived artifacts: embeddings, indexes, projections, multimodal

- **Embeddings and indexes inherit the sensitivity of their source.** Vector and lexical search are access-filtered by the same ceiling as content (`postgres_engine.py:691,740`), so an S3 row cannot be surfaced to an S2 principal via its embedding. Any new index MUST carry the source `sensitivity`/`access_policy` or it is treated as S4 by default.
- **Projections are recomputable views** (principle 1); they carry, never lower, the classification of the evidence they derive from.
- **Multimodal.** Raw media objects live in the (optionally encrypted) object store; their **derived text and media embeddings** inherit the object's sensitivity. Disclosing a derived caption is bounded by the source object's level, not the caption's apparent innocuousness.

## 8. Residency

- **Pin at ingest.** `residency` is normalized and enforced at ingest against the runtime allow-list (`enforce_residency`, `ingestion.py:107`); disallowed residency fails closed.
- **Cross-region transfer is deny-by-default.** A move to a different region is permitted only by an explicit `source->target` rule (`enforce_residency_transfer`, `ingestion.py:114`); otherwise it raises. Cross-region disclosure is therefore a redaction/deny trigger (§5.1.2).
- **Interaction with sensitivity.** S3 regulated data SHOULD be residency-pinned. Residency is an independent gate: clearing the sensitivity matrix does **not** authorize a residency-violating transfer, and vice-versa. Verified by `privacy-ops-check --require-case residency-deny`.

## 9. Exceptional access (break-glass)

Operator access to S2+ plaintext is permitted only as an explicit, bounded exception:

- Requires `access_policy.break_glass = true` **and** an operator session whose grant is recorded.
- **Dual-control**: a break-glass read is logged with actor, justification, rows touched (by fingerprint), and time; it is reported by the relevant ops bundle and is reviewable.
- It **never** crosses tenant/user isolation (§4.1) and **never** silently declassifies the row.
- Absent an explicit break-glass grant, operators get metadata/fingerprints only (§4.3).

## 10. Threat → control map

| Disclosure threat | Primary control (this lane) | Backstop / owner lane |
|---|---|---|
| Cross-tenant / cross-user leak | — | Hard isolation, RLS, signed-session (§4.1, §27, `auth-ops-check`) |
| Over-disclosure to a low-privilege reader | Role ceiling + matrix (§4.2/§4.3) | Retrieval filter `engine.py:1177` / SQL ceiling |
| Exfiltration via the system prompt | `system_prompt_eligible=false` for S3+/untrusted (§4.4) | §31 rail `untrusted_to_system_prompt` |
| Leak through embeddings/indexes | Index inherits source level; vector results filtered (§7) | `postgres_engine.py:691,740` |
| Quarantined/poisoned content surfacing | Default-exclude quarantined (§4.5) | §27 quarantine, capability tags |
| Over-share on export | Redaction-on-export + `export_eligible` (§5.1.2, §6) | — |
| Cross-border data movement | Residency deny-by-default (§8) | `privacy-ops-check` |
| Raw secrets in logs/audit | Metadata/fingerprint-only sinks (§4.3, §5.1.4) | Repo redaction flags, ops bundles |
| Silent declassification | Escalate-only + authored declassification (§2.3) | Audit log, §31 rails |

## 11. Enforcement state & conformance

This is the honesty section: **policy target ≠ current enforcement.** Conformance is auditable against these facts.

**Enforced in code today (verified):**
- Tenant isolation / RLS and signed-session binding — §27; `auth-ops-check`.
- Sensitivity **ceiling** drop at retrieval — `engine.py:1177`; `postgres_engine.py:691` (evidence), `:740` (assertions).
- Trust ceiling + quarantine exclusion — `engine.py:1169–1179`.
- Ingest effective-sensitivity `max` escalation — `ingestion.py:152`.
- Consolidation `max` sensitivity inheritance — `consolidation.py:727`, `:1447`, `:1505`.
- Residency enforce + deny-by-default transfer at ingest — `ingestion.py:107,114`.
- Erasure modes (`tombstone_recompute`, `hard_delete_legal`) — `privacy.py:11–13`; `privacy-ops-check`.
- Per-request and default ceilings — `--max-sensitivity` (`cli.py:11341`), `policy.max_sensitivity`.

**Policy target, NOT yet enforced (tracked in §12):**
- Role→ceiling binding as an automatic default (today the ceiling is caller-supplied).
- Rich `access_policy` object (today `{"tenant": …}`); `min_role`/`mask_fields`/`system_prompt_eligible`/`export_eligible` are not yet read by the engine.
- Assembly-time **field-masking / gist substitution** (today above-ceiling rows are dropped, not masked).
- Prefetch access filtering (`prefetch.py` does none).
- Most-restrictive `access_policy` merge on derived items (today first-evidence, `consolidation.py:1511`).

**Auditability.** Every access decision and redaction is recorded with the write/audit log (actor/source/tier/diff, §27); `search --explain` surfaces *why* an item was dropped or masked. The rules above are verified through `auth-ops-check`, `privacy-ops-check`, the retrieval trust/sensitivity/quarantine-filter tests, and the provider/ops redaction bundles. **Defining new checks is the validation lane's job, not this one.**

## 12. Hardening backlog (disclosure-side)

Ordered by disclosure risk. Each is a gap between §1–§10 (target) and §11 (today):

1. **Wire field-masking at §22.6** so "mask" stops degrading to "deny" and PII spans (`mask_fields`) are dropped in place.
2. **Add prefetch access filtering** so warmed caches never hold above-ceiling content.
3. **Bind role→`max_sensitivity` as the default ceiling** (`reader`=S1 … `consolidator`=S4) instead of trusting the caller's filter.
4. **Engine reads the full `access_policy` object** (`min_role`, `system_prompt_eligible`, `export_eligible`).
5. **Fix derived `access_policy` to most-restrictive merge** (replace `_first_access_policy`).
6. **Expand the ingest PII detector** beyond email/phone toward the §2.2 taxonomy (or require source-level `--sensitivity` floors and document the residual risk).

## 13. Governance

- **Owner.** This policy is owned by the security/privacy lane; changes are PRs against this file.
- **Change control.** Material changes to the levels (§2), the matrix (§4.3), or the `access_policy` shape (§3) require a recorded acknowledgement consistent with the repo's fingerprint/rollout pattern (e.g. the `idp-authz-policy-rollout-check` / gate-suite acknowledgement style) so a disclosure-widening change cannot land silently.
- **Review cadence.** Re-review whenever §11 changes (a target becomes enforced), when a new memory type or modality is added, or when the PII detector's coverage changes — because each can move the effective disclosure surface.

## 14. Quick reference

```
Two axes (never collapse):
  trust_tier 0..5   → may it INFLUENCE?    gated by §27 / security.py        (not this lane)
  sensitivity S0..4 → may it be DISCLOSED? gated here

Classify (ingest, §2):
  S0 public · S1 internal · S2 PII/confidential · S3 regulated · S4 secret-referenced
  effective = max(stored, pii/trust floor)     ── fail safe, never open      [ingestion.py:152]
  derived inherits MAX sensitivity of evidence ── escalate-only              [consolidation.py:727]
  detector today = email/phone only → set --sensitivity for regulated data   [GAP §2.2]

Disclose (ceiling at §22.3 → mask at §22.6 → export):
  ceiling rule: drop if trust_tier>max_trust OR sensitivity>max_sensitivity  [engine.py:1177]
  reader S1 · agent S2(masked)/S3 ptr/S4 ptr · consolidator S4 · operator metadata-only
  external / cross-tenant ............... DENY (hard isolation §4.1 — absolute)
  S3+/untrusted ......................... never to the system prompt (§4.4)

Redact (view transform, NOT a ledger edit):
  full → field-mask → gist → pointer-only → withhold+abstain
  today: ceiling DROPS above-level rows; field-masking not yet shipped       [GAP §5.2/§12]

Residency: pinned at ingest, cross-region deny-by-default                    [ingestion.py:114]
Break-glass: operator S2+ only with grant + dual-control audit (§9)
Don't confuse: redaction (disclosure) ≠ fidelity demotion (utility §25) ≠ erasure (destructive §25)
```

## 15. Glossary

- **Effective sensitivity** — `max(stored sensitivity, floor implied by pii_tags/trust_tier)`; the value every disclosure check uses.
- **Ceiling** — the `max_sensitivity` (and `max_trust_tier`) a given read is allowed; candidates above it are excluded.
- **Principal** — the acting identity: data subject (owner) or a session role (`reader`/`agent`/`consolidator`/`operator`).
- **Redaction** — non-destructive, per-read view transform that lowers what a principal sees. Reversible; never edits the ledger.
- **Erasure** — destructive crypto-shred + transitive recompute (§25); not a redaction outcome.
- **Quarantine** — inbound/trust state that, for disclosure, excludes a row from default retrieval (§4.5).
- **Break-glass** — audited, dual-controlled exceptional operator access to S2+ plaintext (§9).
- **Residency** — region pin enforced at ingest; cross-region movement is deny-by-default (§8).

## 16. Boundaries restated (so this lane stays scoped)

- **§27 / `security.py`** owns trust tiers, capability-gated writes, `authorize_write`, the quarantine LLM, sanitization, signed provenance, and **secret detection/handling**. This lane *reads* `trust_tier`/`capability_tags` and *references* the system-prompt rail; it defines none of them.
- **§25 / `ErasureMode`** owns destructive erasure and fidelity demotion. This lane's redaction is a non-destructive, per-read view transform and must not be used to describe erasure.
- **§22** owns the retrieval pipeline. This lane supplies the access predicate at §22.3 and the mask at §22.6; it does not alter channels, ranking, or budgets.
- **§29 / `sql/schema.sql`** owns the columns. This lane assigns meaning to `sensitivity` and the `access_policy` object; it adds and renames nothing.
- **The validation lane** owns pass/fail gates and check definitions. This lane *references* `auth-ops-check` / `privacy-ops-check` / retrieval-filter tests as the verification surface (§11) and defines no new checks.
- **This lane** owns: the sensitivity levels, the PII taxonomy, effective-sensitivity/escalation rules, the `access_policy` object semantics, the role ceilings and need-to-know matrix, the redaction ladder and triggers, lifecycle disclosure rules, residency/break-glass disclosure rules, the threat→control map, and the disclosure-side conformance and hardening backlog. New trust/write rules, erasure steps, retrieval mechanics, columns, or gate definitions discovered while using this doc belong in §27, §25, §22, §29, or the validation lane respectively — link to them; don't copy them here.
