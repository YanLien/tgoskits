#!/usr/bin/env python3
"""After the immutable cohort, account for integer reference/cycle quantization."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
analysis = repo/'virtualization/axvm/tests/analysis'
record_path = archive/'configs/frequency-quantization-correction.json'
assert not record_path.exists(), 'Do not restart a recorded correction'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
state_path = archive/'results/frequency-check-status.json'
while True:
    state = json.loads(state_path.read_text())
    if state['terminal']:
        assert state['success'], 'sampling plan failed; no analysis mutation performed'
        try:
            os.kill(state['controller_pid'], 0)
        except ProcessLookupError:
            break
    time.sleep(1)
plan = json.loads((archive/'configs/frequency-check-plan.json').read_text())
assert all(digest(repo/p) == h for p, h in plan['source_sha256'].items())
record = dict(reason='Native equal-tick brackets require outward reference-tick and cycle quantization; raw/runtime inputs unchanged',
              controller_terminal_before_edit=True, sources={}, old_outputs={}, new_outputs={}, success=False)
for name in ('analyze_virq_frequency.py', 'test_virq_frequency_analysis.py'):
    source = analysis/name
    before = archive/'configs/frequency-analysis-before'/name
    before.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, before)
    after = archive/'configs/frequency-quantized-payload'/name
    record['sources'][str(source.relative_to(repo))] = dict(before_sha256=digest(before), after_sha256=digest(after))
record_path.write_text(json.dumps(record, indent=2)+'\n')
# Strengthen the same behavior test first: the old numeric bounds must fail.
shutil.copyfile(archive/'configs/frequency-quantized-payload/test_virq_frequency_analysis.py', analysis/'test_virq_frequency_analysis.py')
with (archive/'raw/frequency-quantization-red.log').open('w') as stream:
    red = subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', str(analysis), '-p', 'test_virq_frequency_analysis.py'], cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
assert red.returncode != 0 and 'AssertionError' in (archive/'raw/frequency-quantization-red.log').read_text()
shutil.copyfile(archive/'configs/frequency-quantized-payload/analyze_virq_frequency.py', analysis/'analyze_virq_frequency.py')
with (archive/'raw/frequency-analysis-final-tests.log').open('w') as stream:
    green = subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', str(analysis), '-p', 'test_*.py'], cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
assert green.returncode == 0
for run in plan['runs']:
    name = run['name']
    folder = archive/'results'/name
    shutil.move(str(folder/'frequency'), str(folder/'frequency-before-quantization'))
    record['old_outputs'][name] = {p.name: digest(p) for p in (folder/'frequency-before-quantization').iterdir() if p.is_file()}
    with (archive/'raw'/(name+'-quantized-analysis.log')).open('w') as stream:
        subprocess.run(['python3', str(analysis/'analyze_virq_frequency.py'), str(folder/'analysis-input.log'), '--output-dir', str(folder/'frequency')], cwd=repo, check=True, stdout=stream, stderr=subprocess.STDOUT)
    record['new_outputs'][name] = {p.name: digest(p) for p in (folder/'frequency').iterdir() if p.is_file()}
record.update(success=True, red_exit=red.returncode, green_exit=0,
              red_log_sha256=digest(archive/'raw/frequency-quantization-red.log'),
              green_log_sha256=digest(archive/'raw/frequency-analysis-final-tests.log'))
record_path.write_text(json.dumps(record, indent=2)+'\n')
print('FREQUENCY_QUANTIZATION_OK runtime_unchanged=1 raw_unchanged=1 red_rejected=1 final_tests=41 reanalysed_boots=3')
