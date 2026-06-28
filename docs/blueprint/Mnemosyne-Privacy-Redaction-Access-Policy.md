# Mnemosyne — Privacy, Redaction & Access-Control Policy

> **Lane scope.** This document defines **how memory content is classified by confidentiality, what redaction transforms are applied at each disclosure boundary, and the access predicate that decides who or what may see each class — including the surfaces nothing else owns: egress to the model provider, bitemporal "as-of" queries, branches, embeddings/latent space, telemetry, and data residency.** It is an enforceable, auditable policy keyed to fields and chokepoints that already exist in the Build Blueprint — not a new subsystem.
>
> **What this lane does _not_ own (read those first):**
> - **Secret handling & credential-grade write defenses** (Build Blueprint **§27**, innovation **I11**). Trust tiers 0–5, capability-gated writes, the CaMeL/dual-LLM quarantine pattern, taint labels / data-never-instruction, signed provenance (C2PA), anti-poisoning isolation, and the *detection and vaulting* of secrets at ingest are all §27's. This doc never redefines them. Where a memory contains an actual credential or secret, §27 owns its capture-time handling and vaulting; **this doc owns only its at-rest classification, its redaction posture, and its read boundary.**
> - **Schema / data model** (**§19** meta-envelope, **§29** DDL, **Appendix A**). The fields this policy keys on all already exist: `sensitivity`, `trust_tier`, `capability_tags[]`, `status`, `fidelity`, the bitemporal columns (`valid_from/valid_to/recorded_at/expired_at`), `branch`, `erased` (on `evidence`; `assertions` express erasure as `status='retracted'`), and the **per-row `access_policy` JSONB** — which is universal (every table carries it) and is the home this policy uses for purpose, lawful basis, grants, region, and the restriction `hold` flag. (`scope` exists only on `assertions`/`preferences` and is used here only for need-to-know.) This doc assigns **meaning and allowed values** to `sensitivity` and to the access-relevant keys of `access_policy`/`capability_tags`. **It adds no columns and renames none.**
> - **Retrieval engine** (**§22**, especially **§22.3** security-before-ranking and **§22.6** context assembly). This doc *defines* the access predicate and redaction transform that §22.3 drops on and §22.6 applies — it is the meaning of "out-of-permission" in §22.3 — but it does not redefine channels, ranking, or the latency contract.
> - **Forgetting & erasure** (**§25**). Decay, fidelity demotion, and transitive crypto-shred erasure are §25's. This doc names **which classes trigger erasure-class disposition** and closes the re-identification gaps that redaction, pseudonymization, branches, and bitemporal history open.
> - **User model** (**§24** / **I9**) and **belief revision** (**§30.3** / **I2**). The six typed preference categories and the rectification path live there. This doc references the identity/PII they hold and routes the *rectification* right through the belief core; it does not redefine either.
>
> If a sentence here starts to read like a write-gating rule, an injection defense, a DDL change, or a retrieval-pipeline stage, it belongs in one of those lanes, not this one.

---

## 0. The axes to internalize first — trust ≠ sensitivity ≠ purpose

Three orthogonal questions ride on every memory and every request. Conflating any pair is the root cause of leaks, poisoning, or function creep.

- **Trust tier (0–5, owned by §27/I11)** — *"how much may this content influence behavior?"* The **inbound** axis; guards poisoning/injection. Tier-5 (external) is data-only, never instruction.
- **Sensitivity class (this doc, §1)** — *"to whom may this content be disclosed?"* The **outbound** axis; guards leakage.
- **Purpose binding (this doc, §4)** — *"for what use was this captured, and is this use compatible?"* The **lawful-basis** axis; guards function creep and satisfies purpose limitation.

They are independent. A tier-5 untrusted item can be `S0/PUBLIC` (scraped text) **or** `S4` (a password a stranger pasted). A tier-0 system item can be `S4`. A high-trust, low-sensitivity fact captured for "calendar scheduling" still may not be used for "ad targeting." **Never derive one axis from another.** §22.3 filters on all three, separately and conjunctively.

---

## 1. Classification levels — the `sensitivity` lattice

The existing `sensitivity` field is given a **total order** (a lattice under `max`), so dominance, least-privilege, and the access predicate are monotone and trivially auditable.

| Level | Name | Content | Default read boundary | At-rest posture |
|---|---|---|---|---|
| **S0** | PUBLIC | Non-personal, already-public, or synthetic data | Any principal in-tenant | Verbatim OK |
| **S1** | INTERNAL | Operational/derived data, non-identifying | In-tenant, any authorized agent | Verbatim OK |
| **S2** | CONFIDENTIAL | Personal data / PII (identity, contact, behavior tied to a person) | Subject + agents acting for the subject (need-to-know) | Verbatim OK; no recoverable shared-latent embed |
| **S3** | RESTRICTED | Sensitive/regulated personal data (health, financial, precise location, biometric, special categories) | Subject only + explicit scoped grant | Verbatim OK; never shared-latent; priority erasure; residency-pinned |
| **S4** | SECRET-REFERENCED | Credential/secret material (keys, tokens, passwords) | Never disclosed as plaintext to any principal | **Reference only — verbatim secret never enters the ledger; the value is vaulted by §27** |

**Sub-typing without new columns.** Regulatory routing (e.g. `health`, `financial`, `location`, `biometric`, `minor`) rides on the existing `capability_tags[]` as `pii:<subtype>` tags, *not* a new field. The access predicate (§6) requires the matching capability to read a sub-typed item, which is how HIPAA-/GLBA-/special-category routing is enforced with machinery that already exists.

Rules governing the field:

1. **Assigned at ingest.** §20 already runs `classify(raw, ctx) → PII`; this policy fixes the **allowed values** it writes into `sensitivity` and the procedure (§3).
2. **Monotonic by default.** Any actor may **raise** a classification; only an authorized actor (§7) may **lower** one, and only with a logged justification (mirrors the `monotonic_trust` rail of §31).
3. **Derived items inherit the join.** A memory's sensitivity is `≥ max(sensitivity of its source evidence)`, enforced along the provenance graph (I5). Supersession (§25) may never lower a surviving item below that join.
4. **S4 is a reference, not a value.** Classifying as S4 hands the secret to §27's vault and leaves a typed, non-sensitive descriptor on the envelope. This policy governs the descriptor's disclosure, not the secret's storage.
5. **Linkage escalates.** A *set* of S0/S1 quasi-identifiers that jointly re-identify a person is, as a set, treated as S2 — see the linkage rule in §3 and the aggregation thresholds in §8.

---

## 2. Principles (the test every rule must pass)

Anchored to the blueprint's design philosophy (§4). A proposed rule that violates one of these is wrong, not merely unusual.

- **Deny-by-default / fail-closed.** Absence of an explicit permit is a denial. A classifier error, missing field, or evaluator exception denies disclosure, never grants it.
- **Least privilege & need-to-know.** A principal sees the minimum class and scope its task requires, nothing wider.
- **Data minimization & purpose limitation.** Capture and disclose the least data for the bound purpose; no silent re-purposing (§4).
- **Privacy by design & by default.** The conservative classification and the tightest boundary are the defaults; loosening is an explicit, logged act.
- **Defense in depth.** The same decision is enforced at every egress, not once — so a bug at one boundary is not a breach.
- **Reversibility of disclosure decisions, irreversibility of erasure.** Every disclosure is replayable from its audit record; every erasure is final and total (§9).
- **Auditability over trust.** A rule that cannot be logged and tested is not a control. If it isn't in `privacy_rails` (§10) and a test class (§10), it isn't enforced.

---

## 3. Classification procedure & defaults

- **Conservative default.** Any user-originated or unattributed content whose class is undetermined is floored at **S2**. Public-source, non-personal content defaults to S0/S1. Defaulting *down* from S2 requires the detector to affirmatively establish non-personal content.
- **Detector + confidence.** §20's classifier emits a class plus a confidence (§26). **Below the per-type conformal threshold, escalate one level** (fail-safe) and flag for review rather than abstaining into a permissive state.
- **Special categories & minors.** Detected health/financial/biometric/precise-location → S3 + the `pii:<subtype>` tag. Any indication the subject is a minor → S3 floor + `pii:minor`, regardless of other signals.
- **Linkage / quasi-identifier rule.** Quasi-identifier fields (name, DOB, ZIP, device id, …) are tagged `pii:quasi` at ingest (existing `capability_tags`). The consolidation pass (§21) runs the *exhaustive* linkage check: if a joinable set of S0/S1 items re-identifies an individual, the set is re-tagged so the *combination* is gated at S2 (a derived item per §1 rule 3). Because that pass is warm, a **cheap hot-path guard** also applies (§6): when an assembled packet carries ≥ a configured count of `pii:quasi` tags for one subject, the *packet* is gated at S2 pending the linkage pass — so the hot path cannot ship a re-identifying S0/S1 set as individually-low-class items.
- **Reclassification triggers.** (a) linkage detected; (b) a merge/summary in consolidation joins higher-class evidence; (c) a subject reclassifies their own data; (d) an authorized operator lowers a class with justification. All are logged; (b) and (a) can only raise.
- **Who may classify.** See §7. Raising: any actor or detector. Lowering: operator/subject roles only, logged.

---

## 4. Purpose limitation & lawful basis

- **Purpose is bound at capture.** `memory.capture(content, source, trust, scope)` records a **purpose** and, for S2+, a **lawful basis** (consent / contract / legal-obligation / legitimate-interest) in the row's universal `access_policy` JSONB — no new column. Consent records are first-class evidence so they are revocable and auditable.
- **Purpose check in the predicate.** A request carries its own purpose; `purpose_compatible(item.access_policy.purpose, ctx.purpose)` is a conjunct of `may_read` (§6). Incompatible purpose → drop, even when clearance and scope would otherwise allow. **Fail-closed:** a missing `access_policy.purpose` (or any predicate-required key) evaluates the conjunct to *false*, never true (§2).
- **No silent re-purposing.** Using an S2+ memory for a purpose outside its captured set requires a new, scoped, expiring **grant** (§6) recorded as evidence — the same mechanism as a clearance grant, so consent-withdrawal and re-purposing share one audit trail.
- **Withdrawal.** Withdrawing consent revokes the lawful-basis evidence; items resting solely on it become non-disclosable immediately and are queued for erasure/restriction per §9. Items with surviving independent lawful basis are retained with the withdrawn basis dropped from provenance (mirrors §25's corroboration logic).

This section maps to GDPR Art. 5 (purpose/storage limitation, minimization), Art. 6/9 (lawful basis, special categories), and CPRA purpose-disclosure — without this doc owning the regulatory runbook, which is a deployment concern (§32/§15 "data residency configurable").

---

## 5. Redaction — triggers and transforms

Redaction is a **deterministic, boundary-applied transform**, not a mutation. The ledger stays append-only; redaction is applied **on the way out** (sanitize-on-retrieval, per §27), never by rewriting the stored item. Three distinct operations, never conflated:

- **Minimization** — capturing/keeping less (purpose-driven, §4).
- **Redaction** — reversible-by-authorization masking at an egress boundary (this section).
- **Erasure** — irreversible transitive crypto-shred of stored evidence (§25/§9).

**Triggers — redaction fires when:**

| # | Trigger | Action |
|---|---|---|
| T1 | Ingest detects secret material → S4 | The value is handled at capture by §27 (vaulting is §27's mechanism, not redefined here); the envelope keeps a typed, non-sensitive reference. Verbatim secret never lands in the ledger. |
| T2 | Retrieval assembles an item whose audience clearance < item sensitivity (or purpose-incompatible) | §22.3 **drops** it; if the boundary permits a masked form, §22.6 emits the masked surrogate. |
| T3 | **Egress to an external model provider** (prompt/tool-call leaving the trust domain) | Disclose only ≤ the provider's contracted clearance; S3+ never sent verbatim to a non-zero-retention or out-of-region endpoint; mask/pseudonymize otherwise. (See §8 B-model.) |
| T4 | `memory.export(scope)` crosses a sensitivity ceiling | Redact above the export scope's ceiling; S4 never exported as plaintext. |
| T5 | Audit log / `search --explain` output | Log `cid` + classification + transform applied — **never the sensitive value**. Critically, the write/merge audit (`audit_log.diff`, `merges.report`) must store `{cid, from_class, to_class, transform}` for S2+, **not** the raw before/after content — otherwise a supersession/rectification diff or a merge report becomes a plaintext S2+/S4-descriptor sink readable by the Auditor role. |
| T6 | Latent-model / embedding generation over S3+ (or shared-latent over S2) | Do not embed recoverably; embed a redacted surrogate or tag `no_embed` (§8). |
| T7 | Any cross-**tenant** or cross-**region** egress | Cross-tenant is **forbidden at every class** (isolation is absolute, §27/B1; even S0's read boundary is in-tenant per §1). Cross-region is forbidden for S3/`pii:*` (residency-pinned, §8/B9) and needs a residency grant for S2. Cross-**user** within a tenant masks S2 to ≤ S1 absent a scope grant (B2). |
| T8 | Branch merge into a more widely-readable branch | Re-evaluate class at the join; never let a merge widen disclosure below the source's ceiling (§8). |
| T9 | Telemetry / reconsolidation-on-read (§22.7) writes access records | Record access metadata as itself S2 (it reveals what a subject looked at); never log the content value. |

**Transforms (least to most lossy):** `mask` (typed placeholder, e.g. `⟨EMAIL⟩`) · `pseudonymize` (reversible only via the §27 vault) · `summarize-without-specifics` (a gist-style summary that strips identifiers — distinct from §25's *stored* fidelity demotion; redaction is boundary-applied and never mutates the stored item) · `pointer-only` (reference to the verbatim drawer, gated by clearance) · `drop` (never reaches the slot).

**Determinism & auditability.** The transform is a pure function of `(item.sensitivity, item.capability_tags, boundary, ctx.clearance, ctx.purpose)`; every disclosure decision is reconstructable and replayable. Each redaction emits `{cid, from_class, transform, boundary, actor, purpose, justification_ref}`.

**Re-identification governance.** Reversing a `pseudonymize` (vault lookup) is itself a privileged disclosure requiring the re-identify capability (§7), logged, and forbidden to the user-facing agent. Pseudonyms that cross the model-provider (B-model) or export (B5) boundary are **per-disclosure salted, never globally deterministic** — a stable token would let an external processor (or a reader of several outputs) re-link all of a subject's records and re-identify by auxiliary data *without ever touching the vault*. Only the in-domain vault path uses stable tokens.

---

## 6. Access boundaries — the read predicate

All access is **deny-by-default**. A request carries `ctx = (tenant, subject, role, capability_set, scope, purpose, clearance, region)`, where `clearance` is the audience's sensitivity ceiling. The predicate is evaluated at §22.3 and **re-checked at every egress** (assembly, model-provider, export, audit, API):

```
may_read(item, ctx) :=
      same_tenant(item, ctx)                          # B1 tenant — hard, never crossable
    ∧ same_residency_region(item, ctx)                # B9 residency (item.access_policy.region)
    ∧ in_scope(item.access_policy.scope, ctx.scope)   # B2 need-to-know
    ∧ purpose_compatible(item.access_policy.purpose, ctx.purpose)   # §4 purpose limitation
    ∧ ctx.clearance >= item.sensitivity               # the lattice check (§1)
    ∧ has_caps(ctx, item.capability_tags)             # B3 capability + pii:<subtype> routing
    ∧ item.status ∈ {active, candidate, contested}    # never superseded/quarantined/retracted
    ∧ not erased(item)                                # evidence.erased=true OR assertion status='retracted' (§25)
    ∧ not restricted(item, ctx)                       # §9 restriction-of-processing (access_policy.hold)
# any predicate-required access_policy key that is absent ⇒ the conjunct is false (fail-closed, §2)
```

False → **drop** (default) or **redact to a masked form** if and only if the boundary explicitly allows it (§5 table). A **drop is existence-silent**: to a principal below `item.sensitivity` (or failing `same_tenant`/`same_region`/`in_scope`/`restricted`), the `--explain` output, abstention notes (§22.6/§26), and error messages are **indistinguishable from "no such memory"** — no `cid`, no class, no "redaction fired." Only the `mask`/`pseudonymize`/`pointer-only` surrogates — used where the boundary already permits partial disclosure — may reveal that an item exists.

**Boundaries enumerated:**

- **B1 — Tenant.** Hard. Never crossable by any clearance or grant (mirrors §27 per-tenant isolation).
- **B2 — Subject (within a tenant).** A subject's S2+ memories are invisible to other users/agents in the same tenant absent an explicit scope grant. (The P-Team persona's *shared* memories are a distinct scope, captured at S0/S1 or with team-scope grants — never an implicit widening of a personal memory.)
- **B3 — Agent / tool.** The user-facing agent reads a view filtered to ≤ its granted clearance, capabilities, and purpose. Untrusted-derived or quarantined items never enter its context **regardless of sensitivity** — that exclusion is §27's trust axis applied in the same §22.3 filter.
- **B4 — System prompt.** S2+ content is forbidden from any persistent system prompt. (Untrusted-derived content is *also* forbidden there by §31's `untrusted_to_system_prompt`; this doc adds only the sensitivity-side rule.)
- **B5 — Export / portability.** Honors the requesting scope's ceiling; S4 never leaves as plaintext. Backs the data-portability right (§9).
- **B6 — Consolidation / optimizer.** The cold loop and latent-model updater operate on **de-identified or aggregated** views for S2+ (§8). Reward/eval signal is `external_only` (§31).
- **B-model (B7) — External model provider.** Assembling retrieved content into a prompt sent to an out-of-domain model is a *disclosure to a processor*. Gated by the provider's contracted clearance, retention, and region (§8). This is the boundary most systems forget; it is in-lane here.
- **B-time (B8) — Bitemporal / as-of-T.** An "as-of" query (I5) is evaluated against the **current** access policy and **current** classification/erasure state — never the historical permissions. History may not resurrect access that has since been revoked, restricted, or erased (§8).
- **B9 — Residency.** Three tiers: **S0/S1** move freely across regions; **S2** crosses only under an explicit, logged residency grant; **S3 and any `pii:*`-tagged data are hard-pinned** to their residency region and admit *no* grant (the `cross_region_s3_disclosure: forbidden` rail, §10). Cross-region egress of pinned data is treated like a cross-tenant disclosure (backs §15 "data residency configurable").

**Grants.** Any access above a default boundary requires an **explicit, scoped, expiring grant recorded as evidence** — revocable and auditable. Grants are **data, never inferred**: untrusted content cannot mint a grant (defers to §27 for write-gating enforcement).

**Break-glass.** Emergency access beyond a principal's clearance is permitted only via a named break-glass capability that (a) is time-boxed, (b) raises an immediate audit alert, (c) never reaches S4 plaintext, (d) is reviewed after the fact, and (e) for **S3+** requires a **second-actor co-sign recorded as evidence before the read** — not only after-the-fact review. It is an *escalated grant*, not an exception to the predicate.

---

## 7. Roles, clearances & separation of duties

Clearance = `(ceiling ∈ S0..S4, role, capability_set, purpose-set, region)`. Roles and their privileged verbs:

| Role | May classify | May lower class | May grant access | May re-identify | May erase | Reads |
|---|---|---|---|---|---|---|
| **Subject** | own data ↑ | own data | own data (delegate) | own data | request | own, to S4-ref (never S4 plaintext) |
| **User-facing agent** | ↑ only | no | no | **no** | no | granted view ≤ clearance/purpose |
| **Consolidator** | ↑ (join rule) | no | no | no | execute §25 | de-identified S2+ for optimization (B6); identified `cid`+vault **only** while executing erasure, never for ranking/optimization |
| **Operator / DPO** | ↑ | yes (logged) | yes (logged) | yes (logged) | approve | per duty, logged |
| **Auditor** | no | no | no | no | no | metadata & references only, never values |

**Separation of duties.** No single role may both **lower a classification** and **disclose** the lowered item in one action; the two acts are independently logged and, for S3+, require different actors. For **S3+**, the same actor may not be both **grantor and grantee** of a grant, nor both grant and read under it in one action — a self-grant cannot become a read-through (closes the operator self-grant bypass). Operator/DPO grant, re-identify, and lower powers are each independently logged. The user-facing agent — the most-exposed principal — holds the fewest privileges by construction.

---

## 8. Special surfaces (the hard cases nothing else owns)

- **External model provider (B-model).** Treat the model endpoint as a third-party processor. Maintain a per-endpoint contracted clearance, retention policy, and region. Rule: **S3+ never sent verbatim** to a retentive or out-of-region endpoint; S2 sent only to a contracted, zero-retention, in-region endpoint, else pseudonymized; tool-call arguments are subject to the same predicate as context. A self-hosted in-domain model raises the contracted clearance accordingly.
- **Embeddings & latent space.** Embeddings of S2+ content are themselves derived personal data (inversion/membership-inference risk). S3+ → never embedded into shared/advisory latent space recoverably; S2 → per-subject embedding spaces only, never a cross-subject shared space recoverably. The latent user model (I9) is advisory and per-user; this doc forbids it from becoming a cross-subject leak channel. **Enforcement hook** (a §29 coordination, not a new field): the dense-vector index (§22.2) is partitioned — `embed_ok:false`, S4, held, restricted, or unsupported-policy rows are non-embeddable; S2+ and raw/redaction-restricted rows are excluded from the public HNSW path and default to a private partition whose stored raw vectors are usable only by callers authorized to read the raw item. Without this the single tenant-wide HNSW index embeds everyone's S2+ by default and the prohibition has no teeth. Test: no S2+ row is retrievable from the shared public index by a different `user_id`, and redacted callers cannot rank through a raw stored vector.
- **Dedup oracle.** Content-addressed dedup (`cid = sha256(content)`, idempotent per tenant; §20/§29) is a *confirmation oracle*: a principal who ingests a guessed S2+ value and observes a dedup no-op (timing, returned `cid` status, or `--explain`) confirms another subject's content verbatim **without ever reading it** — crossing B2 on the write side. For S2+, `cid` idempotency is scoped per `(tenant, user_id, branch)` (or the `cid` is per-subject salted), so cross-subject dedup never reveals a hit. Keys on the existing `user_id`; a §20/§29 coordination, not a new field.
- **Ranking side-channels.** §22.3 drops out-of-permission items **before** fusion (§22.4), but ACT-R `base_level`/`spreading` activation could still let a gated S2+ neighbour perturb the *scores and ordering* of surviving S0/S1 results — an inference channel. Rule: activation contributions (`base_level`, `spreading`, reconsolidation bumps from §22.7) of items failing `may_read(ctx)` are **zeroed for that `ctx` before fusion**, and `--explain` never exposes raw activation components contributed by items above the principal's class.
- **Aggregation / de-identification thresholds (B6).** Optimizer and analytics views over S2+ must satisfy a **k-anonymity floor (k ≥ a configured, non-null minimum)** per released aggregate, with small-cell suppression **and a query-set differencing guard** — a per-subject aggregate budget or *mandatory* calibrated noise (not "where feasible") — so two overlapping aggregates (cohort of 5, then of 4) cannot isolate a subject across the cold loop's repeated passes. The cold loop sees aggregates, never individuals.
- **Bitemporal (B-time).** Restated for emphasis: as-of-T answers reflect *what was true then* but are gated by *who may see it now*. Erasure and restriction win over historical recall — the one sanctioned narrowing of the §22 "completeness guarantee," parallel to §25's erasure exception to "always reconstructable."
- **Branchable memory (I3).** A branch inherits the classification and access state of its base. A merge re-evaluates class at the join (T8) and may only raise disclosure restrictions, never relax them. **Erasure and restriction propagate across all branches** (extends §25's transitive shred to the branch graph) — a forgotten subject cannot survive on a side branch. Branch/merge audit records (`merges.report`, branch names tied to a subject) are themselves S2 metadata (T9): a merge re-runs `may_read` and redacts `report` values above the target branch's ceiling, so a pre-restriction state cannot re-widen through the retained report.
- **Telemetry & access logs (T9).** Access metadata (`last_accessed`, `access_count`, query traces, retrieval explanations) reveals subject behavior and is classified **S2** in its own right: subject-readable, operator-readable under duty, never cross-subject, and erased with the subject.
- **Residency (B9).** S3/`pii:*` data is region-pinned at rest and in transit; replication, backup, and consolidation honor the pin. S3/`pii:*` cross-region movement is a **hard denial** (B1-equivalent, no grant — the `cross_region_s3_disclosure` rail); **S2** may cross only under an explicit residency grant; **S0/S1** move freely.

---

## 9. Lifecycle, retention & data-subject rights (boundary with §25)

**Class-keyed retention.** S0/S1 follow ordinary decay (§25). S2/S3 carry shorter default retention; S3 (regulated) and S4 (references) get **priority erasure** on request. This doc sets class-keyed defaults and floors; §25 enforces them via decay/demotion.

**Data-subject rights → existing API verbs** (no new surface):

| Right | Mechanism |
|---|---|
| Access / transparency | `memory.export(scope)` + `search --explain` (references, classification) |
| Rectification | route the correction through the belief core (I2/§30.3) — superseding evidence, not a destructive edit |
| Erasure ("right to be forgotten") | `memory.forget(id, mode)` → §25 transitive crypto-shred |
| Portability | `memory.export(scope)` honoring B5 ceiling |
| Restriction of processing | set a `hold:<basis>` flag in `scope` (or a `restricted` capability tag) — no schema change; the `restricted()` conjunct (§6) then excludes the retained item from `may_read`. *(A first-class `status` value would be cleaner but is a §29 coordination, not a change this lane makes.)* |
| Objection / withdraw consent | revoke lawful-basis evidence (§4); items resting solely on it → restricted then erased |

**Erasure close-out (this lane's obligation).** A subject-erasure runs §25's transitive shred **and additionally** purges: (a) the `pseudonymize` **vault token mapping** (else tokenized PII is re-identifiable); (b) any sensitive values that escaped into **redaction/audit records**; (c) derived **embeddings** in any latent space; (d) the item across **all branches** (I3); (e) **bitemporal history** of the erased evidence; (f) the erased content's **hash `cid`** wherever retained (`deletion_log.evidence_cid`, surviving `source_evidence_cids[]`/provenance arrays) — replaced with a random/HMAC deletion-record id, since `cid = sha256(content)` otherwise lets anyone confirm a guessable erased value (`sha256(guess)` match); (g) any **retained derived assertion** whose text was generated while erased evidence was in scope is **recomputed/regenerated**, not merely provenance-dropped, so a partially-corroborated derivation carries no erased specifics. "Always reconstructable" remains scoped to non-erased evidence — the single sanctioned exception (§25). Erasure completeness is a test class (§10).

**Propagation bound.** Consent-withdrawal and restriction propagate to caches, embeddings, branches, and **contracted external processors** within the same bounded window as erasure (§10 SLO). When data already disclosed to a model provider (B-model) is withdrawn or restricted, the provider's contracted deletion is triggered and logged — an in-flight or already-sent value is not left orphaned at the processor.

**No silent downgrade on supersession.** See §1 rule 3.

---

## 10. Enforcement, audit & assurance — so the policy is real, not aspirational

**Single chokepoint.** Every read traverses the §22.3 predicate; every egress (assembly, model-provider, export, audit, API) traverses the redaction boundary. There is **no path that returns content without passing one** — that single-funnel property, plus defense-in-depth re-checks, is what makes the policy enforceable rather than advisory.

**Mechanisms reused (nothing new built):** `sensitivity` · the universal **`access_policy` JSONB** (purpose, lawful basis, grants, region, `hold:<basis>`) · `scope` (need-to-know, on `assertions`/`preferences`) · `capability_tags[]` (`pii:<subtype>`, `pii:quasi`, roles, grants, `restricted`) · `branch` · the write/merge audit log (extended to store `{cid, from_class, to_class, transform}` for S2+, never raw diffs/reports) · `search --explain` (surfaces classification and whether redaction fired, never the value) · transitive erasure (§25) · the belief core (rectification, I2). The two non-field enforcement hooks that need §29/§20 coordination — the **partial vector index** (no shared-latent S2+) and **per-subject `cid` scoping** (no dedup oracle) — are flagged as such in §8, not silently assumed.

**Policy-side invariant rails** (same spirit as §31 — the cold loop tunes *within* these and can never widen them):

```yaml
privacy_rails:
  cross_tenant_disclosure: forbidden
  cross_region_s3_disclosure: forbidden          # residency, B9
  disclose_above_clearance: forbidden
  disclose_against_purpose: forbidden            # §4
  missing_access_policy_key_denies: true         # fail-closed, §4/§6
  s4_plaintext_at_rest: forbidden                # never in ledger/index/embedding
  s4_plaintext_egress: forbidden                 # never in context, export, audit, model-provider, prompt
  s3plus_verbatim_to_external_model: forbidden   # B-model
  external_model_stable_pseudonym_s2plus: forbidden  # per-disclosure salt only, §5/§8
  embed_s2plus_in_shared_latent: forbidden       # inversion risk, §8 (partial-index hook)
  dedup_oracle_cross_subject_s2plus: forbidden   # cid scoped per subject, §8
  ranking_leak_from_gated_items: forbidden       # zero activation before fusion, §8
  audit_diff_plaintext_above_s1: forbidden       # diffs/reports store {cid,class,transform}, §5 T5
  pii_in_persistent_system_prompt: forbidden     # S2+, B4
  grant_from_untrusted_source: forbidden         # grants are data, defers to §27
  self_grant_read_through_s3plus: forbidden      # grantor≠grantee, §7
  asof_query_uses_historical_permissions: forbidden  # B-time
  default_class_floor: S2                         # for undetermined/user-originated content only; public non-personal → S0/S1 (§3)
  min_k_anonymity: <configured, non-null>        # aggregates + differencing guard, §8
  restriction_propagation_window: "<= erasure_window"  # incl. external processors, §9
```

**Auditable invariants (test classes that must exist, in the spirit of §33):**
1. A clearance-below-sensitivity (or purpose-incompatible) read returns drop/masked — **never plaintext**.
2. A cross-tenant or cross-region-S3 read returns **nothing**, at any clearance.
3. S4 verbatim appears in **no** ledger row, embedding, export, audit record, model-provider prompt, or system prompt.
4. Subject-erasure removes vault token mapping, audit values, embeddings, all branches, and bitemporal history (no re-identification).
5. A derived item's `sensitivity` `≥ max(evidence.sensitivity)`; supersession never lowers it; merges never widen disclosure.
6. An as-of-T query honors *current* permissions and erasure/restriction state.
7. Consent withdrawal makes solely-dependent items non-disclosable in the same pass.
8. Every disclosure has a replayable redaction/grant record; every break-glass raises an alert (and S3+ break-glass carries a pre-read co-sign).
9. A denied read is **existence-silent**: `--explain`, abstention, and error output for a dropped item are indistinguishable from absence to a principal below its class.
10. A cross-subject dedup of a guessed S2+ value reveals no hit; the shared vector index returns no S2+ row to a different `user_id`.
11. Items failing `may_read(ctx)` contribute **zero** to the scores/ordering of an under-cleared `ctx`'s results.
12. Two overlapping aggregates cannot isolate a subject; small cells are suppressed.
13. Post-erasure, **no retained row** (`deletion_log`, provenance arrays, merge reports) lets `sha256(guess)` confirm erased content, and partially-derived items carry no erased specifics.
14. A missing predicate-required `access_policy` key evaluates `may_read = false` (fail-closed).

**Monitoring & response.** Leak canaries: seeded honeytoken memories per class whose appearance at a lower boundary fires an alarm. Privacy SLOs: zero cross-tenant disclosures; erasure-completeness ≤ a bounded propagation window. A confirmed boundary violation is a breach: contain (revoke grants, mark affected items `restricted`, freeze the branch), assess scope via the audit log + provenance graph, notify per the deployment's regulatory clock (a §32/§15 concern this lane feeds, not owns). This lane **owns the trigger and the evidence**: a confirmed violation auto-emits a breach record (scope reconstructed from `audit_log` + the provenance graph) and raises a **DPIA-review flag** whenever S3/`pii:*` data or the latent user model (I9, inherently high-risk automated profiling) is implicated — deferring only the jurisdictional notification timing (e.g. the 72-hour clock) to §32, so no obligation falls between lanes.

---

## 11. Worked examples (the predicate in motion)

1. **Other user in the same tenant requests "Jake's home address."** S2, subject = Jake, requester ≠ Jake, no grant → `same_tenant ✓`, `in_scope ✗` → **drop**. Not even a masked form (existence itself is need-to-know).
2. **Jake's own agent drafts an email needing his address.** S2, subject = Jake, agent acts for Jake, purpose = "correspondence" compatible → **allow verbatim** into assembly (B3), but **not** into the persistent system prompt (B4).
3. **Agent calls an external model to summarize Jake's lab results (S3:health).** B-model: endpoint is retentive/out-of-region → `s3plus_verbatim_to_external_model: forbidden` → **pseudonymize or refuse**; if a contracted zero-retention in-region endpoint exists and purpose matches, disclose under that grant, logged.
4. **Auditor runs `search --explain` over Jake's data.** Returns `cid`s, classes, and which transforms fired — **never the values** (T5, auditor row in §7).
5. **Jake withdraws consent for "marketing" purpose, then an as-of-last-month query runs.** Lawful basis revoked (§4); items resting solely on it → restricted/erased; the as-of query (B-time) sees current state → those items **do not resurface** despite having been visible last month.
6. **Consolidator builds a cohort statistic touching 3 subjects.** k-anonymity floor unmet → **small cell suppressed** (B6/§8); the individuals never enter the optimizer's view.

---

## 12. Open questions & known tensions (honest, per §17/§38)

- **Lossless recall vs. erasure/restriction.** Bounded by design (§25/§38); B-time enforces current-policy gating, but a determined "audit everything" deep-mode query (§22) and aggressive erasure pull in opposite directions. The bound is principled, not free.
- **Latent personalization vs. minimization.** A per-user advisory embedding (I9) inherently encodes S2+ signal. Per-subject isolation + no-shared-embed contains leakage but does not eliminate inversion risk on the per-user space itself; treat the per-user embedding as S2.
- **Classifier accuracy ceiling.** Fail-safe escalation (§3) trades precision for safety; mass over-classification degrades utility. The conformal threshold is the tuning knob and a monitored metric.
- **Linkage detection cost.** Exhaustive quasi-identifier linkage (§3) is expensive; v1 runs the full check in consolidation (warm, gated) and a cheap `pii:quasi`-packet guard on the hot path (§3/§6). The hot-path guard is conservative (counts tags, doesn't prove re-identification), so it over- and under-classifies at the margin — a known coverage/latency trade.
- **Shared-team scope (P-Team).** The cleanest model is "shared memories are a separate scope, never an implicit widening." Whether teams will accept the friction of explicit team-scope capture is unresolved and a product question.
- **Break-glass abuse.** After-the-fact review is the control; real-time prevention of a privileged operator is out of scope for the memory layer.

---

## 13. Quick reference

- **Three axes:** trust (§27, inbound) · sensitivity (this doc, outbound) · purpose (this doc, lawful basis). Never conflate.
- **Lattice:** S0 public · S1 internal · S2 PII · S3 regulated · S4 secret-referenced. Derived = `max(evidence)`; raise freely, lower only with logged authorization.
- **Predicate:** `same_tenant ∧ same_region ∧ in_scope ∧ purpose_compatible ∧ clearance≥sensitivity ∧ caps ∧ active ∧ ¬erased ∧ ¬restricted` (missing required `access_policy` key ⇒ false; denied reads are existence-silent) → else drop/redact.

**Disclosure decision table** (cell = action at that boundary for that class):

| Boundary ↓ / Class → | S0 | S1 | S2 | S3 | S4 |
|---|---|---|---|---|---|
| In-tenant retrieval | allow | allow | need-to-know | grant-only | drop |
| Context assembly | allow | allow | allow if subject | mask/pointer | drop |
| External model (B-model) | allow | allow | zero-retention only | forbidden verbatim | forbidden |
| Export | allow | allow | scope-ceiling | scope-ceiling | forbidden |
| Audit / `--explain` | allow | allow | reference-only | reference-only | reference-only |
| Latent / consolidation | allow | allow | de-identified, per-subject | de-identified | forbidden |
| System prompt | allow | allow | forbidden | forbidden | forbidden |
| As-of-T (B-time) | current-policy + erasure state | → | → | → | → |
| Cross-tenant | forbidden | forbidden | forbidden | forbidden | forbidden |
| Cross-region (B9) | allow | allow | residency grant | forbidden | forbidden |

**Rights → verbs:** access→`export`/`explain` · rectify→belief core · erase→`forget` · portability→`export` · restrict→`access_policy hold:<basis>` flag · object→revoke lawful basis.

---

## 14. Boundaries restated (so this lane stays scoped)

- **Owned here:** the `sensitivity` lattice and its values; sub-typing on `capability_tags`; classification procedure & fail-safe defaults; purpose limitation & lawful basis; redaction triggers/transforms & re-identification governance; the read-access predicate and all boundaries B1–B9 incl. model-provider, bitemporal, branch, residency; roles & separation of duties; data-subject-rights mapping; the erasure close-out; the `privacy_rails`, test classes, and monitoring.
- **Referenced, not redefined:** trust tiers, capability issuance, write-gating, quarantine, injection defenses, signed provenance, secret vaulting (**§27 / I11**); all schema fields (**§19 / §29 / App. A**); the retrieval pipeline (**§22**); erasure propagation and fidelity tiers (**§25**); the typed preference categories and rectification (**§24 / I9 / I2**); branching mechanics (**I3**); the optimizer rails (**§31**); the deployment/regulatory runbook and residency configuration (**§32 / §15**).
- **The line with secret handling:** §27 decides *whether something is a secret and how it is captured and vaulted*; this doc decides *how that secret's reference — and every other classified memory — is disclosed, masked, and bounded on read.* Detection and capture mechanics → §27. Classification, redaction, and access on egress → here.

---

## Glossary

- **Sensitivity / class (S0–S4)** — the outbound confidentiality level on `sensitivity`.
- **Clearance** — a principal's maximum readable class, with role, capabilities, purpose-set, region.
- **Trust tier (0–5)** — §27's inbound influence level; orthogonal to sensitivity.
- **Purpose binding** — the captured use of a memory, in `access_policy`; checked on read (§4).
- **Grant** — an explicit, scoped, expiring, evidence-recorded permission above a default boundary.
- **Redaction** — reversible-by-authorization masking at egress; ≠ erasure.
- **Erasure** — irreversible transitive crypto-shred (§25) + this lane's close-out (§9).
- **Restriction / held** — retained-but-non-disclosable item, marked via an `access_policy` `hold:<basis>` flag / `restricted` capability tag; GDPR restriction-of-processing.
- **Break-glass** — time-boxed, alarmed, reviewed emergency grant; never reaches S4 plaintext.
- **Linkage / quasi-identifier** — fields that jointly re-identify a subject; escalates a set to S2.
- **B-model / B-time / B9** — the model-provider, bitemporal, and residency disclosure boundaries.
