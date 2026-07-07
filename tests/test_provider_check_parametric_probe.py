from __future__ import annotations

import argparse

import mnemosyne.postgres_engine as postgres_engine
from mnemosyne import cli


def test_seed_provider_health_parametric_corpus_yields_four_rows_two_tiers(monkeypatch) -> None:
    # The command parametric trainer restricts training to the source_ids evidence
    # split and hard-requires >=4 rows over >=2 trust tiers. The provider-check
    # probe therefore seeds a real >=4-row / two-tier provider-health corpus and
    # passes its cids as the train split -- this asserts the seed shape so the probe
    # genuinely satisfies the trainer instead of the old unsatisfiable two-id proposal.
    appended: list = []

    class _FakeEngine:
        def __init__(self, dsn, require_safe_role: bool = False) -> None:
            assert dsn == "postgresql://health"

        def ensure_tenant_and_branch(self, tenant: str, branch: str = "main") -> None:
            assert tenant == "provider-health"

        def append_evidence(self, ev, branch: str = "main") -> str:
            appended.append(ev)
            return f"{len(appended):064x}"  # stand-in content-addressed cid hex

    monkeypatch.setattr(postgres_engine, "PostgresEngine", _FakeEngine)
    args = argparse.Namespace(postgres_dsn="postgresql://health", postgres_require_safe_role=False)

    cids = cli._seed_provider_health_parametric_corpus(args)

    assert len(cids) == 4
    assert len(set(cids)) == 4  # distinct rows
    assert all(ev.tenant_id == "provider-health" for ev in appended)
    tiers = {ev.trust_tier for ev in appended}
    assert 5 in tiers and 0 in tiers  # both label classes present (trust_tier>=5 vs <5)


def test_seed_provider_health_parametric_corpus_requires_a_dsn(monkeypatch) -> None:
    monkeypatch.setattr(cli, "default_postgres_dsn", lambda: None)
    args = argparse.Namespace(postgres_dsn=None, postgres_require_safe_role=False)
    try:
        cli._seed_provider_health_parametric_corpus(args)
    except ValueError as exc:
        assert "MNEMOSYNE_POSTGRES_DSN" in str(exc)
    else:
        raise AssertionError("missing DSN must fail closed")
