import base64
from copy import deepcopy
import json

import pytest

from eval.public.action_formation_ollama import SYSTEM_PROMPT, complete
from eval.public.action_implicit_plan import make_corpus, public_turn

DIGEST = 'a' * 64
MODEL = 'qwen3:0.6b'


def request():
    return {'schema': 'm12-formation-request/v1', 'conversation': public_turn(make_corpus()['cases'][0], 0),
            'current_tasks': [], 'prior_responses': [], 'response_contract': {}}


class Transport:
    def __init__(self):
        self.calls = []
        self.tags = {'models': [{'name': MODEL, 'digest': DIGEST}]}
        self.chat = {'model': MODEL, 'done': True, 'done_reason': 'stop',
                     'message': {'role': 'assistant', 'content': '{"operations":[],"clarification":null}'},
                     'prompt_eval_count': 20, 'eval_count': 8}

    def __call__(self, base, route, payload, timeout):
        self.calls.append((base, route, deepcopy(payload), timeout))
        return json.dumps(self.tags if route == '/api/tags' else self.chat).encode()


def logs(root):
    return [json.loads(line) for path in root.glob('*.jsonl') for line in path.read_text().splitlines()]


def test_exact_content_and_raw_http_evidence_without_gold_or_prompt_mutation(tmp_path):
    transport = Transport()
    supplied = request()
    before = deepcopy(supplied)
    result = complete(supplied, model=MODEL, digest=DIGEST, evidence_dir=tmp_path, transport=transport)
    assert result == transport.chat['message']['content'].encode()
    assert supplied == before
    assert [call[1] for call in transport.calls] == ['/api/tags', '/api/chat', '/api/tags']
    body = transport.calls[1][2]
    assert body['keep_alive'] == 0 and body['stream'] is body['think'] is False
    assert body['options']['num_thread'] == 2 and body['options']['temperature'] == 0
    assert body['messages'][0]['content'] == SYSTEM_PROMPT
    assert json.loads(body['messages'][1]['content']) == supplied
    records = logs(tmp_path)
    assert records[-1]['stage'] == 'completed'
    raw_chat = next(r for r in records if r['stage'] == 'chat_response')
    assert json.loads(base64.b64decode(raw_chat['raw_base64'])) == transport.chat
    assert records[0]['provider_identity_attested'] is False


@pytest.mark.parametrize('base', ['https://example.com', 'http://localhost:11434',
                                 'http://127.0.0.1:11434/other', 'http://user@127.0.0.1:11434',
                                 'http://127.0.0.1:11434?x=1'])
def test_reject_nonexplicit_loopback_origin(tmp_path, base):
    transport = Transport()
    with pytest.raises(ValueError, match='loopback'):
        complete(request(), model=MODEL, digest=DIGEST, evidence_dir=tmp_path,
                 base_url=base, transport=transport)
    assert not transport.calls


def test_no_generation_after_preflight_digest_mismatch(tmp_path):
    transport = Transport()
    with pytest.raises(ValueError, match='digest'):
        complete(request(), model=MODEL, digest='b' * 64, evidence_dir=tmp_path, transport=transport)
    assert len(transport.calls) == 1
    assert logs(tmp_path)[-1]['stage'] == 'failed'


def test_postflight_digest_change_preserves_raw_response_but_rejects_success(tmp_path):
    transport = Transport()

    def changed(base, route, body, timeout):
        if len(transport.calls) == 2:
            transport.tags['models'][0]['digest'] = 'b' * 64
        return transport(base, route, body, timeout)

    with pytest.raises(ValueError, match='digest'):
        complete(request(), model=MODEL, digest=DIGEST, evidence_dir=tmp_path, transport=changed)
    assert any(r['stage'] == 'chat_response' for r in logs(tmp_path))
    assert logs(tmp_path)[-1]['stage'] == 'failed'


@pytest.mark.parametrize('field,value', [('done_reason', 'length'), ('done', False), ('model', 'other')])
def test_incomplete_or_mismatched_response_is_not_success(tmp_path, field, value):
    transport = Transport()
    transport.chat[field] = value
    with pytest.raises(ValueError, match='incomplete'):
        complete(request(), model=MODEL, digest=DIGEST, evidence_dir=tmp_path, transport=transport)
    assert logs(tmp_path)[-1]['stage'] == 'failed'


def test_invalid_model_json_is_preserved_for_bridge_validation(tmp_path):
    transport = Transport()
    transport.chat['message']['content'] = 'this is not valid formation JSON'
    assert complete(request(), model=MODEL, digest=DIGEST, evidence_dir=tmp_path,
                    transport=transport) == b'this is not valid formation JSON'
    assert logs(tmp_path)[-1]['output_semantics_validated'] is False


def test_context_rejection_does_not_drop_history_or_call_model(tmp_path):
    supplied = request()
    supplied['conversation']['turns'][0]['text'] = 'large history ' * 2000
    transport = Transport()
    with pytest.raises(ValueError, match='context budget'):
        complete(supplied, model=MODEL, digest=DIGEST, evidence_dir=tmp_path, transport=transport)
    assert not transport.calls


def test_schema_mode_records_grammar_and_preserves_model_content(tmp_path):
    from eval.public.action_formation_schema import response_schema

    transport = Transport()
    supplied = request()
    content = complete(supplied, model=MODEL, digest=DIGEST, evidence_dir=tmp_path,
                       output_mode='schema', transport=transport)
    assert content == transport.chat['message']['content'].encode()
    assert transport.calls[1][2]['format'] == response_schema(supplied['conversation']['actions'])
    assert logs(tmp_path)[0]['output_mode'] == 'schema'
    assert len(logs(tmp_path)[0]['format_sha256']) == 64
