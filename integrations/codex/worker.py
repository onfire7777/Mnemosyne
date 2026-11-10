"""Retry completed turns and advance the configured local memory host."""

import json
import os
import sys
from datetime import datetime, timezone

from runtime import ROOT, STATE, TENANT, USER, open_facade
from hook import adapter
from automatic_learning import advance
from mnemosyne.jobs import RuntimeJobHandlers
from mnemosyne.media import CommandMediaTextExtractor
from mnemosyne.mental_model_refresh import MentalModelRefreshWorker
from mnemosyne.mental_models import MentalModelService
from mnemosyne.queue import QueueWorker


def main():
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "processed": []}
    try:
        report["stage"] = "completed_turns"
        report["completions"] = adapter().recover_completed(max_sessions=8)
        with open_facade() as facade:
            report["stage"] = "queued_work"
            handlers = RuntimeJobHandlers(
                facade.engine, facade.queue, metrics=facade.tools.metrics,
                object_store=facade.tools.ingestion.object_store,
                media_extractor=CommandMediaTextExtractor(
                    [sys.executable, str(ROOT / "codex" / "multimodal.py")], timeout_seconds=300,
                ),
                learning=facade.tools.learning, user_model=facade.tools.user_model,
                gate_cases=facade.runtime_state.load_gate_cases(),
            )
            worker = QueueWorker(facade.queue, handlers.handlers())
            for _ in range(8):
                job = worker.run_once()
                if job is None:
                    break
                report["processed"].append({"id": job.id, "kind": job.kind, "status": job.status})
                if job.kind in {"consolidate_evidence", "consolidate_sleep"}:
                    break
            report["queue"] = facade.queue.snapshot()
            report["stage"] = "project_memory"
            from mnemosyne.hosts.project_memory import advance_project_memory
            report["project_memory"] = advance_project_memory(
                facade.tools._learning_runtime(), TENANT, USER, STATE / "project-memory.json")
            report["stage"] = "automatic_learning"
            report["automatic_learning"] = advance(facade, TENANT, STATE / "automatic-learning.json")
            report["stage"] = "retrieval_index"
            from mnemosyne.retrieval_maintenance import maintain_retrieval_index
            report["retrieval_index"] = maintain_retrieval_index(facade.engine, TENANT, USER)
        # Model generation runs outside the hook lock. Its own lease protects
        # concurrent refreshes while completion capture can continue.
        report["stage"] = "maintained_answers"
        with open_facade() as facade:
            from mnemosyne.knowledge_maintenance import KnowledgeMaintenanceWorker
            from mnemosyne.hosts.project_memory import maintenance_context
            knowledge_context = maintenance_context(facade.engine, TENANT, USER)
            report["knowledge"] = KnowledgeMaintenanceWorker(facade.engine, knowledge_context,
                checkpoint_path=STATE / "knowledge-maintenance.json").run_once()
            service = MentalModelService(facade.engine, provider_factory=facade.tools._grounded_provider_factory)
            context = maintenance_context(facade.engine, TENANT, USER)
            report["maintained_answers"] = MentalModelRefreshWorker(
                service, context, max_batch=1, check_changes=True,
            ).run_once()
        report["stage"] = "complete"
    except Exception as error:
        report["error"] = type(error).__name__
        raise
    finally:
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = STATE / "worker-status.json"
        temporary = destination.with_suffix(".tmp")
        with temporary.open("w") as stream:
            temporary.chmod(0o600)
            json.dump(report, stream, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)


if __name__ == "__main__":
    from mnemosyne.hosts.locking import bounded_lock
    try:
        with bounded_lock(STATE / "worker.lock", timeout=0):
            main()
    except TimeoutError:
        pass  # another worker owns this bounded batch; hooks remain independent
