# Mnemosyne — Self-Hosted-First Production Architecture

**Status:** Proposed subordinate architecture for a self-hosted production
profile. Local-first / self-hosted is the preferred operating target for rows it
can honestly satisfy; cloud/GPU remains the required values-only extension for
capabilities such as B9/FR-21 that cannot be evidenced on a no-GPU host.
**Audience:** operators standing up Tier-B production evidence, and the Codex/GSD loop.
**Authority:** the blueprint (`docs/blueprint/`) and live repo evidence win over this doc where they
differ. This doc **extends** the already-wired `infra/` provider stack; it does not replace it.
**Constraint envelope:** local-first, **no GPU** for the self-hosted baseline,
runs comfortably on a ~16 GB Mac, must preserve every Tier-B gate, the seven
§31 rails, and the six §16 SLOs — with **no quality degradation** versus what a
top engineer would choose, and **no gate weakened**. The no-GPU envelope is not
a license to mark B9 or strict 100% complete without real B9 evidence.

---

## 1. Principle: extend reality, upgrade only where it raises quality

The repo already ships a real self-hosted provider stack — `infra/docker-compose.providers.yml`
(Keycloak 25.0, HashiCorp Vault 1.17, c2patool) with setup/validate scripts, native-Postgres
retrieval, and model-agnostic `HttpEmbeddingProvider` / `HttpReranker` boundaries. This architecture
**completes and hardens that stack** rather than introducing a parallel one. Every choice below was
adversarially audited for quality; we change a component **only** when the change *raises* quality
inside the envelope, and we **keep** the SLO-proven core untouched.

**Two profiles, one codebase, values only.** The gates key on provider *kind* and
host/CA *locality*, never on vendor identity. So `self-hosted` (preferred
baseline) and `cloud` (B9-capable extension) share the identical
`provider-manifest.production.template.json` and the same checks; they differ
only in the *values* bound to env references. `forbid_local: true` is retained
in **both** — it is a property of the schema, not the profile. Profiles live
outside the repo (`infra/profiles/self-hosted.env`, `infra/profiles/cloud.env`),
filled in the Tier-B custody packet.

---

## 2. Component architecture (reconciled, best-in-class in-envelope)

| Capability | Choice | Why it is best-in-class here | Status vs repo |
|---|---|---|---|
| **Retrieval engine (B1)** | **Native Postgres 16**: FTS (`to_tsvector`/`plainto_tsquery`) + **pgvector HNSW** + **`postgres-recursive-ppr`** | Unified store, SLO-proven (recall 0.977 / nDCG 0.983). A specialist vector DB (Qdrant/Weaviate/Vespa) would **fracture** the single source of truth and lose transactional consistency with the evidence ledger. | **KEEP** (deployed) |
| **Lexical (BM25) — only if gate demands** | **ParadeDB `pg_search`** (Tantivy BM25), *in the same Postgres* | If the strict audit insists on a true BM25 backend distinct from native FTS, `pg_search` is the **minimal** add — it stays inside Postgres (no fracture). Name it `paradedb-bm25` (non-local). | **Conditional** add |
| **Graph + PPR (B1)** | **Native recursive-PPR** (`postgres-recursive-ppr`); **igraph/scipy sidecar** only as an optional command-backed accelerator | Native recursive-PPR remains the quality path. Do not replace it with Apache AGE as the algorithm source. If the strict Tier-B row still requires an AGE deployment as production evidence, satisfy that as an evidence-compatible sidecar or change the strict audit through an explicit ADR before claiming parity. | **KEEP** native PPR; AGE is evidence-only if required |
| **Dense embeddings (B1/B6)** | **`snowflake-arctic-embed-l-v2.0`** (568M, native **1024-dim**, 8192-ctx RoPE, Matryoshka→256) via **TEI/Infinity (CPU)** → `HttpEmbeddingProvider` | SOTA among sub-1B CPU models (~+3.5pt nDCG vs `bge-large`, and no silent 512-token truncation on long memory chunks). Native 1024-dim = exact `pgvector(1024)` match. **Wire `query:` prefix on queries only.** | **Upgrade** (model swap, no code) |
| **Cross-encoder reranker (B1)** | **Real cross-encoder** via `HttpReranker` — **bake off `bge-reranker-v2-m3` vs `gte-reranker-modernbert-base`** on your gold set | A true cross-encoder is required for both quality and the non-local reranker probe. Pick the winner on *your* data, not a benchmark. | **Config** (model-agnostic boundary exists) |
| **Consolidation role-LLM (B4)** | **Default: `Qwen3-4B` (thinking), Q4_K_M, llama.cpp (CPU)**. **No-compromise option: command-backed frontier model** (`claude`/OpenAI-compatible adapter) | The 11-role "society of roles" drives belief/calibration/lesson quality — reasoning matters. Qwen3-4B is a generation ahead of Qwen2.5-3B and CPU-runnable; the command-backed frontier is the quality ceiling (gate-legal as a non-local `command` provider; §27 sanitizes spans and the quarantine LLM has no write tools). | **Upgrade** + documented lever |
| **Identity / OIDC (B2)** | **Keycloak 25.0** (already wired: `OidcJwtVerifier`, `idp-jwks-live-check`, FR-7/9) | Already integrated and live-validated; switching to Dex would *lose* wired capability for a marginal RAM saving. | **KEEP** (deployed) |
| **Secrets / KMS (B2/B7)** | **HashiCorp Vault 1.17 transit** (or **OpenBao** drop-in) via `CommandKeyManager` | Real transit wrap/unwrap/rotate/shred already wired; non-local KMS kind. OpenBao is an Apache-licensed drop-in if licensing matters. | **KEEP** (deployed) |
| **TLS (B2)** | **smallstep `step-ca`** ACME behind the proxy | Issues a real chain (order-id + serial + chain hashes), **not self-signed** → passes the TLS gate. Caddy's built-in `internal` CA is self-signed and **must not** be used for the gate. | **Add** |
| **Object store (B6)** | **SeaweedFS** (native AES256-GCM) or MinIO; **mandatory** `MNEMOSYNE_OBJECT_STORE_ENCRYPTION=aesgcm` with Vault-transit key provider | Non-local object store; SeaweedFS encrypts server-side without a separate KMS sidecar. At-rest encryption is a **security must-do**, not optional. | **Add** (+ default fix) |
| **Observability (B8)** | **VictoriaMetrics + vmalert + Grafana** | Real hosted dashboard URL (`mode=hosted_url`) with tripwires + freshness + auth; ~⅓ the RAM of Prometheus. | **Add** |
| **Reverse proxy / ingress** | **Caddy** — the **sole** published port; ACME certs from step-ca | Lightest auto-HTTPS; one ingress on a non-loopback hostname → satisfies the HTTPS-non-loopback gate for all services. | **Add** |

**MCP runtime (B3):** the existing hosted MCP HTTP + StreamableHTTP surfaces behind Caddy/step-ca TLS,
with **mandatory signed sessions** (see §4).

---

## 3. Per-row mapping B1–B10 and the no-GPU resolution

| Row | Satisfied by | Gate cleared because… |
|---|---|---|
| B1 retrieval | native Postgres (FTS+HNSW+recursive-PPR) + arctic embeddings + cross-encoder | non-local backend *names* + `postgres`/`http` providers over non-loopback TLS; real cross-encoder probe |
| B2 tenant/auth/TLS | Keycloak + Vault + step-ca | HTTPS non-loopback JWKS; non-self-signed CA chain; non-local KMS |
| B3 CLI/MCP runtime | hosted MCP behind Caddy TLS, signed sessions | HTTPS non-loopback soaks with verified sessions |
| B4 consolidation | Qwen3-4B / frontier command adapter | non-local `command`/`http` role providers |
| B5 provenance | c2patool + real trust roots | fail-closed C2PA verification (not the stub) |
| B6 multimodal | SeaweedFS/MinIO + media extractor/embedder | non-local object store + media commands |
| B7 privacy/erasure | Vault transit crypto-shred + residency policy | non-local KMS lifecycle; real erasure proof |
| B8 observability | Grafana (`mode=hosted_url`) | retained non-loopback dashboard URL + tripwires |
| **B9 parametric** | **Not satisfiable on the no-GPU self-hosted baseline** | Current strict parity still requires real B9 operator evidence before 100%. The self-hosted profile must leave B9 Partial unless the cloud/GPU values-only profile supplies trainer evidence or the strict audit is changed by an explicit ADR. |
| B10 live parity | the whole self-hosted stack under one manifest | all non-local providers + belief-revision over real infra |

**Net:** the self-hosted baseline can target **B1–B8 + B10** with real evidence,
no GPU, and no weakened gate. It does **not** by itself reach strict 100%.
Current strict parity still requires B9 evidence through a cloud/GPU values-only
profile or a separately accepted audit decision.

---

## 4. Security architecture (hardened; no gate weakened)

The repo's cryptographic *primitives* are strong (per-object AES-GCM + crypto-shred, SSRF fetch with
DNS-pinning, RS/ES-only OIDC verifier with JWKS rotation, FORCE RLS, the seven §31 rails, C2PA
byte-binding). The work is closing **intent-vs-enforcement** gaps and shipping **fail-closed defaults**.

### 4.1 Non-negotiable fixes (must ship before self-hosted profile capture)

1. **Fail-closed runtime defaults (production profile):** MCP `require_session=True` (refuse boot if
   unset); `tenant_id`/`role`/`source_trust_tier` derive **only** from the verified session claim,
   never a tool argument; **mandatory** object-store AES-GCM (refuse start if `none` while S2+
   writable); **sealed** Vault/OpenBao (no dev-mode, no committed root token); **MFA-gated** privilege
   elevation (operator/tier-0 rules require `acr/amr` + claim matcher); `ProvenanceTrustPolicy`
   **fail-closed**.
2. **Postgres role separation under RLS:** ship `mnemosyne_app` (NOSUPERUSER, NOBYPASSRLS, no
   DELETE/TRUNCATE), a separate `mnemosyne_consolidator` (sole write/destructive authority), and
   SELECT-only eval roles; an ops-check that live-probes `rolsuper`/`rolbypassrls` and fails if true.
3. **Gate integrity → measure, don't attest:** for Phase 8 only, extend
   high-value `*-ops-check` gates where a real capture attempt exposes an
   attestation-only weakness. The target behavior is live re-execution against
   infra (auth-ops forges `alg=none`/wrong-aud/replayed-kid tokens against the
   live verifier; privacy-ops does a real `forget` then re-reads to confirm 404
   + Vault key gone; provider-check round-trips the live endpoint) and evidence
   bundles signed by a collector-only key the gate verifies. This is not a
   reason to add generic gates ahead of the active Tier-B capture path.

### 4.2 Layered defense-in-depth

- **Edge/network:** Caddy the *sole* published port (bound to LAN/VPN iface, never `0.0.0.0`/WAN); all
  other services `internal:true`; step-ca **mTLS between services** (verify expected SAN); single SSRF
  **egress chokepoint** routing *all* outbound calls through `network_safety.validate_fetch_url` +
  default-deny allowlist (drop metadata/link-local/RFC1918); a lint that fails if any raw HTTP client
  bypasses the guard.
- **Host/container:** policy-as-code CI gate (fail on `docker.sock` mount, `privileged`, unpinned
  image, secret-in-env, missing `read_only`/`cap_drop:[ALL]`/non-root/`no-new-privileges`/limits);
  **digest-pin every image**; Trivy/Grype/Syft + gitleaks required gates; cosign verify-at-deploy.
- **Privilege separation:** split Mnemosyne into an edge API/MCP container (no secrets/data) and a back
  consolidator (sole KMS + write authority); no container holds edge+data+secrets at once.
- **Data:** mandatory AES-GCM at rest; **per-tenant-scoped** crypto-shred keys (not a wildcard delete);
  LUKS for PGDATA/Vault storage; encrypted PITR backups with **scheduled verified restores**.
- **Monitoring:** tamper-evident **hash-chained append-only audit log** (Vault-HMAC keyed, BEFORE
  UPDATE/DELETE trigger, INSERT-only grant) + pgaudit + an out-of-band WORM copy the app role cannot
  rewrite; log every write and every auth decision.

### 4.3 Accepted residual risks (mitigated structurally, not eliminated)

In-band abuse of *legitimate* tool authority via poisoned memory (mitigated by R6 single-choke-point +
credential-less quarantine worker + consolidator-only writes); single-tenant deployments gain no
per-tenant-isolation benefit (mitigated by R6 + per-source trust tiers); attestation residue after
live-probing (mitigated by collector-signed bundles); rootless-Docker hosts where egress-deny can't be
enforced (**gate production on a working host firewall**).

---

## 5. Resource footprint (no-GPU, ~16 GB Mac)

Steady-state always-on: native Postgres (~1–3 GB incl. HNSW) + TEI embeddings+reranker (~3 GB) +
Keycloak (~0.4 GB) + Vault + step-ca + Caddy + SeaweedFS + VictoriaMetrics + Grafana (~1 GB combined).
Role-LLM adds ~2.5 GB if local (`Qwen3-4B`) or ~0 GB if command-backed frontier. **Total ≈ 6–9 GB**,
with capture/transcode workers run **on-demand** (`--profile capture`) to keep idle low. Comfortable on
16 GB.

---

## 6. No-compromise levers (where the envelope itself is the only cap)

| Where | What the no-GPU/local envelope caps | Lever (optional `cloud` profile) |
|---|---|---|
| Embedding quality | LLM-scale embedders (Qwen3-Embedding-4B/8B, ~+8–12 retrieval pts) need GPU and emit 2560/4096-dim (pgvector reindex) | cloud/GPU embedding endpoint |
| Consolidation reasoning | a local 4B is good, not frontier | command-backed frontier model (already supported) |
| B9 parametric tier | LoRA / test-time-training needs a GPU | cloud/GPU trainer endpoint flips B9 from DEFERRED to evidenced |

Every lever is a **values-only profile swap** — no code change, no gate weakened.

---

## 7. What changes in the repo — and what does not

**Additive (new):** `infra/docker-compose.prod.yml` (hardened production stack extending the providers
compose), `infra/profiles/{self-hosted,cloud}.env`, step-ca/SeaweedFS/Grafana service configs, the
Postgres role-separation DDL, the policy-as-code CI gate, the audit-log migration, and the live-probe
extensions to the high-value `*-ops-check` gates.

**Unchanged (do not touch):** the gate locality semantics and `forbid_local`;
the seven §31 rails; the native-Postgres retrieval engine; the SLO-proven
calibration path; the strict-audit ledger (rows flip only on real evidence).
Current B9 remains a production-evidence requirement for strict 100% unless a
future accepted ADR changes the audit. **No gate is weakened anywhere.**

---

## 8. Open decisions for the operator

1. **Consolidation default:** local `Qwen3-4B` (fully local, lower reasoning) **vs** command-backed
   frontier (higher quality, some egress). Default = local for purity; switch via one env value.
2. **Lexical backend:** native FTS (default) **vs** add ParadeDB `pg_search` — decide once the strict
   audit confirms whether native FTS counts as the non-local lexical backend.
3. **Object store:** SeaweedFS (native SSE) vs MinIO (broader S3 fidelity, needs KES for SSE).
