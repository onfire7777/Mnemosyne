"""Concrete prohibited mutations used to prove learning guard detection."""
from copy import deepcopy
from types import SimpleNamespace

from mnemosyne.experience.receipts import digest
from mnemosyne.experience.store import empty_state
from mnemosyne.security import sanitize_retrieved_text


def source_lookup(cid):
    return SimpleNamespace(content='validate\nupload', erased=False) if cid == 'source' else None


def baseline():
    state = empty_state()
    state['receipts']['receipt'] = {
        'id': 'receipt', 'tenant_id': 't', 'user_id': 'u', 'session_id': 's', 'task_class': 'deploy',
        'prediction': .5, 'prediction_hash': digest(.5), 'query': 'Deploy inventory',
        'items': [{'kind': 'item', 'item_id': 'source', 'revision': 1}],
        'eligible_targets': [{'kind': 'item', 'item_id': 'source', 'revision': 1}],
        'created_at': '2026-11-05T12:00:00+00:00', 'mode': 'deliberate',
    }
    state['episodes']['episode'] = {
        'id': 'episode', 'tenant_id': 't', 'user_id': 'u', 'session_id': 's', 'task_class': 'deploy',
        'receipt_ids': ['receipt'], 'source_cids': ['source'], 'status': 'resolved',
        'signals': [{'kind': 'verifier', 'value': 1., 'weight': 1.}],
        'prediction': .5, 'reward': 1., 'rpe': 1., 'tool_events': [],
        'created_at': '2026-11-05T12:00:00+00:00',
    }
    content = 'validate\nupload'
    state['artifacts']['artifact'] = {
        'id': 'artifact', 'kind': 'procedure', 'revision': 1, 'state': 'probation',
        'content': content, 'steps': ['validate', 'upload'], 'task_class': 'deploy',
        'scope': 'deploy', 'conditions': [], 'goal': 'Deploy inventory',
        'source_cids': ['source'], 'source_episode_ids': ['episode'],
        'source_quotes': [{'episode_id': 'episode', 'cid': 'source', 'quote': content}],
        'explanation': 'The linked verifier records these steps.', 'explanation_sources': ['episode'],
        'gate_passed': True, 'needs_approval': False, 'origin': 'learned',
        'gate_evidence': {'passed': True, 'content_hash': digest(content),
                          'case_ids': ['case'], 'protected_case_ids': [], 'protected_passed': True},
        'sanitized': sanitize_retrieved_text(content, 5),
    }
    return state


def credit():
    return {'episode_id': 'episode', 'target_kind': 'item', 'target_id': 'source', 'revision': 1,
            'task_class': 'deploy', 'delta': 1., 'rate': .1, 'share': 1., 'trace': .8,
            'contingency_lb': .4, 'served_n': 20, 'control_n': 20}


def corrupt(code, before):
    after = deepcopy(before)
    artifact = after['artifacts']['artifact']
    policy = after['policy']
    if code == 'X1':
        after['stats']['uncredited'] = {'utility': 1.1}
    elif code == 'X2':
        policy['authority'] = 1
    elif code == 'X3':
        after['episodes']['other'] = deepcopy(after['episodes']['episode'])
    elif code == 'X4':
        policy['exploration_floor'] = 0
    elif code == 'X5':
        policy['positive_rate'] = .2
        policy['negative_rate'] = .1
    elif code == 'X6':
        receipt = deepcopy(after['receipts']['receipt'])
        receipt.update(id='fast', mode='fast', goal_checked=False)
        after['receipts']['fast'] = receipt
    elif code == 'X7':
        after['episodes']['episode']['signals'][0]['source'] = 'assistant'
    elif code == 'X8':
        policy['replayed'] = {'episode': 'not-the-current-outcome'}
    elif code == 'X9':
        artifact['scope'] = 'all-tasks'
    elif code == 'X10':
        before['artifacts']['artifact']['state'] = 'retired'
        artifact['state'] = 'probation'
    elif code == 'X11':
        artifact['sanitized']['instruction_authority'] = 'system'
    elif code == 'X12':
        after['receipts'].clear()
    elif code == 'X13':
        after['credit']['credit'] = {**credit(), 'delta': 0.}
    elif code == 'X14':
        after['stats']['inconsistent'] = {'alpha': 100., 'beta': 1., 'n': 0.}
    elif code == 'X15':
        artifact['source_cids'] = ['unrecorded-source']
    elif code == 'X16':
        artifact['confidence'] = .99
    elif code == 'X17':
        after['episodes']['erased'] = {'status': 'erased', 'user_text': 'secret'}
    elif code == 'X18':
        artifact['steps'] = ['upload', 'validate']
    elif code == 'X19':
        after['credit']['credit'] = {**credit(), 'rate': 0}
    elif code == 'X20':
        artifact['schema_ref'] = 'schema'
        artifact['source_quotes'] = [{'episode_id': 'episode', 'cid': 'source', 'quote': 'invented'}]
    elif code == 'X21':
        artifact['gate_evidence']['content_hash'] = 'unchecked-content'
    elif code == 'X22':
        artifact['novelty_reward'] = 1
    elif code == 'E1':
        policy['pattern_splits'] = {'split': {'before': [.8, .8], 'after': [.9, .7]}}
    elif code == 'E2':
        before['artifacts']['artifact']['state'] = 'active'
        artifact.update(state='active', chunk_ids=['missing-child'])
    elif code == 'E3':
        before['artifacts']['artifact']['state'] = 'active'
        artifact.update(state='active', replaces=['old'], abstraction_evaluation={
            'candidate_scores': [.7], 'original_scores': [.9]})
    elif code == 'E4':
        artifact['explanation_sources'] = []
    else:
        raise AssertionError(code)
    return after
