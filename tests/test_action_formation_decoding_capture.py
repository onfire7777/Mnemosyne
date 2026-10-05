import base64
import hashlib
import json
from pathlib import Path

import pytest

from eval.public.action_formation import validate_response


def test_decoding_comparison_retains_failures_and_changes_only_format():
    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-formation-decoding-diagnostic-2026-10-04'
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    inputs = json.loads((root / 'inputs.json').read_text())
    assert len(inputs) == 11
    for index, request in enumerate(inputs):
        bodies = []
        for mode in ('json', 'schema'):
            cell = f'{index:02d}-{mode}'
            paths = list((root / cell).glob('*.jsonl'))
            assert len(paths) == 1
            rows = [json.loads(line) for line in paths[0].read_text().splitlines()]
            sent = next(r for r in rows if r['stage'] == 'chat_request')
            raw = base64.b64decode(sent['request_body_base64'])
            assert hashlib.sha256(raw).hexdigest() == sent['request_body_sha256']
            body = json.loads(raw)
            assert json.loads(body['messages'][1]['content']) == request
            response = json.loads(base64.b64decode(next(r for r in rows if r['stage'] == 'chat_response')['raw_base64']))
            output = (root / f'{cell}.txt').read_bytes()
            assert output == response['message']['content'].encode()
            recorded = json.loads((root / f'{cell}.json').read_text())
            kwargs = {'allowed_actions': {a['action_id'] for a in request['conversation']['actions']}, 'existing_tasks': set()}
            if recorded['status'] == 'failed':
                with pytest.raises(ValueError):
                    validate_response(output, **kwargs)
            else:
                assert validate_response(output, **kwargs) == recorded['response']
            bodies.append(body)
        assert bodies[0]['format'] == 'json'
        assert isinstance(bodies[1]['format'], dict)
        bodies[1]['format'] = bodies[0]['format']
        assert bodies[0] == bodies[1]
    assert json.loads((root / 'cleanup.json').read_text())['models'] == []
