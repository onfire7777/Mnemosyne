"""A6 harness: kernel + fast-path baselines with relative-regression gating.

CI gates RELATIVE regression vs baselines.json (shared runners are noisy):
a benchmark fails when its mean exceeds 1.5x the recorded baseline. The
absolute §22.5 budgets run only under MNEMOSYNE_BENCH_ABSOLUTE=1 (nightly,
reference Mac). Spec §4.6.

Machine-noise caveat: ``baselines.json`` is machine-specific BY DESIGN — it is
the reference capture for relative-regression gating on this machine (spec
§4.6). Do not hand-edit it. To re-capture (e.g. after moving to a new
reference machine or landing an intentional kernel change), run the Step-4
capture script:

    uv run --locked python tests/benchmarks/capture_baselines.py

then commit the regenerated ``tests/benchmarks/baselines.json``. A freshly
captured baseline trivially passes its own 1.5x gate; Phase 1 kernels must
show their delta against these committed values.

Collection-time gating (which run modes execute these tests) lives in
``tests/benchmarks/conftest.py``.
"""

from __future__ import annotations

import itertools
import json
import os
import random
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.text import cosine, hashing_embedding, lexical_score

BASELINES = Path(__file__).parent / "baselines.json"
RELATIVE_CEILING = 1.5  # fail if >1.5x recorded baseline
random.seed(20260701)

_WORDS = ["postgres", "memory", "belief", "evidence", "tenant", "branch", "vector", "graph"]


def _text(n: int) -> str:
    return " ".join(random.choice(_WORDS) + str(random.randint(0, 500)) for _ in range(n))


# Generated at import time, directly downstream of the module-level seed, so
# benchmark inputs are byte-identical across runs and machines.
DOCS = [_text(80) for _ in range(2000)]
QUERY = _text(12)


def _gate(name: str, seconds: float) -> None:
    if not BASELINES.exists():
        pytest.skip("baselines.json not captured yet (run tests/benchmarks/capture_baselines.py)")
    baseline = json.loads(BASELINES.read_text())[name]
    assert seconds <= baseline * RELATIVE_CEILING, (
        f"{name}: {seconds:.4f}s exceeds {RELATIVE_CEILING}x baseline {baseline:.4f}s"
    )


def test_bench_cosine_1024(benchmark):
    rng = random.Random(20260701)  # order-independent, reproducible vectors
    a = [rng.random() for _ in range(1024)]
    b = [rng.random() for _ in range(1024)]
    benchmark(cosine, a, b)
    _gate("cosine_1024", benchmark.stats.stats.mean)


def test_bench_hashing_embedding_cold(benchmark):
    # hashing_embedding memoizes on its input (lru_cache), so a repeating input
    # stream would measure cache hits after the first pass over DOCS. A unique
    # per-call salt keeps every invocation on the cold (tokenize + blake2b)
    # path, which is the kernel this baseline is meant to guard.
    counter = itertools.count()

    def run() -> None:
        i = next(counter)
        hashing_embedding(DOCS[i % len(DOCS)] + f" salt{i}")

    benchmark(run)
    _gate("hashing_embedding", benchmark.stats.stats.mean)


def test_bench_lexical_scan_2k(benchmark):
    benchmark(lambda: [lexical_score(QUERY, d) for d in DOCS])
    _gate("lexical_scan_2k", benchmark.stats.stats.mean)


def _seed_one(tools: MemoryTools, content: str) -> None:
    # Canonical public capture path, same shape as the minimal capture call in
    # tests/test_engine_contract.py (test_hybrid_retrieval_returns_provenance...).
    tools.capture(
        tenant_id="bench-tenant",
        user_id="bench-user",
        actor="user",
        source_type="chat",
        content=content,
        trust_tier=0,
    )


def test_fast_path_retrieve_absolute_budget():
    if os.environ.get("MNEMOSYNE_BENCH_ABSOLUTE") != "1":
        pytest.skip("absolute §22.5 budget runs on the reference machine only")
    import time

    engine = LocalMemoryEngine()
    tools = MemoryTools(engine)
    # Seed 1000 items through the public capture path.
    for i in range(1000):
        _seed_one(tools, f"doc {i}: " + _text(30))
    start = time.perf_counter()
    for _ in range(20):
        engine.retrieve(QUERY, tenant_id="bench-tenant")
    p_mean_ms = (time.perf_counter() - start) / 20 * 1000
    assert p_mean_ms <= 400, f"fast path {p_mean_ms:.0f} ms exceeds §22.5 budget"
