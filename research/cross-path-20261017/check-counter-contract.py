#!/usr/bin/env python3
"""Prove serialized counter reversals cannot be admitted as valid observations."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
source = repo/'virtualization/axvm/tests/analysis/analyze_virq_counter.py'
record_path = archive/'configs/counter-reversal-contract.json'
assert not record_path.exists(), 'Do not restart a recorded contract check'
original = source.read_bytes()
needle = b'(backwards or not positive)'
assert original.count(needle) == 1
mutant = original.replace(needle, b'(not positive)')
digest = lambda b: hashlib.sha256(b).hexdigest()
cmd = ['python3', '-m', 'unittest', 'discover', '-s', 'virtualization/axvm/tests/analysis', '-p', 'test_virq_counter_analysis.py']
record = dict(original_sha256=digest(original), mutant_sha256=digest(mutant), command=cmd)
try:
    source.write_bytes(mutant)
    red_path = archive/'raw/counter-reversal-red.log'
    with red_path.open('w') as stream:
        red = subprocess.run(cmd, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
    assert red.returncode != 0 and 'ValueError not raised' in red_path.read_text()
    record.update(red_exit=red.returncode, red_log_sha256=digest(red_path.read_bytes()))
finally:
    source.write_bytes(original)
    assert source.read_bytes() == original
    record['source_restored'] = True
    record_path.write_text(json.dumps(record, indent=2)+'\n')
green_path = archive/'raw/counter-reversal-green.log'
with green_path.open('w') as stream:
    green = subprocess.run(cmd, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
assert green.returncode == 0 and source.read_bytes() == original
record.update(green_exit=0, green_log_sha256=digest(green_path.read_bytes()), success=True)
record_path.write_text(json.dumps(record, indent=2)+'\n')
print('COUNTER_CONTRACT_OK reversal_mutant_rejected=1 original_bytes_restored=1 green_passed=1')
