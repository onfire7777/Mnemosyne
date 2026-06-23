# Mnemosyne — Secret Handling Policy (deployment lane)

**Status:** draft · policy-level · implementation-agnostic
**Scope owner:** deployment-security / secret-handling lane
**Position in the blueprint:** belongs adjacent to §27 (Security & governance) and §32 (Deployment & operations); it does **not** restate either.

This document defines *how operational secrets are handled, stored, and referenced* across Mnemosyne
deployments. It is policy and guardrails only — not schemas, not runbook procedure, not observability
wiring. Where a rule touches another lane, it **cites** that lane rather than re-specifying it.

---

## 0. The one distinction this lane exists to make

Mnemosyne already has a rich notion of **trust in remembered content** — trust tiers, capability
mediation on writes, taint labels, the quarantine LLM, signed provenance (§10, §27, I11). That lane
answers *"can this remembered thing be believed or allowed to write?"*

This lane is about a **different class of object**: the **operational secrets** that authenticate
Mnemosyne's own components to each other and to external services so the deployment can run at all.
These are not memory. They never become memory. The whole policy follows from keeping those two
worlds apart.

> **A trust tier protects the system from what it remembers. A secret policy protects the system's
> ability to operate from being remembered, logged, or leaked.**

---

## 1. What counts as a secret here (taxonomy, not schema)

A *secret* is any credential, key, or token whose disclosure would let an actor impersonate a
Mnemosyne component, read/mutate its stores, or defeat an architectural defense. Grounded in the
v2 architecture, the operational secret classes are:

| Class | Examples (illustrative, not prescriptive) | Why it matters |
|---|---|---|
| **Datastore credentials** | Postgres role passwords / connection strings; vector & graph store access; object-storage keys; ephemeral-state (Redis) credentials | Read or mutate the substrate directly, bypassing all higher-level gating |
| **Model / provider credentials** | API keys for the ingest model, the **quarantine LLM**, the consolidator's model, rerankers, embedding and eval models | Spend, exfiltrate prompts/memory, or impersonate a trusted processing stage |
| **Write-authority credential** | the single credential the **consolidator** holds (§32) | The only thing that can mutate compiled projections / promote — highest blast radius |
| **Capability-issuing & provenance-signing keys** | keys that mint I11 capability tokens; C2PA / signed-provenance signing keys (§27, I11) | Compromise **silently** voids the architectural injection defenses |
| **Tenant-isolation credentials** | per-tenant DB roles / row-level-security identities (§32) | Hold the isolation boundary that nullifies MINJA's shared-memory assumption (§10) |
| **Encryption keys** | at-rest keys for the evidence ledger and object store; key-encryption keys | Confidentiality of the immutable ledger and its derived stores |
| **Service / transport identity** | MCP-server service credentials; inter-service auth (mTLS material, tokens); ingest/webhook endpoint secrets | Network-level impersonation of a component |
| **Reward / eval-signal credentials** | access to the `external_only` reward / verifier / eval suite (§31) | Must stay outside the optimizer's reach or the self-improvement loop can be gamed |

This taxonomy classifies *handling tiers*; it does not define storage layout. Data-model and key
schemas remain owned by §19 / §29.

---

## 2. Core principles (the load-bearing rules)

**P1 — Secrets are never memory.** No operational secret may enter the memory substrate — not the
evidence ledger, not projections, not embeddings, not caches, not the human-editable git
source-of-truth. The ledger is immutable, content-addressed (I3) and verbatim-tiered (I7): a secret
that lands there is effectively *unforgettable* and replicates into derived indexes. **Policy is
prevention at the boundary, not erasure after the fact.** (Erasure mechanics, when prevention fails,
defer to §25 deletion integrity — but a secret in the ledger is always treated as a leak, never as a
routine forget.)

**P2 — Reference, never embed.** Config, code, container images, the git source-of-truth, and this
blueprint reference secrets *by handle* (a non-secret name/identifier) resolved at runtime from a
dedicated secret store. Literal secret material appears in none of them.

**P3 — Component-scoped least privilege.** Each component holds only the secrets its role requires.
In particular: the **quarantine / untrusted-processing LLM holds no credential that grants write
authority or datastore mutation** (this is the secret-layer reinforcement of I11's "no write tools");
the **stateless MCP server holds no standing write-authority credential**; the **write-authority
credential lives only with the consolidator role** (§32).

**P4 — Secrets stay out of the observability and audit plane.** Logs, traces, metrics, dashboards,
the audit log, and `search --explain` / attribution output must never carry secret material.
Redaction is a property of the *emitting boundary*, not a downstream cleanup pass. (Which dashboards
and audit fields exist is owned by §27 / §32; this lane only forbids secrets inside them.)

**P5 — Rotation and revocation are first-class and decoupled from memory.** Every secret class must
be rotatable and revocable **without** rebuilding memory, replaying the ledger, or
branching/rolling-back beliefs. A leaked or rotated secret is an **out-of-band credential event** —
never a belief-revision or memory-rollback event. (Memory rollback/branch mechanics stay with §27 /
§32; this lane only asserts the decoupling.)

**P6 — Isolation extends to the secret layer.** Per-tenant isolation — the highest-leverage single
defense (§10, §27) — must also hold for secrets: no shared standing credential may let one tenant's
flow reach another tenant's store or keys. Secrets inherit the isolation boundary; this lane does not
redefine that boundary.

**P7 — Capability and provenance keys are the trust root.** Because compromise of the
capability-issuing and provenance-signing keys (I11, §27) silently invalidates the architectural
injection defenses, they receive the strictest handling tier, the shortest assumed blast radius, and
the most aggressive rotation posture. This lane governs *their custody*; the mechanism they secure
stays defined in I11 / §27.

**P8 — Know *that*, never *what*.** It is legitimate — and useful — for operators and tooling to
reason about a secret's **non-secret metadata**: its handle, owning component, scope, and rotation
state. It is never legitimate to materialize the **value** anywhere persistent. This lets ops reason
about secret posture without a secret ever existing as data at rest outside the secret store.

---

## 3. Do / Don't

### Storage & provenance
| ✅ Do | ❌ Don't |
|---|---|
| Keep all secret material in a dedicated secret store / platform-native secret manager | Commit secrets to the repo, bake them into images, or place them in the git source-of-truth |
| Inject secrets into a component at runtime, scoped to that component's role | Pass secrets as build args, image layers, or shared global config |
| Treat any secret found inside the memory substrate as an incident | Rely on §25 forgetting to "clean up" a secret that reached the ledger |

### Reference & propagation
| ✅ Do | ❌ Don't |
|---|---|
| Reference secrets by stable, non-secret handles everywhere config is read | Interpolate secret values into prompts, tool arguments, or memory items |
| Let only the resolving boundary see the value, for the shortest viable lifetime | Forward a secret to a downstream stage that doesn't strictly need it |
| Keep ingestion paths secret-free by construction | Let user/source content carrying a secret be ingested as ordinary memory |

### Scope & least privilege
| ✅ Do | ❌ Don't |
|---|---|
| Give the quarantine LLM only read-scoped, non-write credentials | Hand any untrusted-content processor a write or mutation credential |
| Confine the write-authority credential to the consolidator role | Let the stateless MCP server or user-facing agent hold standing write authority |
| Scope datastore credentials per component and per tenant | Share one high-privilege datastore credential across components or tenants |

### Rotation, revocation & incident posture
| ✅ Do | ❌ Don't |
|---|---|
| Design every secret to rotate without touching memory state | Couple a key rotation to a ledger replay or a memory branch/rollback |
| On suspected leak, revoke + rotate out-of-band and assume disclosure | Treat a leaked secret as a belief to be superseded or forgotten |
| Rotate capability/provenance keys most aggressively (P7) | Assume an injection defense still holds after its signing key may be exposed |

### Observability boundary
| ✅ Do | ❌ Don't |
|---|---|
| Redact at the point a log/metric/trace/audit line is emitted | Defer redaction to a scrubber that runs over already-stored telemetry |
| Surface only non-secret metadata (handle, scope, rotation state — P8) | Echo secret values into `search --explain`, dashboards, or error messages |

---

## 4. Boundaries with other lanes (explicit)

This lane deliberately **does not** define the following; each stays with its owner:

| Topic | Owned by | This lane's only relationship to it |
|---|---|---|
| Trust tiers (0–5), taint labels, capability mediation, quarantine semantics, signed-provenance mechanism | §10, §27, **I11** | References them; governs *custody* of the keys behind them (P7), never the mechanism |
| Immutable safety rails (`invariant_rails`, `reward_signal: external_only`, etc.) | §31 | Treats the reward/eval credential as a secret class (§1); does not add or alter any rail |
| Memory key schemas, stores, DDL, projections | §19, §29 | Asserts secrets never enter them (P1); defines no schema |
| Deployment topology, runbook steps, environment bring-up | §32 | States *policy* secrets must satisfy; writes **no** procedure or validation checklist |
| Observability dashboards, metrics, audit-log contents, rollback counters | §27, §32 | Forbids secrets inside them (P4); defines none of them |
| Deletion / erasure propagation mechanics | §25 | Invokes it only as the failure path for P1; defines no erasure procedure |
| Memory rollback, branching, belief revision | §27, I2, I3 | Asserts secret rotation is **decoupled** from these (P5); defines none of them |

If a future change blurs one of these boundaries, the rule is: **a secret's *custody, scope, and
lifecycle* belong here; the *thing a secret protects* belongs to that thing's lane.**

---

## 5. Open questions (tagged, for cross-lane resolution)

- **[Q-SEC-1]** Custody model for the capability/provenance signing keys in the local-first single-user
  deployment, where there is no central secret store — what is the minimum acceptable posture? (with §32)
- **[Q-SEC-2]** Whether per-source (not just per-tenant) secret scoping is warranted for ingest-side
  model credentials, or whether per-tenant scope is sufficient. (with §27 isolation)
- **[Q-SEC-3]** Canonical non-secret metadata shape for P8 ("know *that*, not *what*") so ops tooling
  can read secret posture without any schema overlap with §29. (with §29)
