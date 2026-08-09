---
type: concept
title: Mnemosyne Phase8 Provider Latency Release Gate 2026 07 03
ingested_via: put_page
ingested_at: '2026-08-09T03:54:07.166Z'
source_kind: put_page
---

# Mnemosyne Phase 8.2 provider latency release gate (2026-07-03)

Commit `bea1edb` on `/Users/admin/Mnemosyne` branch `phase3/providers-consolidation` adds source-side CPU P95 evidence gating for the self-hosted provider path.

What changed:
- `provider-check` supports `--provider-latency-samples` and `--max-provider-p95-latency-ms`.
- Embedding and reranker health checks record structured p50/p95/max latency evidence.
- Provider-check fails if embedding or reranker p95 exceeds the configured threshold.
- Production `release-audit` rejects provider evidence missing repeated p95 timing for embedding and reranker checks.

Verification:
- Focused provider/release-audit tests passed.
- Full `tests/test_cli_runtime_tools.py` passed.
- `uv run --locked ruff check` passed.
- `git diff --check` passed.
- Full `uv run --locked pytest -q` exited 0 locally.

Still open:
- Real target-host TEI/Infinity deployment evidence.
- Real cross-encoder evidence.
- Retained CPU P95 artifacts from the operator production path.
