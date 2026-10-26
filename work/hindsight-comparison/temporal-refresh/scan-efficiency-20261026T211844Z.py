"""Bounded provider-free operation counts; run with the repository Python environment."""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mnemosyne.answering import AnswerReadContext
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mental_model_refresh import MentalModelRefreshWorker, new_schedule
from mnemosyne.mental_models import MentalModelService
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


def probe(backend):
    context = AnswerReadContext(tenant_id="t", user_id="u", role="agent", max_sensitivity=0)
    with TemporaryDirectory() as temporary:
        engine = (LocalMemoryEngine(Path(temporary) / "store.json") if backend == "local"
                  else SqliteEngine(Path(temporary) / "store"))
        try:
            for index in range(8):
                engine.append_evidence(Evidence(
                    tenant_id="t", user_id="u", actor="user", source_type="chat", content=f"Source {index}.",
                    access_policy={"tenant": "t", "allow_principals": ["u"]}))
            def no_provider():
                raise AssertionError("no provider may run")
            service = MentalModelService(engine, no_provider)
            fingerprint = service._snapshot(context)[0]
            models = []
            for index in range(3):
                mid = service.create(context, f"Model {index}", "What is recorded?")["model_id"]
                models.append(mid)
                row = service._load(context, mid)
                schedule = new_schedule(True, 3600)
                now = datetime.now(UTC)
                schedule.update(next_run_at=(now + timedelta(hours=1)).isoformat(),
                                last_started_at=(now - timedelta(minutes=2)).isoformat(),
                                last_finished_at=(now - timedelta(minutes=2)).isoformat(),
                                last_outcome="abstained")
                row.update(status="abstained", corpus_fingerprint=fingerprint, time_fingerprint=None,
                           refresh_schedule=schedule)
                engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
            counts = {"exports": 0, "point_reads": 0}
            original_export, original_get = engine.export_tenant_filtered, engine.get_evidence
            def export(*args, **kwargs):
                counts["exports"] += 1
                return original_export(*args, **kwargs)
            def get(*args, **kwargs):
                counts["point_reads"] += 1
                return original_get(*args, **kwargs)
            engine.export_tenant_filtered, engine.get_evidence = export, get
            worker = MentalModelRefreshWorker(service, context, check_changes=True)
            processed = [worker.run_once()["processed"] for _ in range(2)]
            result = {"two_unchanged_early_polls": {**counts, "processed": processed}}
            counts.update(exports=0, point_reads=0)
            pending = service.create(context, "Pending", "What is recorded?")
            result["create_pending"] = {**counts, "status": pending["status"]}
            counts.update(exports=0, point_reads=0)
            for mid in models:
                row = service._load(context, mid)
                row["refresh_schedule"]["next_run_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
                engine.save_mental_model_record("t", mid, row, expected_version=row["version"])
            report = MentalModelRefreshWorker(service, context).run_once()
            result["three_due_unchanged_models"] = {**counts, "processed": report["processed"], "unchanged": report["unchanged"]}
            return result
        finally:
            engine.close()


if __name__ == "__main__":
    print(json.dumps({backend: probe(backend) for backend in ("local", "sqlite")}, indent=2, sort_keys=True))
