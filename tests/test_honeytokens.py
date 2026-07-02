"""Honeytoken leak canaries (privacy policy §10; spec §4.0).

Per-(class, tenant) deterministic marker strings whose appearance beyond
their boundary is a leak alarm, plus the first boundary test: cross-tenant
journal isolation through the real capture path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mnemosyne.honeytokens import honeytoken, scan_for_foreign_honeytokens


def test_honeytoken_is_deterministic_and_class_tagged():
    t1 = honeytoken("S3", "tenant-a")
    assert t1 == honeytoken("S3", "tenant-a")
    assert t1.startswith("HTKN-S3-")
    assert honeytoken("S3", "tenant-b") != t1


def test_honeytoken_rejects_unknown_class():
    with pytest.raises(ValueError):
        honeytoken("S5", "tenant-a")
    with pytest.raises(ValueError):
        honeytoken("s3", "tenant-a")


def test_scan_flags_only_foreign_tokens():
    own = honeytoken("S3", "tenant-a")
    foreign = honeytoken("S3", "tenant-b")
    text = f"log line with {own} and {foreign}"
    hits = scan_for_foreign_honeytokens(text, own_tenant_id="tenant-a")
    assert hits == [foreign]


def test_scan_ignores_own_tokens_of_every_class():
    text = " ".join(honeytoken(f"S{i}", "tenant-a") for i in range(5))
    assert scan_for_foreign_honeytokens(text, own_tenant_id="tenant-a") == []


def test_scan_flags_class_relabelled_own_token():
    """Class-binding property: cross-class leakage is detectable.

    ``_tenant_hash`` mixes the class into the hash, so a tenant-a token
    generated for S3 but re-labelled as S2 is NOT a legitimate tenant-a token
    of any class — the scanner must flag it (an S3 payload surfacing under an
    S2 label is a boundary violation even within the same tenant).
    """
    relabelled = honeytoken("S3", "tenant-a").replace("HTKN-S3-", "HTKN-S2-")
    hits = scan_for_foreign_honeytokens(relabelled, own_tenant_id="tenant-a")
    assert hits == [relabelled]


def _seed_with_content(engine, tenant_id: str, content: str) -> None:
    # Task 8's canonical minimal capture shape (tests/test_journal.py
    # ``_evidence``): the repo's real public capture path with explicit
    # ``content=``.
    from mnemosyne.models import Evidence

    engine.append_evidence(
        Evidence(
            tenant_id=tenant_id,
            user_id="user-a",
            actor="user",
            source_type="chat",
            content=content,
            trust_tier=0,
            access_policy={"tenant": tenant_id},
        )
    )


def test_cross_tenant_journal_isolation(tmp_path: Path):
    """Spec §4.0: tenant A's journal never contains tenant B's honeytokens."""
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine(journal_dir=tmp_path)
    _seed_with_content(engine, "tenant-a", f"note {honeytoken('S3', 'tenant-a')}")
    _seed_with_content(engine, "tenant-b", f"note {honeytoken('S3', 'tenant-b')}")
    a_text = (tmp_path / "tenant-a.journal").read_text()
    # The canary genuinely landed in tenant-a's journal (test is non-vacuous)...
    assert honeytoken("S3", "tenant-a") in a_text
    # ...and no foreign tenant's canary crossed the boundary.
    assert scan_for_foreign_honeytokens(a_text, own_tenant_id="tenant-a") == []


def test_benchmark_artifacts_contain_no_honeytokens():
    baselines = Path(__file__).parent / "benchmarks" / "baselines.json"
    if baselines.exists():
        assert "HTKN-" not in baselines.read_text()
