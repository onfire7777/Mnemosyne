"""Dispatch contract: native active by default when installed; MNEMOSYNE_PURE=1
forces pure; results byte-identical either way (spot-checked here; the full
guarantee is the parity suite run in both modes, Task 6 Step 4)."""
from __future__ import annotations

import os
import struct  # noqa: F401 - used inside the subprocess CODE strings
import subprocess
import sys
from collections import Counter

import pytest

native = pytest.importorskip("mnemosyne_native")


def _run(code: str, pure: bool) -> str:
    env = dict(os.environ)
    if pure:
        env["MNEMOSYNE_PURE"] = "1"
    else:
        env.pop("MNEMOSYNE_PURE", None)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    ).stdout.strip()


CODE = (
    "import struct; from mnemosyne import text;"
    "v = text.hashing_embedding('alpha beta x1.2.3', 256);"
    "s = text.lexical_score('alpha beta', 'alpha gamma beta beta');"
    "print(text.NATIVE is not None, struct.pack('<d', s).hex(), ''.join(struct.pack('<d', x).hex() for x in v[:8]))"
)


def test_native_active_by_default_and_pure_forced():
    active = _run(CODE, pure=False).split()
    forced = _run(CODE, pure=True).split()
    assert active[0] == "True" and forced[0] == "False"
    assert active[1:] == forced[1:]  # byte-identical outputs


MMR_CODE = (
    "from mnemosyne import text;"
    "from mnemosyne.algorithms import mmr_select;"
    "from mnemosyne.models import Hit;"
    "hits = [Hit(id=str(i), kind='evidence', tenant_id='t', branch='main',"
    " text=f'alpha beta gamma {i} delta-{i % 3}', score=i / 7.0, channel='dense')"
    " for i in range(6)];"
    "q = text.hashing_embedding('alpha beta', 64);"
    "sel = mmr_select(hits, 3, query_vec=q,"
    " embed_hit=lambda h: text.hashing_embedding(h.text, 64), mmr_lambda=0.7);"
    "print(text.NATIVE is not None, ','.join(h.id for h in sel))"
)


def test_mmr_select_identical_selection_both_modes():
    active = _run(MMR_CODE, pure=False).split()
    forced = _run(MMR_CODE, pure=True).split()
    assert active[0] == "True" and forced[0] == "False"
    assert active[1] == forced[1]  # same hits selected, same order


def test_tokenize_and_cosine_route_through_dispatch():
    code = (
        "import struct; from mnemosyne import text;"
        "t = text.tokenize('Hello, WORLD... v1.2.3 data-only');"
        "c = text.cosine([1.0, 2.0, 3.0], [4.0, 5.0]);"
        "print(text.NATIVE is not None, '|'.join(t), struct.pack('<d', c).hex())"
    )
    active = _run(code, pure=False).split()
    forced = _run(code, pure=True).split()
    assert active[0] == "True" and forced[0] == "False"
    assert active[1:] == forced[1:]


PPR_CODE = (
    "import struct; from mnemosyne import text;"
    "from mnemosyne.algorithms import ppr_power_iteration;"
    # Deliberate shape stressors: an empty neighbor list ('d'), duplicate
    # neighbors + a self-loop ('c'), and an out-of-adjacency neighbor that is
    # itself a seed ('x') — the external-teleport and key-order edge cases.
    "adjacency = {'a': ['b', 'c'], 'b': ['a'], 'c': ['d', 'd', 'c'], 'd': [], 'e': ['x']};"
    "ranks = ppr_power_iteration(adjacency, lambda n: n in {'a', 'x'});"
    "print(text.NATIVE is not None, ';'.join("
    "node + '=' + struct.pack('<d', score).hex() for node, score in ranks.items()))"
)


def test_ppr_power_iteration_identical_both_modes():
    active = _run(PPR_CODE, pure=False).split()
    forced = _run(PPR_CODE, pure=True).split()
    assert active[0] == "True" and forced[0] == "False"
    # Joined in dict order: same nodes, same INSERTION ORDER, same score bits.
    assert active[1] == forced[1]


# --- Task 7: engine batch call sites (single FFI crossing per scan) ---------

TENANT = "t-dispatch"

# Canonical public capture path (append_evidence), ~20 items: every 3rd gets a
# stored embedding (so the stored-embedding gate path fires) and every 6th is
# non-text modality (so the dense_media channel fires); the rest fall back to
# the hashing embedding (dense_hash). Shared verbatim between the in-process
# tests (exec) and the subprocess equivalence code so both seed identically.
SEED_SRC = """
from mnemosyne import text
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence

engine = LocalMemoryEngine()
tenant = "t-dispatch"
for i in range(20):
    engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="user-a",
            actor="user",
            source_type="chat",
            content=f"alpha beta gamma item {i} delta-{i % 5}",
            trust_tier=0,
            access_policy={"tenant": tenant},
            modality="image" if i % 6 == 0 else "text",
            embedding=text.hashing_embedding(f"alpha beta stored {i}", 256) if i % 3 == 0 else None,
        )
    )
"""

ENGINE_SCANS_CODE = SEED_SRC + """
import struct

rows = ["native=" + str(text.NATIVE is not None)]
for hit in engine.vector_search("alpha beta", 12, {"tenant_id": tenant}):
    rows.append("|".join((hit.id, struct.pack("<d", hit.score).hex(), hit.channel)))
rows.append("--")
for hit in engine.lexical_search("alpha beta item", 12, {"tenant_id": tenant}):
    rows.append("|".join((hit.id, struct.pack("<d", hit.score).hex(), hit.channel)))
print("\\n".join(rows))
"""


def _seed_engine():
    ns: dict[str, object] = {}
    exec(SEED_SRC, ns)  # noqa: S102 - our own constant; keeps seeds identical
    return ns["engine"]


def test_engine_scans_byte_identical_both_modes():
    active = _run(ENGINE_SCANS_CODE, pure=False).splitlines()
    forced = _run(ENGINE_SCANS_CODE, pure=True).splitlines()
    assert active[0] == "native=True" and forced[0] == "native=False"
    assert active[1:] == forced[1:]  # full (id, score-bits, channel) tuples
    body = active[1:]
    # 20 candidates all score > 0, so both scans truncate to k=12: the
    # score>0 filter, sort, and truncation paths are all exercised.
    assert len(body) == 25  # 12 dense + "--" separator + 12 lexical
    channels = {line.rsplit("|", 1)[-1] for line in body if "|" in line}
    assert {"dense_media", "dense_hash", "lexical"} <= channels


def test_vector_search_native_single_dense_scan_crossing(monkeypatch):
    """Native vector_search makes exactly ONE dense_scan FFI crossing covering
    every candidate row (embeddings stay per-hit in Python for the security
    gate + metadata side effects)."""
    from mnemosyne import text as text_mod

    if text_mod.NATIVE is None:
        pytest.skip("pure mode active (MNEMOSYNE_PURE=1); no batch path")

    engine = _seed_engine()
    calls: list[int] = []
    real = native.dense_scan

    def counting(query_vec, rows):
        calls.append(len(rows))
        return real(query_vec, rows)

    monkeypatch.setattr(native, "dense_scan", counting)
    hits = engine.vector_search("alpha beta", 12, {"tenant_id": TENANT})
    assert len(hits) == 12
    assert calls == [20]  # one crossing, all 20 candidates in the batch


def test_lexical_search_native_single_lexical_scan_crossing(monkeypatch):
    """Native adapterless lexical_search makes exactly ONE lexical_scan FFI
    crossing covering every candidate text."""
    from mnemosyne import text as text_mod

    if text_mod.NATIVE is None:
        pytest.skip("pure mode active (MNEMOSYNE_PURE=1); no batch path")

    engine = _seed_engine()
    calls: list[int] = []
    real = native.lexical_scan

    def counting(query, texts):
        calls.append(len(texts))
        return real(query, texts)

    monkeypatch.setattr(native, "lexical_scan", counting)
    hits = engine.lexical_search("alpha beta item", 12, {"tenant_id": TENANT})
    assert len(hits) == 12
    assert calls == [20]  # one crossing, all 20 candidate texts in the batch


def test_mmr_native_path_calls_embed_hit_exactly_once_per_hit():
    """The native fast path materializes vectors = [embed_hit(h) for h in hits]
    exactly once per hit, index-aligned 1:1 (the kernel raises ValueError on a
    length mismatch). The pure loop deliberately recomputes per candidate loop,
    so this contract is native-path-only."""
    from mnemosyne import text as text_mod
    from mnemosyne.algorithms import mmr_select
    from mnemosyne.models import Hit

    if text_mod.NATIVE is None:
        pytest.skip("pure mode active (MNEMOSYNE_PURE=1); no materialization path")

    calls: Counter[str] = Counter()

    def embed(hit: Hit) -> list[float]:
        calls[hit.id] += 1
        return text_mod.hashing_embedding(hit.text, 32)

    hits = [
        Hit(
            id=str(i),
            kind="evidence",
            tenant_id="t",
            branch="main",
            text=f"alpha beta {i}",
            score=float(i),
            channel="dense",
        )
        for i in range(5)
    ]
    query_vec = text_mod.hashing_embedding("alpha beta", 32)
    selected = mmr_select(hits, 3, query_vec=query_vec, embed_hit=embed, mmr_lambda=0.7)
    assert len(selected) == 3
    assert calls == Counter({str(i): 1 for i in range(5)})
