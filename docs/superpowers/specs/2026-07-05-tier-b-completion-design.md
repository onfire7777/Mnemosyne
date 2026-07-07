# Tier-B Completion - Self-Hosted Strict Parity (historical design; superseded)

Status: approved 2026-07-05. Branch: `tier-b/completion-selfhosted` off `main @ 4c59c43`.
Superseded 2026-07-07 by the attested `capture-bc10` bundle: 29/29
deployment-soak green, release-audit `ok:true` with 0 findings, and offline
`production-evidence-verify` `ok:true` with fingerprint
`sha256:6dc117d6bb95e7a683915d432b2d2b21997133e9bfbd53624427a7317eeb2271`.

## Goal & end-state

This document records the July 5 design that originally targeted 23/24
artifacts. It is retained for lineage only. The operative result is now 24/24:
B9 completed on the no-GPU self-hosted profile through the ADR-002 amended
CPU-trained parametric adapter evidence path, without weakening
`parametric-trainer-check` or the release-audit verifier.

The final production gate is a **frozen, monolithic 29-command capture**
(`PRODUCTION_RELEASE_REQUIRED_COMMANDS`, cli.py:92-122) with an **exact
count-lock** enforced by `production-evidence-verify`. The single signed bundle
completed only after real retained B1-B10 evidence passed the unchanged gates.

## Decisions (locked)

- **B9:** ADR-002 amended path. Complete through the real CPU-trained
  parametric adapter and retained trainer/serving/rollback evidence; cloud/GPU
  remains optional scale, not required for the current attestation.
- **mTLS:** enforce `client_auth require_and_verify` on the shared
  `mcp.mnemo.local` (what the frozen manifest targets — the honest strict-parity
  posture). Mitigate blast radius by issuing + mounting client certs to every
  current client BEFORE flipping enforcement. Reversible on the branch.

## Guiding principles

1. **No fabricated evidence.** Every bundle assembled from a real live drill.
2. **Additive & reversible.** New backends/services behind selectors/flags;
   defaults unchanged so the running stack and other audit rows stay green.
3. **Zero-dependency invariant preserved** (`dependencies == ["cryptography>=42"]`)
   — S3 via stdlib urllib + manual SigV4, not boto3.
4. **Shared provider-manifest roles stay `command`** (don't break provider-check
   / other rows). Add a SEPARATE hosted-LLM manifest for the hosted-http surface.
5. Every code change gets the `verify` treatment (exercise the real flow).

## Architecture per subsystem

### B1 retrieval-ops — native probe (small engine change)
Extend `cmd_provider_check` (cli.py ~16384-16435): when lexical/graph provider
kind ∈ {postgres, native}, construct a `PostgresEngine` from the DSN and run the
real `lexical_search` + `graph_ppr` against seeded health-tenant data, emitting
`{top_id, hit_count>0}` probes (the same shape the `command` path already emits).
No ParadeDB, no Apache AGE, no image swap, no `pgdata` risk. Backend names stay
`postgres-fts` / `postgres-recursive-ppr` (already non-local, truthful). Then
produce the retrieval-ops evidence bundle: ≥3 calibrated retrieval cases (sha256
query/tenant hashes), 4 adapter probes (graph/lexical/reranker/vector, each with
6 sha256 fingerprints, hit_count>0, latency ≤1000ms), and a production calibration
set (≥20 examples). Validator: `retrieval-ops-check` + the release re-validator
`_release_retrieval_ops_evidence_findings`.

### B9 calibration-dataset.json — shares B1's calibration run
Labeled eval set scored by the live engine + bge embedder (https://tei.mnemo.local/embed,
1024-dim, CPU) → ≥20 examples, ≥1 correct, ≥1 incorrect, empirical coverage
≥0.85, false-accept ≤0.1. `CalibrationExample{confidence, correct, prediction_set_size}`.
Produced once; consumed by both `retrieval-ops-check` and `calibration-tune`.

### B4 consolidation-ops + B9 hosted-llm-manifest — one internal HTTPS role service
New `infra/providers/role-http.py`: a stdlib `http.server` wrapping the existing
`role-llm`/`role-ladder` role dispatch (byte-identical request/response), fronted
by Caddy at `roles.mnemo.local` with step-ca TLS; host added to
`MNEMOSYNE_HOSTED_CHECK_ALLOWED_INTERNAL_HOSTS`. New `Http*` role adapters in
`consolidation.py` (mirror the retrieval `HttpEmbeddingProvider` pattern, reuse
`retrieval._post_json`), `provider_kind="hosted_http"`, `strategy="hosted_http_<role>"`.
Surface `provider_kind` through `_role_pipeline_report`/`_role_provider` so a real
run records `candidate_extractor/entity_resolver/summarizer = "hosted_http"`.
Additive `"http"` choice in `load_*` loaders + argparse + provider-check role
branches (keep `command` working). Same service feeds `cmd_hosted_llm_check` →
satisfies BOTH B4's `hosted_providers`/`role_pipeline` gates AND B9's
`hosted-llm-manifest.json`. New `infra/templates/hosted-llm-manifest.production.template.json`
(`forbid_local:true`, roles → `https://roles.mnemo.local/...`, `protocol:"role-json"`).
No GPU. Keep the shared provider-manifest roles as `command`.

### B6 multimodal-ops — additive S3 object store + real media providers
Refactor `storage.py`: extract 4 byte-backend seams from
`LocalObjectStore`/`EncryptedLocalObjectStore`
(`_write_object_bytes/_read_object_bytes/_object_exists/_delete_object_bytes`),
keeping all envelope/AAD/CID-verify logic. Add `S3ObjectStore` +
`EncryptedS3ObjectStore(EncryptedLocalObjectStore)` overriding the seams to do
S3 `PutObject/GetObject/HeadObject/DeleteObject` (path-style, key `cid[:2]/cid`)
against SeaweedFS at `https://s3.mnemo.local` (creds from `seaweed-s3.json`,
region `us-east-1`), via stdlib urllib + manual AWS SigV4 (hashlib/hmac) routed
through `network_safety.safe_urlopen` with the internal-host allowlist.
`uri_prefix = "s3-object+aesgcm://sha256/"`. App-layer AES-GCM envelope UNCHANGED
→ identical `encrypted:true`/`key_provider:"command"`/crypto-shred semantics. New
`--object-store-backend {local,s3}` / `MNEMOSYNE_OBJECT_STORE_BACKEND` selector in
`load_object_store` (default `local` → zero behavior change, no payload stranding).
Two real command providers: (a) embedded-text extractor (PNG tEXt/iTXt, EXIF
ImageDescription, RIFF/WAV INFO, ID3, MP4 udta, SRT/VTT — genuine embedded bytes,
empty when none); (b) media-embedding shim that POSTs derived text to the real bge
embedder and returns the genuine 1024-dim vector. Live drill: ingest ≥3 real media
assets per modality (image/audio/video) with embedded text on a fresh tenant/branch
with `backend=s3`, let `media_extract` jobs run on a Postgres queue with
`fail_on_dead`, verify vector + derived-text retrieval, assemble the bundle
programmatically from real hashes/counts (deployment cross-checks must equal the
section counts). Validator: `multimodal-ops-check`.

### B3 mTLS — mandatory, shared host
step-ca client-cert provisioner + issue client certs (mounted to soak/operator
clients FIRST); Caddy `tls { ... client_auth { mode require_and_verify; trust_pool
file /data/step-ca-root.crt } }` on `mcp.mnemo.local`; add `--client-cert/--client-key`
to `mcp-http-soak` (urllib `ssl.load_cert_chain`) and `mcp-streamable-http-soak`
(httpx `cert=(cert,key)`); re-run both soaks presenting the cert; rewrite
`mcp-ops-bundle.json` `tls.client_certificate_required:true`. Validate WITH
`--require-client-cert`. The offline clamp `_release_mcp_ops_evidence_findings`
(cli.py:11117/11203) requires this unconditionally.

### B8 oncall — self-hosted ntfy route
Pinned ntfy container (tmpfs-hardened) + replace vmalert `-notifier.blackhole`
with a real Alertmanager/ntfy webhook route; Caddy `ntfy.mnemo.local`. Fire a
synthetic alert; prove delivery via a self-hosted topic subscriber
(`curl .../<topic>/json` — no human/pager needed). Set
`ops-dashboard-bundle.json` `alerts.oncall_route_present:true` + delivery evidence.
Validator: `ops-dashboard-check` + `_release_ops_dashboard_evidence_findings`.

### B10 row-10 + closeout
Produce `row-10-full-suite-evidence.json` = redacted full live-Postgres pytest
suite output (`MNEMOSYNE_POSTGRES_DSN=<prod> python -m pytest -q`), retained as a
custody input artifact of `belief-revision-check`. Run the full custody validation
script across all lanes to prove every non-parametric artifact passes. Update
ADR-002 + the strict-audit doc: B1-B10 Done via the retained monolithic
production bundle; B9 no longer remains narrowed to a pending GPU item.

## Sequencing (dependency-ordered, low-risk first)

1. Branch + manifest posture (done: branch created).
2. B1 native probe + B9 calibration-dataset (shared calibration run).
3. B4 + B9 hosted-llm-manifest (shared `roles.mnemo.local` service + engine adapters).
4. B6 S3 object store + media providers + drill.
5. B3 mTLS.
6. B8 oncall.
7. row-10 + ADR-002/strict-audit closeout + full validation sweep.

Each phase: code + tests green → deploy additively → live drill → assemble bundle
→ validator `ok=true, 0 findings` → commit. `verify` each code change.

## Risk & mitigation

- mTLS lockout → issue+mount client certs before flipping `require_and_verify`;
  reversible on branch.
- Hand-rolled SigV4 → signing unit test against live SeaweedFS before the drill;
  path-style + `us-east-1`.
- Role-pipeline dual shape (engine `roles` list vs flat bundle keys) → update the
  fixtures asserting `model_backed_roles`/`provider_type` in lockstep.
- Monolithic gate -> do NOT fake a signed 29-command bundle; close B1-B10 only
  via the retained wrapper-captured evidence path, documented.

## Scope boundary (NOT in scope)

No cloud GPU; no `parametric-trainer-bundle.json`; no Postgres re-platform
(ParadeDB/AGE); no object-store cutover of existing payloads; no flipping the
shared provider-manifest roles to http; no boto3 dependency.
