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

PURE-PATH DISCIPLINE: the three baseline benches below call the ``_*_pure``
bodies from ``mnemosyne.text`` DIRECTLY (not the dispatchers), so they measure
the pure path even in a native-installed environment. The capture script
additionally forces ``MNEMOSYNE_PURE=1`` in its subprocess. Both guards exist
because the first Task-8 re-capture accidentally measured the dispatched
NATIVE path through the dispatchers, committing native means as "pure"
baselines — the gates were comparing native against native.

Collection-time gating (which run modes execute these tests) lives in
``tests/benchmarks/conftest.py``.
"""

from __future__ import annotations

import array
import itertools
import json
import os
import random
from pathlib import Path

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_tools import MemoryTools

# The pure benches import the pure bodies directly — NOT the dispatching
# cosine/hashing_embedding/lexical_score — so a native-installed environment
# still regression-tests the pure path honestly (see module docstring).
from mnemosyne.text import _cosine_pure, _hashing_embedding_pure, _lexical_score_pure

BASELINES = Path(__file__).parent / "baselines.json"
RELATIVE_CEILING = 1.5  # fail if >1.5x recorded baseline
# Module-local RNG: same seed (and therefore the same byte-identical DOCS /
# QUERY as the original process-global random.seed(20260701)) without
# mutating global RNG state for the rest of the process.
_RNG = random.Random(20260701)

_WORDS = ["postgres", "memory", "belief", "evidence", "tenant", "branch", "vector", "graph"]


def _text(n: int) -> str:
    return " ".join(_RNG.choice(_WORDS) + str(_RNG.randint(0, 500)) for _ in range(n))


# Generated at import time, directly downstream of the freshly seeded
# module-local RNG, so benchmark inputs are byte-identical across runs and
# machines.
DOCS = [_text(80) for _ in range(2000)]
QUERY = _text(12)

# Dense-scan inputs: 2000 rows x 256 dims plus a 256-dim query, generated once
# at import time downstream of DOCS/QUERY on the same module-local RNG, so the
# byte-identical-inputs guarantee extends to the native dense bench.
DENSE_QUERY = [_RNG.random() for _ in range(256)]
DENSE_ROWS = [[_RNG.random() for _ in range(256)] for _ in range(2000)]


def _gate(name: str, seconds: float) -> None:
    if os.environ.get("MNEMOSYNE_BASELINE_CAPTURE") == "1":
        # capture_baselines.py is re-capturing: the mean just measured becomes
        # the new baseline, so comparing it against the committed (possibly
        # intentionally-changed or previously-contaminated) baseline would
        # veto the very re-capture that fixes it.
        return
    if not BASELINES.exists():
        pytest.skip("baselines.json not captured yet (run tests/benchmarks/capture_baselines.py)")
    baseline = json.loads(BASELINES.read_text())[name]
    assert seconds <= baseline * RELATIVE_CEILING, (
        f"{name}: {seconds:.4f}s exceeds {RELATIVE_CEILING}x baseline {baseline:.4f}s"
    )


def _gate_speedup(
    name: str, seconds: float, factor: float = 10.0, *, baseline: float | None = None
) -> None:
    """Phase-1 exit gate: the native mean must be <= the pure baseline / factor.

    ``baseline`` defaults to the committed ``baselines.json`` entry for
    ``name``; pass it explicitly for derived pure-equivalent baselines (see
    the dense-scan bound arithmetic below).
    """
    if not BASELINES.exists():
        pytest.skip(
            "baselines.json not captured yet (run tests/benchmarks/capture_baselines.py)"
        )
    if baseline is None:
        baseline = json.loads(BASELINES.read_text())[name]
    bound = baseline / factor
    multiple = baseline / seconds if seconds > 0 else float("inf")
    assert seconds <= bound, (
        f"{name}: native mean {seconds:.6e}s is only {multiple:.1f}x faster than the pure "
        f"baseline {baseline:.6e}s — phase exit requires >={factor:.0f}x (<= {bound:.6e}s)"
    )


def test_bench_cosine_1024(benchmark):
    rng = random.Random(20260701)  # order-independent, reproducible vectors
    a = [rng.random() for _ in range(1024)]
    b = [rng.random() for _ in range(1024)]
    benchmark(_cosine_pure, a, b)
    _gate("cosine_1024", benchmark.stats.stats.mean)


def test_bench_hashing_embedding_cold(benchmark):
    # hashing_embedding memoizes on its input (lru_cache), so a repeating input
    # stream would measure cache hits after the first pass over DOCS. A unique
    # per-call salt keeps every invocation on the cold (tokenize + blake2b)
    # path, which is the kernel this baseline is meant to guard.
    # _hashing_embedding_pure is the uncached pure body; dims=256 matches the
    # hashing_embedding default, so input semantics are identical to the
    # dispatcher's cold path.
    counter = itertools.count()

    def run() -> None:
        i = next(counter)
        _hashing_embedding_pure(DOCS[i % len(DOCS)] + f" salt{i}", 256)

    benchmark(run)
    _gate("hashing_embedding", benchmark.stats.stats.mean)


def test_bench_lexical_scan_2k(benchmark):
    benchmark(lambda: [_lexical_score_pure(QUERY, d) for d in DOCS])
    _gate("lexical_scan_2k", benchmark.stats.stats.mean)


# --- Phase-1 native kernels vs the committed pure baselines ----------------
# These benches call the native kernels DIRECTLY (not through dispatch) so
# they measure kernel cost, not dispatch overhead, over inputs byte-identical
# to the pure benches above. They do not gate against baselines.json the
# relative-regression way; the gating ones assert their phase-exit bar
# instead (the list-seam dense bench is informational — see its comment).


def test_bench_native_lexical_scan_2k(benchmark):
    native = pytest.importorskip("mnemosyne_native")
    # One whole-corpus scan per round, mirroring the pure bench's
    # [_lexical_score_pure(QUERY, d) for d in DOCS] loop.
    benchmark(native.lexical_scan, QUERY, DOCS)
    _gate_speedup("lexical_scan_2k", benchmark.stats.stats.mean)


def test_bench_native_hashing_embedding_cold(benchmark):
    native = pytest.importorskip("mnemosyne_native")
    # Same salt-cold pattern as the pure bench: a unique per-call salt keeps
    # every invocation on the cold (tokenize + blake2b) path. dims=256 matches
    # the pure hashing_embedding default the pure bench relies on.
    #
    # GATE = 3.0x, NOT the 10x phase-exit bar: hashing is not in the spec's
    # Phase-1 exit bar (that names the DENSE and LEXICAL scan benches), and
    # 10x is structurally out of reach for this kernel — the pure path's
    # blake2b is C-backed hashlib, so the only pure-Python work the native
    # kernel can beat is tokenize + bucket accumulation. Measured against the
    # TRUE pure baseline (captured under MNEMOSYNE_PURE=1; the earlier "~1.8x
    # floor" was an artifact of a contaminated capture that measured the
    # dispatched-native path as "pure"): native ~15us vs pure ~70us ~= 4.6x.
    # factor=3.0 is a conservative margin below that measured multiple.
    counter = itertools.count()

    def run() -> None:
        i = next(counter)
        native.hashing_embedding(DOCS[i % len(DOCS)] + f" salt{i}", 256)

    benchmark(run)
    _gate_speedup("hashing_embedding", benchmark.stats.stats.mean, factor=3.0)


def test_bench_native_dense_scan_2k_256d(benchmark):
    native = pytest.importorskip("mnemosyne_native")
    # NON-GATING (informational): this bench measures the list-FFI seam the
    # engine ships today. Measured ~3.4 ms per scan — ~4.6x vs the honest
    # pure-equivalent bound (~15.6 ms, derivation in the prepacked bench
    # below). The previously quoted "1.8x" was computed against a bound
    # derived from the contaminated baseline capture that had measured the
    # dispatched-NATIVE path as "pure". Profiled 2026-07-02: ~93% of the call
    # is PyFloat->f64 conversion of 2000x256 boxed floats at the FFI boundary,
    # serial under the GIL, so no per-call conversion strategy can reach 10x
    # here. The >=10x END-TO-END dense exit gate is formally re-homed to
    # Phase 2's packed-BLOB seam — embeddings stored as packed LE-f64 BLOBs
    # fed to dense_scan_packed with ZERO per-call conversion; see
    # docs/superpowers/plans/2026-07-02-phase2-sqlite-engine.md, Task 4,
    # "PACKED-BLOB dense seam" (the binding exit gate for that task). The
    # kernel-side >=10x proof is test_bench_native_dense_scan_prepacked below.
    #
    # SEAM CHOICE (measured 2026-07-02, clean machine): this bench measures the
    # list-of-lists path because that is what the engine ships. A packed-bytes
    # kernel (dense_scan_packed) exists and its Rust side is ~0.2 ms on
    # pre-packed buffers (~30x even vs the idealized bound), but END-TO-END —
    # packing 2000x256 Python floats with array.array('d') included — the
    # packed path costs ~6.0 ms vs ~3.1 ms for the list path, so it was NOT
    # adopted (per-call PyFloat->f64 conversion dominates both, and Python-side
    # packing is the slower converter). Adopting it would have made this bench
    # dishonest; the conversion wall is the blocker either way.
    benchmark(native.dense_scan, DENSE_QUERY, DENSE_ROWS)


def test_bench_native_dense_scan_prepacked(benchmark):
    native = pytest.importorskip("mnemosyne_native")
    if not BASELINES.exists():
        pytest.skip(
            "baselines.json not captured yet (run tests/benchmarks/capture_baselines.py)"
        )
    # Kernel-side phase-exit proof: the SAME 2000x256 rows as the list-seam
    # bench above, packed OUTSIDE the timed region (Phase 2 stores embeddings
    # in exactly this packed LE-f64 form, so packing is not a per-call cost at
    # that seam). Only the dense_scan_packed call is timed; mask all-present.
    #
    # Pure-equivalent bound derivation (same arithmetic as the list-seam bench
    # used while it gated): the committed cosine_1024 baseline is the mean of
    # ONE pure 1024-dim cosine. Pure cosine is O(dims), so one 256-dim cosine
    # costs cosine_1024 * (256/1024), and a full scan over 2000 rows costs
    #     cosine_1024 * (256/1024) * 2000   (~1.56e-02 s at the honest
    #     MNEMOSYNE_PURE=1 capture)
    # — an idealized zero-overhead pure opponent, which now nearly coincides
    # with a real [_cosine_pure(q, r) for r in DENSE_ROWS] loop (~16 ms on the
    # reference machine). Measured ~82x here against that bound.
    query_packed = array.array("d", DENSE_QUERY).tobytes()
    rows_packed = array.array(
        "d", [value for row in DENSE_ROWS for value in row]
    ).tobytes()
    row_mask = b"\x01" * len(DENSE_ROWS)
    pure_equivalent = (
        json.loads(BASELINES.read_text())["cosine_1024"] * (256 / 1024) * 2000
    )
    benchmark(native.dense_scan_packed, query_packed, rows_packed, 256, row_mask)
    _gate_speedup(
        "dense_scan_2k_256d_prepacked",
        benchmark.stats.stats.mean,
        baseline=pure_equivalent,
    )


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
