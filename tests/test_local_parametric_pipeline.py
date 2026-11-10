from dataclasses import replace
from types import SimpleNamespace

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.integration import build_learning_runtime, configure_learning
from mnemosyne.gate import RegressionCase
from mnemosyne.hosts.local_parametric import LocalMemoryTrainer
from mnemosyne.learning import Lesson
from mnemosyne.models import Evidence
from mnemosyne.parametric import ParametricArtifactStore, ParametricTier


class SeparableEmbedding:
    name = 'test-separable'
    dims = 2

    def embed(self, text):
        return [1.0 if 'green' in text else -1.0, 0.1]

    def embed_many(self, texts):
        return [self.embed(text) for text in texts]


def setup_pipeline(tmp_path, *, inverse=False):
    engine = LocalMemoryEngine()
    engine.adapters = replace(engine.adapters, embedding=SeparableEmbedding())
    runtime = build_learning_runtime(engine)
    training = []
    for i in range(8):
        query = f"{'green' if i % 2 else 'red'} operation {i}"
        receipt = runtime.prepare_context('t', 'u', f's{i}', query)
        episode = runtime.observe_turn('t', 'u', f's{i}', query, f'response {i}', receipt_ids=[receipt['receipt_id']])
        value = 1 if i % 2 else -1
        if inverse and i >= 4:
            value = -value
        runtime.record_signal('t', episode_id=episode['episode_id'], kind='verifier', value=value,
                              evidence=f'external outcome {i}', final=True)
        if i < 4:
            training.append(episode['episode_id'])
    source = engine.append_evidence(Evidence(tenant_id='t', user_id='u', actor='user',
        source_type='note', content='The protected orchard key is amber.',
        access_policy={'tenant': 't', 'allow_principals': ['u']}))
    cases = [RegressionCase('protected', 'orchard', 'orchard key', 'amber', protected=True)]
    trainer = LocalMemoryTrainer(engine, tmp_path / 'models', lambda: cases, backend='pure-python')
    tier = ParametricTier(ParametricArtifactStore(tmp_path / 'artifacts'), trainer)
    configure_learning(engine, parametric=tier)
    lesson = Lesson('t', 'corrective', 'operations', 'Follow verified operation results.',
                    status='active', origin='curated', source_episode_ids=training)
    artifact = tier.propose_from_lessons('t', [lesson], [])
    return engine, runtime, tier, artifact, cases, source


def test_measured_adapter_activates_serves_reloads_and_rolls_back(tmp_path):
    engine, runtime, tier, artifact, cases, _ = setup_pipeline(tmp_path)
    decision = tier.evaluate_measured(artifact, cases)
    assert decision.promoted, decision.reason
    assert artifact.metrics['heldout_brier_improvement'] > 0.01
    stored = tier.artifact_store.read(artifact.artifact_uri)
    assert stored['payload']['provider']['artifact_ref']
    assert stored['payload']['gate']['passed_cases'] == ['protected']
    receipt = runtime.prepare_context('t', 'u', 'live', 'green unseen request')
    assert receipt['prediction'] > 0.5
    saved = runtime.writer.read('t')['receipts'][receipt['receipt_id']]
    assert saved['parametric_prediction']['artifact_id'] == artifact.id
    assert saved['baseline_prediction'] == 0.5
    assert tier.predict('t', 'other', 'green', .5) is None
    reloaded = LocalMemoryTrainer(engine, tmp_path / 'models', cases)
    assert reloaded.predict('t', 'u', 'green', .5)['prediction'] > .5
    tier.rollback(artifact, 'operator rollback', cases)
    assert reloaded.predict('t', 'u', 'green', .5) is None


def test_no_improvement_and_caller_veto_cannot_activate(tmp_path):
    _, _, tier, artifact, cases, _ = setup_pipeline(tmp_path, inverse=True)
    decision = tier.evaluate_measured(artifact, cases)
    assert not decision.promoted
    assert tier.predict('t', 'u', 'green', .5) is None
    _, _, tier, artifact, cases, _ = setup_pipeline(tmp_path / 'veto')
    assert not tier.evaluate_measured(artifact, cases, allow_activation=False).promoted
    assert tier.predict('t', 'u', 'green', .5) is None


def test_protected_case_is_executed_and_source_changes_disable_serving(tmp_path):
    engine, runtime, tier, artifact, cases, _ = setup_pipeline(tmp_path)
    original = engine.retrieve
    engine.retrieve = lambda *a, **k: SimpleNamespace(hits=[], abstained=True)
    assert not tier.evaluate_measured(artifact, cases).promoted
    engine.retrieve = original
    assert tier.evaluate_measured(artifact, cases).promoted
    model = tier.trainer._load(tier.artifact_store.read(artifact.artifact_uri)['payload']['provider']['artifact_ref'], 't')
    row = runtime.writer.read('t')['episodes'][model['provenance']['training_ids'][0]]
    engine.forget('t', row['source_cids'][0])
    assert tier.predict('t', 'u', 'green', .5) is None


def test_suite_change_and_missing_evaluator_fail_closed(tmp_path):
    _, _, tier, artifact, cases, _ = setup_pipeline(tmp_path)
    assert tier.evaluate_measured(artifact, cases).promoted
    cases.append(RegressionCase('new', 'new', 'new', 'new', protected=True))
    assert tier.predict('t', 'u', 'green', .5) is None
    with pytest.raises(ValueError, match='suite changed'):
        tier.evaluate_measured(artifact, cases)
    tier.trainer = None
    assert not tier.evaluate_measured(artifact, cases).promoted


def test_automatic_worker_trains_evaluates_activates_and_checkpoints(tmp_path):
    from mnemosyne.hosts.codex_learning import advance
    engine, runtime, tier, proposed, cases, _ = setup_pipeline(tmp_path)
    provider = tier.artifact_store.read(proposed.artifact_uri)['payload']['provider']
    model = tier.trainer._load(provider['artifact_ref'], 't')
    lesson = Lesson('t', 'corrective', 'operations', 'Follow measured results.', status='active',
                    origin='curated', source_episode_ids=model['provenance']['training_ids'])
    facade = SimpleNamespace(runtime_state=SimpleNamespace(load_gate_cases=lambda: cases),
        tools=SimpleNamespace(parametric=tier, _learning_runtime=lambda: runtime,
            learning=SimpleNamespace(load_native=lambda tenants: None,
                                     lessons={lesson.id: lesson}, procedures={})))
    report = advance(facade, 't', tmp_path / 'worker.json')
    assert report['training']['promoted'] is True
    assert tier.predict('t', 'u', 'green new work', .5)['artifact_id'] == report['training']['artifact_id']
    assert advance(facade, 't', tmp_path / 'worker.json') == report


def test_proposal_identity_and_full_case_set_are_bound(tmp_path):
    _, _, tier, artifact, cases, _ = setup_pipeline(tmp_path)
    artifact.source_ids = ['forged-source']
    with pytest.raises(ValueError, match='identity changed'):
        tier.evaluate_measured(artifact, cases)
    original = tier.artifact_store.load_artifact(artifact.artifact_uri)
    incomplete = [RegressionCase('replacement', 'orchard', 'orchard key', 'amber', protected=True)]
    with pytest.raises(ValueError, match='complete protected suite'):
        tier.evaluate_measured(original, incomplete)
    assert tier.predict('t', 'u', 'green', .5) is None


def test_live_prediction_never_calls_provider_inside_learning_transaction(tmp_path, monkeypatch):
    engine, runtime, tier, artifact, cases, _ = setup_pipeline(tmp_path)
    assert tier.evaluate_measured(artifact, cases).promoted
    locked = [False]
    original_apply = runtime.writer.apply

    def apply(tenant, operation, callback, **kwargs):
        def guarded(state):
            locked[0] = True
            try:
                return callback(state)
            finally:
                locked[0] = False
        return original_apply(tenant, operation, guarded, **kwargs)

    original_embed = engine.adapters.embedding.embed_many

    def embed(texts):
        assert not locked[0], 'provider called inside learning transaction'
        return original_embed(texts)

    monkeypatch.setattr(runtime.writer, 'apply', apply)
    monkeypatch.setattr(engine.adapters.embedding, 'embed_many', embed)
    result = runtime.prepare_context('t', 'u', 'outside-lock', 'green fresh operation')
    assert result['prediction'] > .5
