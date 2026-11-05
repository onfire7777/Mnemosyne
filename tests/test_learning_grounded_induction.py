from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.learning import LearningSystem, Lesson, Trajectory


def test_induction_quotes_episode_instead_of_inventing_solution():
    system = LearningSystem(LocalMemoryEngine())
    episode = Trajectory(
        "t",
        "u",
        "s",
        "calculate",
        [{"name": "arithmetic", "status": "failed", "error": "wrong sum"}],
        "failure",
        -1,
        "v1",
    )
    attribution = system.attribute_failure(system.log_trajectory(episode))
    lesson = system.induce_lesson(attribution)
    procedure = system.induce_procedure(lesson)
    assert "wrong sum" in lesson.content
    assert "verify with tools" not in lesson.content
    assert "Apply the smallest correction" not in procedure.body
    assert attribution.confidence == 0
    assert lesson.votes == 0
    assert lesson.source_episode_ids == [episode.id]


def test_old_lesson_without_new_fields_remains_readable():
    old = Lesson.from_dict(
        {
            "tenant_id": "t",
            "lesson_type": "corrective",
            "failure_signature": "x",
            "content": "source text",
            "id": "old",
            "votes": 2,
            "status": "candidate",
        }
    )
    assert old.content == "source text"
    assert old.source_episode_ids == []


def test_legacy_promotion_cannot_turn_generated_content_into_authority():
    from mnemosyne.gate import RegressionCase

    engine = LocalMemoryEngine()
    learning = LearningSystem(engine)
    from mnemosyne.models import Evidence

    engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="note",
            content="Lesson off by one day: verify with tools.",
            access_policy={"tenant": "t"},
        )
    )
    lesson = Lesson("t", "corrective", "off by one day", "verify with tools")
    result = learning.promote_lesson(
        lesson,
        [
            RegressionCase(
                "case", "off by one day", "lesson off by one day", "verify with tools"
            )
        ],
    )
    assert not result.promoted
    assert lesson.status == "candidate"
    assert not engine.assertions


def test_legacy_archive_is_native_and_cannot_resurrect_erased_sources(tmp_path):
    from mnemosyne.models import Evidence
    from mnemosyne.runtime_state import RuntimeState

    engine = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    cid = engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="note",
            content="source",
        )
    )
    learning = LearningSystem(engine)
    trajectory = Trajectory(
        "t", "u", "s", "task", [], "success", 1.0, "v1", evidence_cid=cid
    )
    learning.log_trajectory(trajectory)
    side = RuntimeState(tmp_path / "runtime.json")
    side.save_learning(learning)
    assert side.data["learning"] == {"engine_tenants": ["t"]}
    assert trajectory.id in side.load_learning(LearningSystem(engine)).trajectories
    engine.forget("t", cid)
    side.save_learning(learning)
    assert side.load_learning(LearningSystem(engine)).trajectories == {}


def test_legacy_procedure_requires_real_outcome_provenance():
    from mnemosyne.learning import Procedure
    system = LearningSystem(LocalMemoryEngine())
    procedure = Procedure('t','checklist','untested','perform an action',{})
    verdict = system.validate_procedure(procedure, [])
    assert not verdict.promoted
    assert procedure.status == 'candidate'
