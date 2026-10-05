import base64
import hashlib
import json
from pathlib import Path


def test_paired_prompt_capture_preserves_all_inputs_outputs_and_only_prompt_difference():
    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-formation-semantic-diagnostic-2026-10-04'
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert manifest['publishable'] is manifest['ranking_eligible'] is manifest['task_execution'] is False
    inputs = json.loads((root / 'inputs.json').read_text())
    assert len(inputs) == 11
    for index, supplied in enumerate(inputs):
        bodies = []
        for profile in ('contract-v1', 'semantics-v2'):
            cell = f'{index:02d}-{profile}'
            paths = list((root / cell).glob('*.jsonl'))
            assert len(paths) == 1
            rows = [json.loads(line) for line in paths[0].read_text().splitlines()]
            assert rows[0]['prompt_profile'] == profile
            row = next(r for r in rows if r['stage'] == 'chat_request')
            raw = base64.b64decode(row['request_body_base64'])
            assert hashlib.sha256(raw).hexdigest() == row['request_body_sha256']
            body = json.loads(raw)
            assert json.loads(body['messages'][1]['content']) == supplied
            assert hashlib.sha256(body['messages'][0]['content'].encode()).hexdigest() == rows[0]['prompt_sha256']
            reply = json.loads(base64.b64decode(next(r for r in rows if r['stage'] == 'chat_response')['raw_base64']))
            assert reply['message']['content'].encode() == (root / (cell + '.txt')).read_bytes()
            bodies.append(body)
        assert bodies[0]['messages'][0] != bodies[1]['messages'][0]
        bodies[1]['messages'][0] = bodies[0]['messages'][0]
        assert bodies[0] == bodies[1]
    assert json.loads((root / 'cleanup.json').read_text())['models'] == []
    for index in (0, 5):
        for profile in ('contract-v1', 'semantics-v2'):
            response = json.loads((root / f'{index:02d}-{profile}.json').read_text())['response']
            assert response['operations'][0]['payload']['trigger']['type'] == 'exact_time'
