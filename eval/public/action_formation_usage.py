"""Descriptive provider-reported usage; no pricing, admission or quality score."""

import argparse
import base64
import hashlib
from pathlib import Path

from eval.public.action_formation_replay import _json, _read
from eval.public.bundle import _canonical

COUNTERS = ('prompt_eval_count', 'eval_count', 'total_duration', 'load_duration',
            'prompt_eval_duration', 'eval_duration')


def summarize(paths):
    paths = [Path(path) for path in paths]
    if not paths or len(paths) > 10000:
        raise ValueError('supply between one and 10000 provider log files')
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError('duplicate provider log')
    calls = []
    total_bytes = 0
    for path in paths:
        raw = _read(path)
        total_bytes += len(raw)
        if total_bytes > 128 * 1024 * 1024:
            raise ValueError('usage logs exceed aggregate limit')
        lines = raw.splitlines()
        if len(lines) > 100 or any(len(line) > 4 * 1024 * 1024 for line in lines):
            raise ValueError('provider log exceeds record bounds')
        rows = [_json(line, 'provider usage record') for line in lines]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError('invalid provider record')
        configs = [row for row in rows if row.get('stage') == 'configuration']
        responses = [row for row in rows if row.get('stage') == 'chat_response']
        if len(configs) != 1 or len(responses) > 1:
            raise ValueError('expected one provider invocation per log')
        config = configs[0]
        if config.get('schema') != 'm12-ollama-formation-attempt/v1':
            raise ValueError('unsupported provider log')
        counters = dict.fromkeys(COUNTERS)
        if responses:
            encoded = responses[0].get('raw_base64')
            if not isinstance(encoded, str):
                raise ValueError('missing retained provider response')
            response = _json(base64.b64decode(encoded, validate=True), 'provider response')
            if not isinstance(response, dict) or response.get('model') != config.get('model'):
                raise ValueError('provider model mismatch')
            for name in COUNTERS:
                value = response.get(name)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError('invalid provider usage counter')
                counters[name] = value
        if _read(path) != raw:
            raise ValueError('provider log changed during analysis')
        calls.append({'file': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                      'model': config.get('model'), 'prompt_profile': config.get('prompt_profile', 'contract-v1'),
                      'response_retained': bool(responses), 'terminal_stage': rows[-1].get('stage'),
                      'provider_reported': counters})
    totals = {}
    for name in COUNTERS:
        known = [call['provider_reported'][name] for call in calls
                 if call['provider_reported'][name] is not None]
        totals[name] = {'known_sum': sum(known), 'known_calls': len(known),
                        'missing_calls': len(calls) - len(known),
                        'complete_total': sum(known) if len(known) == len(calls) else None}
    return {'schema': 'm12-provider-usage-diagnostic/v1', 'invocations': len(calls),
            'calls': calls, 'totals': totals, 'duration_unit': 'nanoseconds',
            'wall_elapsed_seconds': None, 'monetary_cost': None,
            'provider_reported_not_attested': True, 'publishable': False,
            'resource_admission_verified': False, 'ranking_eligible': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', nargs='+', type=Path)
    print(_canonical(summarize(parser.parse_args().logs)).decode(), end='')
