"""Run the installed skill locally with a 25-second outer deadline."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'repro_outputs'
FILES = ['README.md', 'setup.py', 'micrograd/__init__.py',
         'micrograd/engine.py', 'micrograd/nn.py', 'test/test_engine.py']

def snapshot():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in FILES}

before = snapshot()
(OUT / 'source_hashes_before.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
env = os.environ.copy()
overrides = {'RIGORPILOT_LESSONS': '0', 'CUDA_VISIBLE_DEVICES': '',
             'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8',
             'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_ADDOPTS': '',
             'PYTEST_PLUGINS': ''}
env.update(overrides)
argv = [sys.executable, '.agents/skills/ai-research-reproduction/scripts/orchestrate_repro.py',
        '--repo', '.', '--output-dir', 'repro_outputs', '--run-selected',
        '--timeout', '18', '--no-gpu-monitor', '--user-language', 'zh-CN',
        '--source-adjacent-readme']
record = {'argv': argv, 'cwd': str(ROOT), 'environment_overrides': overrides,
          'outer_timeout_seconds': 25, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
(OUT / 'invocation.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
start = time.monotonic()
with (OUT / 'orchestrator.stdout.log').open('wb') as stdout, (OUT / 'orchestrator.stderr.log').open('wb') as stderr:
    process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
    try:
        record['exit_code'] = process.wait(timeout=25)
        record['timed_out'] = False
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=stderr, stderr=stderr, timeout=2)
        record['exit_code'] = process.wait(timeout=1)
        record['timed_out'] = True
record['elapsed_seconds'] = round(time.monotonic() - start, 3)
record['source_hashes_unchanged'] = snapshot() == before
(OUT / 'invocation.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False, indent=2))
for name in ['orchestrator.stdout.log', 'orchestrator.stderr.log']:
    print(name)
    print((OUT / name).read_text(encoding='utf-8', errors='replace'))
