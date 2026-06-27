from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_living_latency_docs_do_not_claim_local_adapter_seam_is_missing() -> None:
    living_docs = [
        REPO / "eval" / "latency" / "README.md",
        REPO / "eval" / "latency" / "bench.py",
    ]
    stale_claims = [
        "ignores the HTTP retrieval adapters today",
        "ignores HTTP adapters today",
        "passes no `adapters=`",
        "has no embedding seam",
        "hardwire `hashing_embedding`",
        "hardwires\n``hashing_embedding``",
    ]

    for path in living_docs:
        text = path.read_text(encoding="utf-8")
        for claim in stale_claims:
            assert claim not in text, f"{path} still contains stale latency seam claim: {claim!r}"

    readme = (REPO / "eval" / "latency" / "README.md").read_text(encoding="utf-8")
    bench = (REPO / "eval" / "latency" / "bench.py").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())
    normalized_bench = " ".join(bench.split())
    assert "local backend now receives the configured retrieval adapters" in normalized_readme
    assert "CLI now passes the configured retrieval adapters into ``LocalMemoryEngine``" in normalized_bench
