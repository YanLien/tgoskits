#!/usr/bin/env python3
"""Check functional on/off execution and immutable workload identity in QEMU."""
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
identities, fixtures, environments, artifacts, results = {}, {}, {}, {}, {}
for mode in ('off','on'):
    name = f'recorder-cost-qemu-{mode}-32'
    config = archive/'configs'/name
    identity = json.loads((config/'provenance.json').read_text())
    identities[mode] = identity
    assert identity['exit_code'] == 0 and identity['runtime'] == 'qemu'
    assert identity['raw_log_sha256'] == digest(archive/'raw'/(name+'.log'))
    fixture = tomllib.loads((config/'measurement.toml').read_text())
    assert fixture.pop('recording') == mode
    fixtures[mode] = fixture
    environments[mode] = [s for s in (config/'environment.txt').read_text().splitlines()
                          if not s.startswith('VIRQ_RECORDING=')]
    artifacts[mode] = {p:digest(config/p) for p in ('realtime.elf','realtime.bin','realtime-input.dtb',
        'linux-input.dtb','zephyr.config','linux-build.json','realtime-vm.toml','linux-vm.toml')}
    results[mode] = json.loads((archive/'results'/name/'probe_cost/summary.json').read_text())
    assert results[mode]['recording_mode'] == mode
    assert results[mode]['complete_chain_accepted'] == (mode == 'on')
    assert sum(p['samples'] for p in results[mode]['policies'].values()) == 64
    assert results[mode]['linux_fences']['mode'] == 'serial'
assert fixtures['off'] == fixtures['on'] and environments['off'] == environments['on']
assert artifacts['off'] == artifacts['on']
assert all(identities['off'][k] == identities['on'][k]
           for k in ('source_sha256','host_source_sha256','cargo_lock_sha256'))
log = archive/'results/recorder-cost-qemu-off-32/analysis-input.log'
with (archive/'raw/recorder-off-full-chain-rejection.log').open('w') as stream:
    rejected = subprocess.run(['python3','virtualization/axvm/tests/analysis/analyze_virq_task.py',
        str(log),'--output-dir','/tmp/recorder-off-full-chain'],cwd=repo,
        stdout=stream,stderr=subprocess.STDOUT)
assert rejected.returncode != 0
assert 'disabled recorder cannot establish a complete runtime chain' in (archive/'raw/recorder-off-full-chain-rejection.log').read_text()
report = dict(same_fixed_inputs=True,same_sources=True,full_chain_tasks=64,task_only_observations=64,
    off_complete_chain_rejected=True,workload_artifact_sha256=artifacts['on'],
    scope='Functional on/off contract only; no hardware overhead conclusion',M1_complete=False,M2_complete=False)
(archive/'results/recorder-cost-qemu-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print('RECORDER_QEMU_IDENTITY_OK same_workload=1 tasks=128 off_complete_chain=0')
