"""Public lifecycle-clock prerequisite characterization, not an M07 benchmark."""
import json
from datetime import datetime, timedelta

import pytest

from eval.harness.cli_driver import MnemoCLI


def test_public_queue_clock_advances_and_persists_protected_rehearsal(tmp_path):
    cli = MnemoCLI(store=str(tmp_path / "store.json"), timeout_s=30)
    lifecycle = {"tier": "verbatim", "must_keep": True, "protected": True,
                 "next_rehearsal_at": "2030-01-02T00:00:00+00:00",
                 "last_accessed": "2030-01-01T00:00:00+00:00",
                 "salience": 0.1, "importance": 0.1, "successful_rehearsals": 0}
    capture = cli.run("ingest", "--tenant", "clock-probe", "--user", "probe",
                      "--source-type", "note", "--content", "Synthetic archive token is amber.",
                      "--metadata", json.dumps({"lifecycle": lifecycle}),
                      "--no-enqueue-consolidation").json
    cid = capture["cid"]
    states = []
    for step, day in enumerate((1, 2, 3)):
        payload = {"tenant_id": "clock-probe", "source_evidence_cids": [cid],
                   "passes": ["forgetter"], "now": f"2030-01-{day:02}T00:00:00+00:00",
                   "consolidation_step": step * 5}
        cli.run("queue-enqueue", "--kind", "consolidate_evidence", "--payload", json.dumps(payload))
        job = cli.run("consolidate-once").json["job"]
        assert job["status"] == "complete"
        result = job["result"]
        assert result["role_pipeline"]["model_backed_roles"] == []
        forgetter = next(row for row in result["pass_results"] if row["name"] == "forgetter")
        assert forgetter["status"] == "complete"
        assert forgetter["details"]["failed_cids"] == []
        assert forgetter["details"]["demoted"] == 0
        state, = forgetter["details"]["states"]
        assert state["cid"] == cid
        assert state["updated"] and not state["rail_blocked"]
        assert state["to_tier"] == "verbatim"
        states.append(state)
    assert [row["rehearsed"] for row in states] == [False, True, False]
    assert [row["successful_rehearsals"] for row in states] == [0, 1, 1]
    assert states[0]["next_rehearsal_at"] == "2030-01-02T00:00:00+00:00"
    assert states[1]["next_rehearsal_at"] == states[2]["next_rehearsal_at"] == "2030-01-05T00:00:00+00:00"


# Fixed calendar cases are prerequisite regressions, not M07's seeded corpus.
@pytest.mark.parametrize("start", [
    "2030-01-31T00:00:00+00:00", "2031-12-31T00:00:00+00:00",
    "2032-02-28T00:00:00+00:00", "2032-02-29T00:00:00+00:00",
    "2033-04-30T00:00:00+00:00",
])
def test_public_rehearsal_calendar_persists_across_months(start, tmp_path):
    cli = MnemoCLI(store=str(tmp_path / "calendar.json"), timeout_s=30)
    due = datetime.fromisoformat(start) + timedelta(days=1)
    lifecycle = {"tier": "verbatim", "must_keep": True, "protected": True,
                 "next_rehearsal_at": due.isoformat(), "last_accessed": start,
                 "salience": 0.1, "importance": 0.1, "successful_rehearsals": 0}
    captured = cli.run("ingest", "--tenant", "calendar-probe", "--user", "probe",
        "--source-type", "note", "--content", "Synthetic protected calendar fact.",
        "--metadata", json.dumps({"lifecycle": lifecycle}), "--no-enqueue-consolidation").json
    # Literal public schedule; do not import the SUT's scheduling function.
    for count, interval in enumerate((3, 7, 14, 30, 60, 120, 240, 240), start=1):
        for offset, should_rehearse in ((-1, False), (0, True)):
            now = due + timedelta(seconds=offset)
            payload = {"tenant_id": "calendar-probe", "source_evidence_cids": [captured["cid"]],
                       "passes": ["forgetter"], "now": now.isoformat(),
                       "consolidation_step": count * 10 + offset}
            cli.run("queue-enqueue", "--kind", "consolidate_evidence", "--payload", json.dumps(payload))
            job = cli.run("consolidate-once").json["job"]
            assert job["status"] == "complete"
            assert job["result"]["role_pipeline"]["model_backed_roles"] == []
            details = next(row["details"] for row in job["result"]["pass_results"] if row["name"] == "forgetter")
            assert details["failed_cids"] == [] and details["demoted"] == 0
            state, = details["states"]
            assert state["cid"] == captured["cid"] and state["to_tier"] == "verbatim"
            assert state["rehearsed"] is should_rehearse
            assert state["successful_rehearsals"] == count - (not should_rehearse)
            expected = due + timedelta(days=interval) if should_rehearse else due
            assert state["next_rehearsal_at"] == expected.isoformat()
        due += timedelta(days=interval)
    assert (due - datetime.fromisoformat(start)).days > 365
