#!/usr/bin/env python3
"""Reject treating a pair's 32 tasks as 32 independent resampling units."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

archive = Path(__file__).resolve().parent
record_path = archive/'configs/recorder-ops-statistics-contract.json'
assert not record_path.exists(), 'Do not restart a recorded statistics check'
source = archive/'recorder_ops_statistics.py'
test = archive/'test_recorder_ops_statistics.py'
original = source.read_bytes()
needle = b'for _ in rows]'
assert original.count(needle) == 1
mutant = original.replace(needle, b'for _ in range(len(rows)*32)]')
digest = lambda b: hashlib.sha256(b).hexdigest()
with tempfile.TemporaryDirectory(prefix='recorder-pair-statistics-') as directory:
    root = Path(directory)
    shutil.copyfile(test, root/test.name)
    (root/source.name).write_bytes(mutant)
    red_path = archive/'raw/recorder-ops-statistics-unit-red.log'
    with red_path.open('w') as stream:
        red = subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', str(root), '-p', test.name], stdout=stream, stderr=subprocess.STDOUT)
    assert red.returncode != 0 and 'AssertionError' in red_path.read_text()
assert source.read_bytes() == original
green_path = archive/'raw/recorder-ops-statistics-unit-green.log'
with green_path.open('w') as stream:
    green = subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', str(archive), '-p', test.name], stdout=stream, stderr=subprocess.STDOUT)
assert green.returncode == 0 and source.read_bytes() == original
record_path.write_text(json.dumps(dict(source_sha256=digest(original), test_sha256=digest(test.read_bytes()),
    mutant_sha256=digest(mutant), mutation_scope='isolated two-file copy only', main_source_unchanged=True,
    red_exit=red.returncode, green_exit=green.returncode, red_log_sha256=digest(red_path.read_bytes()),
    green_log_sha256=digest(green_path.read_bytes()), success=True), indent=2)+'\n')
print('RECORDER_OPS_STATISTICS_CONTRACT_OK event_count_inflation_rejected=1 main_source_unchanged=1')
