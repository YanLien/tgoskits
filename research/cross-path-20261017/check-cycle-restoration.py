#!/usr/bin/env python3
"""With no live cohorts, prove the real PMU test detects truncated restoration."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
source = repo/'components/axcpu/src/arch/aarch64/pmu/cycle_scope.rs'
out = archive/'configs/frequency-restoration-contract.json'
assert not out.exists(), 'Do not restart a recorded contract check'
original = source.read_bytes()
needle = b'write_reg!("PMCCNTR_EL0", self.value);'
assert original.count(needle) == 1
mutant = original.replace(needle, b'write_reg!("PMCCNTR_EL0", u64::from(self.value as u32));')
digest = lambda b: hashlib.sha256(b).hexdigest()
cmd = ['cargo', 'xtask', 'arceos', 'test', 'qemu', '--arch', 'aarch64', '--test-group', 'cpu', '--test-case', 'pmu']
record = dict(command=cmd, original_sha256=digest(original), mutant_sha256=digest(mutant),
              scope='Temporary main-tree mutation only while all build and cohort jobs are stopped; finally restores exact original bytes')
out.write_text(json.dumps(record, indent=2)+'\n')
try:
    source.write_bytes(mutant)
    red = archive/'raw/frequency-cycle-truncation-red.log'
    with red.open('w') as stream:
        result = subprocess.run(cmd, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
    assert result.returncode != 0, 'truncated cycle restoration escaped detection'
    assert 'temporary scope destroyed saved state' in red.read_text(errors='replace')
    record['red_exit_code'] = result.returncode
    record['red_log_sha256'] = digest(red.read_bytes())
finally:
    source.write_bytes(original)
    assert source.read_bytes() == original
    record['source_restored'] = True
    out.write_text(json.dumps(record, indent=2)+'\n')
green = archive/'raw/frequency-cycle-restoration-green.log'
with green.open('w') as stream:
    result = subprocess.run(cmd, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
assert result.returncode == 0
assert 'CPU_PMU_OK' in green.read_text() and 'result: 1/1 case(s) passed' in green.read_text()
assert source.read_bytes() == original
record.update(green_exit_code=0, green_log_sha256=digest(green.read_bytes()), success=True)
out.write_text(json.dumps(record, indent=2)+'\n')
print('CYCLE_RESTORATION_CONTRACT_OK red_rejected=1 source_restored=1 green_passed=1')
