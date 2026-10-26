"""Candidate timestamps stay JSON-safe and obey the source's read redactions."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.retrieval import hit_recency_for_unit
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite", "postgres-projection"])
def candidates(request, tmp_path):
    engine = SqliteEngine(tmp_path / "memory.sqlite") if request.param == "sqlite" else LocalMemoryEngine()

    def read(evidence, *, role="reader", full=False):
        engine.append_evidence(evidence)
        filt = {"tenant_id": "t", "role": role}
        if request.param == "postgres-projection":
            # Exercise the PG projection with a real authorized export; no DB
            # or provider is needed for this mapping/privacy regression.
            ops = SimpleNamespace(policy=engine.policy, export_tenant_filtered=engine.export_tenant_filtered)
            return PostgresEngine.passage_candidates(ops, filt)
        if full:
            return engine.retrieve("launch", "t", filt=filt, record_access=False).hits
        return engine.lexical_search("launch", 5, filt)

    yield read
    engine.close()


def source(metadata, *, redacted=False):
    return Evidence(tenant_id="t", user_id="u", actor="user", source_type="doc",
        content="launch code: Secret123", created_at=datetime(2026, 10, 22, 19, tzinfo=UTC),
        metadata=metadata, access_policy={"redact_fields": ["code"], "min_role_for_raw": "operator"}
        if redacted else {})


@pytest.mark.parametrize("name", ["event_start", "event_end", "occurred_start", "occurred_end"])
@pytest.mark.parametrize("full", [False, True])
def test_redacted_source_cannot_leak_arbitrary_text_via_event_metadata(candidates, name, full):
    hits = candidates(source({name: "Secret123"}, redacted=True), full=full)
    assert hits and hits[0].text == "launch code: [REDACTED:code]"
    assert "Secret123" not in json.dumps(hits[0].to_dict())
    assert not {"event_start", "event_end", "occurred_start", "occurred_end"}.intersection(hits[0].metadata)


def test_redacted_source_withholds_even_valid_event_dates(candidates):
    hits = candidates(source({"event_start": "2026-10-22T12:00:00-07:00"}, redacted=True))
    assert "event_start" not in hits[0].metadata


def test_unredacted_dates_are_canonical_and_candidates_serialize(candidates):
    hits = candidates(source({"occurred_start": "2026-10-22T12:00:00-07:00",
                              "event_end": "2026-10-23"}))
    assert hits[0].metadata["event_start"] == "2026-10-22T19:00:00+00:00"
    assert hits[0].metadata["event_end"] == "2026-10-23T00:00:00+00:00"
    assert hits[0].metadata["_candidate_created_at"] == "2026-10-22T19:00:00+00:00"
    json.dumps(hits[0].to_dict(), allow_nan=False)


@pytest.mark.parametrize("value", ["not-a-date", {"secret": "Secret123"}, ["Secret123"], 123])
def test_invalid_event_values_are_omitted(candidates, value):
    hits = candidates(source({"event_start": value, "occurred_end": value}))
    assert not {"event_start", "event_end", "occurred_start", "occurred_end"}.intersection(hits[0].metadata)
    json.dumps(hits[0].to_dict(), allow_nan=False)


def test_raw_authorized_reader_keeps_safe_dates(candidates):
    hits = candidates(source({"event_start": "2026-10-22T12:00:00-07:00"}, redacted=True), role="operator")
    assert hits[0].metadata["event_start"] == "2026-10-22T19:00:00+00:00"


@pytest.mark.parametrize("bad", ["invalid", "", {"private": "Secret123"}])
def test_invalid_interval_endpoint_does_not_turn_interval_into_point(candidates, bad):
    hits = candidates(source({"event_start": "2026-10-22T10:00:00Z", "event_end": bad}))
    assert not {"event_start", "event_end"}.intersection(hits[0].metadata)
    assert hits[0].metadata["_candidate_created_at"] == "2026-10-22T19:00:00+00:00"


@pytest.mark.parametrize("start,end,now", [
    ("2026-10-01T00:00:00-07:00", "2026-11-01T00:00:00-07:00", "2026-10-08T12:00:00+00:00"),
    ("2026-03-01T00:00:00-08:00", "2026-04-01T00:00:00-07:00", "2026-03-08T12:00:00+00:00"),
    ("2026-01-01T00:00:00+05:30", "2027-01-01T00:00:00+05:30", "2026-01-08T12:00:00+00:00"),
    ("2026-10-01T00:00:00-07:00", "2026-10-31T23:59:59-07:00", "2026-10-08T12:00:00+00:00"),
])
def test_calendar_recency_survives_utc_projection_and_dst(candidates, start, end, now):
    hits = candidates(source({"event_start": start, "event_end": end}))
    assert hits[0].metadata["_candidate_event_calendar"] is True
    assert hit_recency_for_unit(hits[0], datetime.fromisoformat(now)) == 0.5


@pytest.mark.parametrize("redacted", [False, True])
def test_input_cannot_spoof_calendar_projection(candidates, redacted):
    hits = candidates(source({"event_start": "2026-10-22T10:00:00Z",
                              "_candidate_event_calendar": "Secret123"}, redacted=redacted))
    assert "_candidate_event_calendar" not in hits[0].metadata


def test_redacted_calendar_interval_withholds_derived_precision(candidates):
    hits = candidates(source({"event_start": "2026-10-01", "event_end": "2026-11-01"}, redacted=True))
    assert "_candidate_event_calendar" not in hits[0].metadata


def test_month_long_trip_is_not_calendar_precision(candidates):
    hits = candidates(source({"event_start": "2026-10-15T00:00:00-07:00",
                              "event_end": "2026-11-15T00:00:00-08:00"}))
    assert "_candidate_event_calendar" not in hits[0].metadata


def test_valid_endpoint_alias_can_replace_invalid_primary(candidates):
    hits = candidates(source({"event_start": "2026-10-01", "event_end": "invalid",
                              "occurred_end": "2026-11-01"}))
    assert hits[0].metadata["event_end"] == "2026-11-01T00:00:00+00:00"
    assert hits[0].metadata["_candidate_event_calendar"] is True
