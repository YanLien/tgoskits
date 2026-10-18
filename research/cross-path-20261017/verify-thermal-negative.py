#!/usr/bin/env python3
"""Check a zero-sample expected rejection despite one inserted runner diagnostic."""
import hashlib
import json
from pathlib import Path
import re

archive=Path(__file__).resolve().parent
name='thermal-qemu-unavailable-32'
raw_path=archive/'raw'/(name+'.log')
raw_bytes=raw_path.read_bytes()
raw=raw_bytes.decode('utf-8')
provenance=json.loads((archive/'configs'/name/'provenance.json').read_text())
sha=hashlib.sha256(raw_bytes).hexdigest()
assert provenance['exit_code']==1 and provenance['raw_log_sha256']==sha
assert 'VIRQ_THERMAL_CONFIG enabled=1 ' in raw and 'AXTEST_SUITE_FAIL failed=1' in raw
for marker in ('VIRQ_HOST_SAMPLE ','VIRQ_ISR_SAMPLE ','VIRQ_PHYSICAL_ARM ','VIRQ_LINUX_BOOT ','VIRQ_THERMAL_SAMPLE '):
    assert marker not in raw
match=re.search(r'^AXVM_TEST_FAILED (.*?)\r?\nnot ok 1 ',raw,re.M|re.S)
assert match,'missing complete failed-case diagnostic'
fragment=match.group(1)
announcement=re.compile(r'\r?\n=== FAIL PATTERN MATCHED: AXVM_TEST_FAILED\r?\n')
assert len(announcement.findall(fragment))==1
joined=announcement.sub('',fragment,count=1).strip()
assert joined=='required SoC temperature unavailable: thermal converter is not ready',repr(joined)
result=dict(name=name,expected_admission_rejection=True,measurement_accepted=False,task_observations=0,
    raw_log_sha256=sha,original_raw_unchanged=True,diagnostic=joined,
    inserted_runner_announcements=1,
    scope='Only the failed-case diagnostic is reconstructed to verify its cause; raw bytes are unchanged, no measurement data repaired or accepted')
(archive/'results/thermal-negative-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print('THERMAL_NEGATIVE_OK unavailable=1 vm_samples=0 raw_unchanged=1')
