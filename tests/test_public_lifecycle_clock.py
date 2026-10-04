"""Public lifecycle-clock prerequisite characterization, not an M07 benchmark."""
import json

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
