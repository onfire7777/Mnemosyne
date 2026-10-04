import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from eval.public.monitor import run_monitored, macos_memory_pressure

root = Path(__file__).resolve().parent
repo = Path.cwd()
python = str(repo / '.superpowers/sdd/completion-2026-10-04/verified-venv/bin/python')
model = 'qwen3:0.6b'
digest = '7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435'
os.environ['TMPDIR'] = str(root / 'scratch')
argv = [python, '-m', 'eval.public.action_formation_run', '--output', str(root / 'workload'),
        '--provider-identity', 'ollama/qwen3:0.6b@' + digest + '; development formation role',
        '--timeout-seconds', '150', '--', python, '-m', 'eval.public.action_formation_ollama',
        '--model', model, '--digest', digest, '--evidence-dir', str(root / 'workload/provider-http')]
(root / 'plan.json').write_text(json.dumps({'source_commit': '88a56f24', 'model': model,
    'digest': digest, 'argv': argv, 'corpus': 'all 220 conversations in frozen order',
    'publishable': False, 'resource_admission': False,
    'rss_scope': 'client process group only; Ollama server excluded'}, indent=2) + '\n')

def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request('http://127.0.0.1:11434' + path, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=5) as response:
        return json.load(response)

with (root / 'server-samples.jsonl').open('x') as log:
    def pressure():
        value = macos_memory_pressure()
        log.write(json.dumps({'pressure': value, 'server': request('/api/ps')}) + '\n')
        log.flush()
        return value
    result = run_monitored(argv, cwd=repo, output_dir=root / 'monitor', wall_seconds=1800,
                           pressure_probe=pressure, usage_roots=[root])
try:
    cleanup = {'before': request('/api/ps'),
               'unload': request('/api/generate', {'model': model, 'keep_alive': 0, 'stream': False}),
               'after': request('/api/ps')}
except Exception as error:
    cleanup = {'error_type': type(error).__name__}
(root / 'cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n')
print(json.dumps(result))
sys.exit(0 if result['status'] == 'succeeded' else 1)
