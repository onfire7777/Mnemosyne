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
