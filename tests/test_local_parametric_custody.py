"""A measured adapter loses serving authority when its evidence loses custody."""

from copy import deepcopy
from dataclasses import replace

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.integration import build_learning_runtime
from mnemosyne.hosts.local_parametric import LocalMemoryTrainer
from mnemosyne.learning import Lesson
from mnemosyne.parametric import ParametricArtifactStore, ParametricTier
from tests.test_local_parametric_pipeline import SeparableEmbedding, setup_pipeline


def _model(tier, artifact):
    provider = tier.artifact_store.read(artifact.artifact_uri)["payload"]["provider"]
    return tier.trainer._load(provider["artifact_ref"], "t")


@pytest.mark.parametrize("partition", ["training_ids", "heldout_ids"])
@pytest.mark.parametrize("revocation", ["expiry", "acl", "quarantine", "imported", "historical", "synthetic", "taint"])
def test_training_and_heldout_source_revocation_disables_serving(tmp_path, partition, revocation):
    engine, runtime, tier, artifact, cases, _ = setup_pipeline(tmp_path)
    assert tier.evaluate_measured(artifact, cases).promoted
    assert tier.predict("t", "u", "green unseen operation", .5) is not None
    eid = _model(tier, artifact)["provenance"][partition][0]
    episode = runtime.writer.read("t")["episodes"][eid]
    cid = next(cid for cid in episode["source_cids"] if engine.get_evidence("t", cid).actor == "user")
    source = engine.evidence[engine._evidence_key("t", "main", cid)]
    if revocation == "expiry":
        source.access_policy = {**source.access_policy, "expires_at": "2000-01-01T00:00:00+00:00"}
    elif revocation == "acl":
        source.access_policy = {**source.access_policy, "allow_principals": ["another-user"]}
    elif revocation == "taint":
        source.capability_tags = [*source.capability_tags, "data-only", "no-write-authority"]
    elif revocation == "quarantine":
        source.metadata = {**source.metadata, "quarantine_reason": "pending source review"}
    else:
        source.metadata = {**source.metadata, revocation: True}
    assert not tier.trainer._eligible_episode("t", episode)
    assert tier.predict("t", "u", "green unseen operation", .5) is None


@pytest.mark.parametrize("source", ["assistant", "self_generated", "provider_self_grade"])
def test_self_grades_are_not_training_or_evaluation_labels(tmp_path, source):
    _, runtime, tier, artifact, _, _ = setup_pipeline(tmp_path)
    eid = _model(tier, artifact)["provenance"]["training_ids"][0]
    row = deepcopy(runtime.writer.read("t")["episodes"][eid])
    row["signals"] = [{**item, "source": source} for item in row["signals"]]
    assert not tier.trainer._eligible_episode("t", row)


@pytest.mark.parametrize("status", ["imported", "legacy", "unknown", "erased"])
def test_nonresolved_histories_cannot_train_an_adapter(tmp_path, status):
    _, runtime, tier, artifact, _, _ = setup_pipeline(tmp_path)
    eid = _model(tier, artifact)["provenance"]["training_ids"][0]
    row = deepcopy(runtime.writer.read("t")["episodes"][eid])
    row["status"] = status
    assert not tier.trainer._eligible_episode("t", row)


def test_explicit_operator_verifier_remains_eligible_without_tool_row(tmp_path):
    _, runtime, tier, artifact, _, _ = setup_pipeline(tmp_path)
    eid = _model(tier, artifact)["provenance"]["training_ids"][0]
    row = runtime.writer.read("t")["episodes"][eid]
    assert not row["tool_events"]
    assert tier.trainer._eligible_episode("t", row)


def test_changed_embedding_space_disables_an_active_adapter(tmp_path):
    engine, _, tier, artifact, cases, _ = setup_pipeline(tmp_path)
    assert tier.evaluate_measured(artifact, cases).promoted
    assert tier.predict("t", "u", "green unseen operation", .5) is not None
    embedding = SeparableEmbedding()
    embedding.name = "different-model-same-dimensions"
    engine.adapters = replace(engine.adapters, embedding=embedding)
    assert tier.predict("t", "u", "green unseen operation", .5) is None


def test_training_labels_follow_external_checks_despite_opposite_user_feedback(tmp_path, monkeypatch):
    from mnemosyne.hosts import local_parametric

    engine = LocalMemoryEngine()
    engine.adapters = replace(engine.adapters, embedding=SeparableEmbedding())
    runtime = build_learning_runtime(engine)
    training_ids = []
    expected = {}
    for i in range(8):
        success = bool(i % 2)
        observed = runtime.observe_turn("t", "u", f"mixed-{i}",
            f"{'green' if success else 'red'} mixed operation {i}", f"response {i}",
            tool_events=[{"name": "external_checker", "verdict": success, "output": f"measured result {i}"}])
        eid = observed["episode_id"]
        # Four real user ratings outweigh the external check in global reward;
        # they must not reverse the label used to train the outcome predictor.
        for rating in range(4):
            runtime.record_signal("t", episode_id=eid, kind="acceptance", value=-1 if success else 1,
                                  evidence=f"explicit feedback {i}/{rating}", final=rating == 3)
        if i < 4:
            training_ids.append(eid)
            expected[eid] = int(success)
    state = runtime.writer.read("t")
    assert all(int(state["episodes"][eid]["reward"] > 0) != value for eid, value in expected.items())
    labels_seen = []
    original = local_parametric.train_logistic_adapter

    def train(features, labels, **kwargs):
        labels_seen.extend(labels)
        return original(features, labels, **kwargs)

    monkeypatch.setattr(local_parametric, "train_logistic_adapter", train)
    trainer = LocalMemoryTrainer(engine, tmp_path / "models", [], backend="pure-python")
    tier = ParametricTier(ParametricArtifactStore(tmp_path / "artifacts"), trainer)
    lesson = Lesson("t", "corrective", "operations", "Follow measured results.", status="active",
                    origin="curated", source_episode_ids=training_ids)
    tier.propose_from_lessons("t", [lesson], [])
    assert labels_seen == [expected[eid] for eid in sorted(training_ids)]
