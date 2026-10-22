"""Historical retrieval normalizes a caller's ISO timestamp before graph dispatch."""

from datetime import UTC, datetime

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    value = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "db")
    value.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="document",
        content="The observatory opened in Cedar Valley.", access_policy={"tenant": "t"},
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    ))
    yield value
    if request.param == "sqlite":
        value.close()


@pytest.mark.parametrize("parallel", ["0", "1"])
@pytest.mark.parametrize("timestamp", ["2025-01-01T00:00:00Z", "2025-01-01T09:00:00+09:00"])
def test_iso_historical_retrieval_matches_datetime(engine, monkeypatch, parallel, timestamp):
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", parallel)
    args = {"query": "observatory Cedar Valley", "tenant_id": "t", "record_access": False}
    original = {"as_of": timestamp}
    actual = engine.retrieve(**args, filt=original)
    expected = engine.retrieve(**args, filt={"as_of": datetime(2025, 1, 1, tzinfo=UTC)})
    assert actual.to_dict() == expected.to_dict()
    assert original == {"as_of": timestamp}  # Caller-owned filters are unchanged.


@pytest.mark.parametrize("value", [True, 42, {}, "", "not-a-date"])
def test_invalid_historical_time_fails_before_retrieval(engine, monkeypatch, value):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid historical time reached a retrieval provider")
    monkeypatch.setattr(engine, "vector_search", forbidden)
    monkeypatch.setattr(engine, "lexical_search", forbidden)
    monkeypatch.setattr(engine, "graph_ppr", forbidden)
    with pytest.raises(ValueError, match="as_of"):
        engine.retrieve("observatory", tenant_id="t", filt={"as_of": value})
