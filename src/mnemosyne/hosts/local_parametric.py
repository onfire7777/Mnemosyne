"""Measured, source-bound local memory prediction adapters.

The adapter estimates task success. It cannot change factual memory, select a
procedure, or bypass any promotion gate. Training and held-out outcome evidence
are disjoint; activation remains revocable when either set loses custody.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from mnemosyne.experience.integration import build_learning_runtime
from mnemosyne.gate import GATING_CASE_ORIGINS, GateResult
from mnemosyne.parametric_adapter import ADAPTER_KIND, score, train_logistic_adapter
from mnemosyne.experience.signals import reward
from mnemosyne.experience.candidates import EXCLUDED_SOURCES
from mnemosyne.retrieval import projection_sources_readable
from mnemosyne.security import is_write_tainted


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        temporary.chmod(0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class LocalMemoryTrainer:
    adapter_kind = ADAPTER_KIND

    def __init__(self, engine, artifact_root, protected_cases, *, backend='numpy'):
        self.engine = engine
        self.root = Path(artifact_root).resolve()
        self.protected_cases = protected_cases
        self.backend = backend

    def _cases(self):
        cases = self.protected_cases() if callable(self.protected_cases) else self.protected_cases
        return sorted((case for case in cases if case.protected and case.mode == 'active'
                       and case.origin in GATING_CASE_ORIGINS), key=lambda case: case.id)

    def _eligible_episode(self, tenant, row):
        if row.get('status') != 'resolved' or self._label(row) is None:
            return False
        sources = [self.engine.get_evidence(tenant, cid) for cid in row.get('source_cids', [])]
        # The features come from the user's request, never the assistant answer.
        # Assistant evidence remains linked for erasure but is not a fact source.
        inputs = [s.cid for s in sources if s is not None and s.actor != 'assistant']
        if not any(s is not None and s.actor == 'user' and s.content == row.get('user_text') for s in sources):
            return False
        if not projection_sources_readable(
            self.engine, inputs, tenant_id=tenant, branch='main',
            filt={'tenant_id': tenant, 'user_id': row['user_id'], 'principal': row['user_id']},
            policy=self.engine.policy,
        ):
            return False
        return bool(sources) and all(
            s is not None and s.user_id == row['user_id'] and s.retired_at is None
            and not is_write_tainted(s.capability_tags)
            and not any(s.metadata.get(key) for key in ('synthetic', 'historical', 'imported', 'imported_from'))
            and not s.metadata.get('quarantine_reason')
            and isinstance(s.metadata.get('provenance', {}), dict)
            and not any(s.metadata.get('provenance', {}).get(key) for key in
                        ('synthetic', 'historical', 'imported', 'imported_from'))
            and s.metadata.get('origin') not in {'imported', 'external', 'synthetic'}
            and (s.actor == 'assistant' or s.trust_tier in {0, 1})
            for s in sources
        )

    @staticmethod
    def _label(row):
        value = reward([s for s in row.get('signals', []) if s['kind'] in {'tests', 'verifier'}
                        and s.get('source') not in EXCLUDED_SOURCES])
        return None if value in (None, 0) else int(value > 0)

    def configuration_fingerprint(self):
        return _digest({'backend': self.backend, 'feature_space': self._feature_fingerprint()})

    def _feature_fingerprint(self):
        embedding = self.engine.adapters.embedding
        return _digest({'embedding_type': type(embedding).__module__ + '.' + type(embedding).__qualname__,
                        **{key: getattr(embedding, key, None) for key in ('name', 'model', 'model_name', 'dims', 'dimensions')}})

    def propose(self, tenant_id, lessons, procedures, source_ids, immutable_rails):
        allowed = set(source_ids)
        items = [item for item in [*lessons, *procedures] if item.id in allowed]
        ids = {eid for item in items for eid in item.source_episode_ids}
        state = build_learning_runtime(self.engine).writer.read(tenant_id)
        training = [row for eid, row in sorted(state['episodes'].items())
                    if eid in ids and self._eligible_episode(tenant_id, row)]
        owners = {row['user_id'] for row in training}
        if len(owners) != 1:
            raise ValueError('Local training requires one source owner per adapter.')
        owner = next(iter(owners))
        self._require_labels(training, 'training')
        source_cids = {cid for row in training for cid in row['source_cids']}
        queries = {' '.join(row['user_text'].lower().split()) for row in training}
        heldout = [row for eid, row in sorted(state['episodes'].items())
                   if eid not in ids and row.get('user_id') == owner
                   and self._eligible_episode(tenant_id, row)
                   and not source_cids.intersection(row['source_cids'])
                   and ' '.join(row['user_text'].lower().split()) not in queries]
        self._require_labels(heldout, 'independent held-out evaluation')
        cases = self._cases()
        # A case's own query cannot double as an outcome training example.
        if queries.intersection(' '.join(case.query.lower().split()) for case in cases):
            raise ValueError('Training source overlaps protected evaluation query.')
        for case in cases:
            result = self.engine.retrieve(case.query, tenant_id=tenant_id, record_access=False,
                                          deep=case.tier != 'smoke', filt={'user_id': owner, 'principal': owner})
            for hit in result.hits:
                if case.expected_substring.strip() and case.expected_substring.lower() in hit.text.lower():
                    refs = {hit.id, *hit.provenance, *hit.metadata.get('source_evidence_cids', [])}
                    if refs.intersection(source_cids):
                        raise ValueError('Training source overlaps protected evaluation evidence.')
        features = self.engine.adapters.embedding.embed_many([e['user_text'] for e in training])
        model = train_logistic_adapter(features, [self._label(e) for e in training], backend=self.backend)
        model['provenance'] = {
            'tenant_id': tenant_id, 'user_id': owner, 'source_ids': sorted(allowed),
            'training_ids': [e['id'] for e in training], 'heldout_ids': [e['id'] for e in heldout],
            'episode_hashes': {e['id']: _digest(e) for e in training + heldout},
            'native_sources': {sid: _digest(state['artifacts'][sid]) for sid in allowed
                               if sid in state['artifacts']},
            'protected_hash': _digest([case.to_dict() for case in cases]),
            'feature_space': self._feature_fingerprint(),
            'reward_signal': 'external_only',
        }
        key = _digest(model)
        _write(self.root / (key + '.json'), model)
        return {'adapter_kind': self.adapter_kind, 'artifact_ref': key,
                'metrics': {'training_examples': len(training), 'heldout_examples': len(heldout),
                            'source_mutation_rate': 0.0},
                'metadata': {'reward_signal': 'external_only', 'monotonic_trust': True,
                             'eval_source_overlap': False, 'target_sink': 'parametric_adapter'}}

    @staticmethod
    def _require_labels(rows, name):
        if len(rows) < 4 or len({LocalMemoryTrainer._label(row) for row in rows}) < 2:
            raise ValueError(f'Local adapter requires at least four verified {name} outcomes with positive and negative labels.')

    def _load(self, ref, tenant):
        if not isinstance(ref, str) or len(ref) != 64 or any(c not in '0123456789abcdef' for c in ref):
            raise ValueError('Invalid local adapter reference.')
        path = (self.root / (ref + '.json')).resolve()
        if path.parent != self.root:
            raise ValueError('Local adapter escaped artifact root.')
        model = json.loads(path.read_text())
        if _digest(model) != ref or model['provenance']['tenant_id'] != tenant:
            raise ValueError('Local adapter identity or digest mismatch.')
        return model

    def _validate(self, model, state):
        p = model['provenance']
        if p['feature_space'] != self._feature_fingerprint():
            raise ValueError('Embedding feature space changed; retraining required.')
        if _digest([case.to_dict() for case in self._cases()]) != p['protected_hash']:
            raise ValueError('Protected evaluation suite changed; reevaluation required.')
        for eid, expected in p['episode_hashes'].items():
            row = state['episodes'].get(eid)
            if not row or _digest(row) != expected or not self._eligible_episode(p['tenant_id'], row):
                raise ValueError('Adapter outcome evidence changed or lost source custody.')
        # Native sources must still be active and admitted. Curated sources are
        # validated by the tier at proposal and do not exist in native storage.
        for sid in p['source_ids']:
            row = state['artifacts'].get(sid)
            if row and (row.get('erased') or row.get('state') != 'active' or not row.get('gate_passed')):
                raise ValueError('Adapter source artifact is no longer admitted.')
        for sid, expected in p['native_sources'].items():
            if _digest(state['artifacts'].get(sid)) != expected:
                raise ValueError('Adapter source artifact changed or was removed.')

    def _protected_results(self, tenant, user, cases):
        passed, failed = [], []
        filt = {'user_id': user, 'agent_id': 'parametric-evaluator'}
        for case in cases:
            result = self.engine.retrieve(case.query, tenant_id=tenant,
                                          deep=case.tier != 'smoke', record_access=False, filt=filt)
            rendered = '\n'.join(hit.text for hit in result.hits)
            ok = bool(case.expected_substring.strip()) and not result.abstained and case.expected_substring.lower() in rendered.lower()
            (passed if ok else failed).append(case.id)
        return passed, failed

    def evaluate(self, artifact, provider, protected_cases):
        from mnemosyne.parametric import protected_suite_is_gating

        if not protected_suite_is_gating(protected_cases):
            raise ValueError('Active non-synthetic protected regression suite required.')
        model = self._load(provider['artifact_ref'], artifact.tenant_id)
        state = build_learning_runtime(self.engine).writer.read(artifact.tenant_id)
        self._validate(model, state)
        p = model['provenance']
        if _digest([case.to_dict() for case in sorted(protected_cases, key=lambda case: case.id)]) != p['protected_hash']:
            raise ValueError('Evaluation must run the complete protected suite.')
        heldout = [state['episodes'][eid] for eid in p['heldout_ids']]
        features = self.engine.adapters.embedding.embed_many([row['user_text'] for row in heldout])
        baseline_loss, candidate_loss = 0.0, 0.0
        for row, feature in zip(heldout, features, strict=True):
            label = self._label(row)
            receipts = row.get('receipt_ids', [])
            receipt = state['receipts'].get(receipts[-1], {}) if receipts else {}
            baseline = receipt.get('baseline_prediction')
            if baseline is None and not receipt.get('parametric_prediction'):
                baseline = receipt.get('raw_prediction')
            if baseline is None:
                raise ValueError('Held-out evaluation requires a retained pre-adapter prediction.')
            from mnemosyne.experience.runtime import calibrate_prediction
            predicted = calibrate_prediction(0.5 * baseline + 0.5 * score(model, feature), state)
            baseline = float(row['prediction'])
            baseline_loss += (baseline - label) ** 2
            candidate_loss += (predicted - label) ** 2
        improvement = (baseline_loss - candidate_loss) / len(heldout)
        passed, failed = self._protected_results(artifact.tenant_id, p['user_id'], protected_cases)
        gate = GateResult(artifact.id, not failed and improvement > 0.01,
                          list(failed), list(failed), passed, improvement, None)
        artifact.metrics.update(heldout_brier_improvement=improvement,
                                baseline_brier=baseline_loss / len(heldout),
                                candidate_brier=candidate_loss / len(heldout))
        return gate

    def _active_path(self, tenant, user):
        return self.root / 'active' / (_digest([tenant, user]) + '.json')

    def activate(self, artifact, provider):
        model = self._load(provider['artifact_ref'], artifact.tenant_id)
        state = build_learning_runtime(self.engine).writer.read(artifact.tenant_id)
        self._validate(model, state)
        if artifact.status != 'promoted':
            raise ValueError('Only a measured promoted adapter can activate.')
        _write(self._active_path(artifact.tenant_id, model['provenance']['user_id']),
               {'artifact_id': artifact.id, 'artifact_ref': provider['artifact_ref']})

    def predict(self, tenant, user, query, baseline, *, state=None):
        path = self._active_path(tenant, user)
        if not path.exists():
            return None
        try:
            active = json.loads(path.read_text())
            model = self._load(active['artifact_ref'], tenant)
            if model['provenance']['user_id'] != user:
                return None
            state = state or build_learning_runtime(self.engine).writer.read(tenant)
            self._validate(model, state)
            if self._protected_results(tenant, user, self._cases())[1]:
                return None
            feature = self.engine.adapters.embedding.embed_many([query])[0]
            prediction = 0.5 * baseline + 0.5 * score(model, feature)
            if not math.isfinite(prediction):
                return None
            return {'artifact_id': active['artifact_id'], 'prediction': prediction}
        except (ValueError, KeyError, OSError, TypeError):
            return None

    def rollback(self, artifact, reason, protected_cases=None):
        directory = self.root / 'active'
        for path in directory.glob('*.json') if directory.exists() else []:
            if json.loads(path.read_text()).get('artifact_id') == artifact.id:
                path.unlink()
        return {'rollback_ref': 'local-memory-adapter:' + artifact.id,
                'metrics': {'rolled_back': 1.0, 'source_mutation_rate': 0.0},
                'metadata': {'rollback_provider_authorized': True}}

    def prediction_is_current(self, tenant, user, prediction, state):
        """Recheck source and activation identity without calling providers."""
        try:
            active = json.loads(self._active_path(tenant, user).read_text())
            if active['artifact_id'] != prediction['artifact_id']:
                return False
            model = self._load(active['artifact_ref'], tenant)
            if model['provenance']['user_id'] != user:
                return False
            self._validate(model, state)
            return True
        except (ValueError, KeyError, OSError, TypeError):
            return False
