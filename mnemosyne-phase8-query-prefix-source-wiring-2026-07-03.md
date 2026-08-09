---
type: concept
title: Mnemosyne Phase8 Query Prefix Source Wiring 2026 07 03
ingested_via: put_page
ingested_at: '2026-08-09T03:54:08.882Z'
source_kind: put_page
---

# Mnemosyne Phase 8.2 query-prefix source wiring (2026-07-03)

Commit `d56093cb90652a103ac94dace471f45dcbf5a613` on `/Users/admin/Mnemosyne` branch `phase3/providers-consolidation` closes the source-side query-prefix portion of Phase 8.2 without claiming deployment evidence.

What changed:
- `HttpEmbeddingProvider.embed()` still sends document text unchanged.
- `embed_query()` routes query text through provider-specific query embedding when available.
- HTTP embedding/rerank query payloads apply `query:` without double-prefixing already-prefixed text.
- Local, SQLite, and Postgres dense query vectors plus MMR query vectors use `embed_query()`.
- Local similarity reranking uses query-aware embedding for the query and plain embedding for documents.
- `provider-check` embedding probe uses the query-aware path.

Verification:
- `uv run --locked pytest tests/test_parity_retrieval.py -q` passed.
- Targeted retrieval/runtime/shared-engine slice passed.
- `uv run --locked ruff check` passed.
- `git diff --check` passed.
- Full `uv run --locked pytest -q` exited 0 locally.

Still open:
- TEI/Infinity deployment and real cross-encoder evidence.
- CPU P95 gate on target host.
- Tier-B operator production bundles and release audit evidence.
