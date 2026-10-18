#!/usr/bin/env python3
"""Run remaining directed stage checks serially, preserving shared build artifacts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
baseline = json.loads((archive/'configs/irq-stages-qemu-current-32/provenance.json').read_text())
previous=json.loads((archive/'results/irq-stage-check-status.json').read_text())
assert previous['terminal'] and not previous['success']
assert previous['completed'] == ['irq-stages-board-memory-sgi-32']
assert previous['active_run'] == 'irq-stages-qemu-lower-32'
assert json.loads((archive/'configs/irq-stages-qemu-lower-32/provenance.json').read_text())['exit_code'] == 1
manifest='virtualization/axvm/tests/vcpu-runtime/irq-stages/host-initramfs.toml'
assert manifest not in baseline['source_sha256']
assert (repo/manifest).read_bytes() == (repo/'virtualization/axvm/tests/vcpu-runtime/host-initramfs.toml').read_bytes()
baseline['source_sha256']=dict(baseline['source_sha256'])
baseline['source_sha256'][manifest]=hashlib.sha256((repo/manifest).read_bytes()).hexdigest()
plan_path = archive/'configs/irq-stage-recovery-plan.json'
assert not plan_path.exists(), 'Existing plan must be inspected, not restarted'
runs = [dict(name='irq-stages-qemu-lower-resources-32', runtime='qemu', scenario='baseline', pressure='off', mode='on', lower=True),
        dict(name='irq-stages-qemu-off-32', runtime='qemu', scenario='linux_cpu', pressure='off', mode='off')]
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
plan = dict(runs=runs, source_sha256=baseline['source_sha256'],
            host_source_sha256=baseline['host_source_sha256'], cargo_lock_sha256=baseline['cargo_lock_sha256'],
            recovery_reason='Missing host-initramfs sidecar in new lower-EL config directory; old failed attempt preserved, no accepted data',
            source_additions={manifest:baseline['source_sha256'][manifest]},
            controls={str(p.relative_to(repo)):digest(p) for p in (
                Path(__file__),archive/'run-native-timechain.sh',archive/'run-irq-stages-lower.sh',archive/'verify-irq-stages.py')},
            scope='Directed functional/path validation, not a randomized interference or probe-cost experiment', M1=False,M2=False)
plan_path.write_text(json.dumps(plan,indent=2)+'\n')
state = dict(controller_pid=os.getpid(),started_unix=time.time(),terminal=False,success=False,completed=[],active_run=None)

def save():
    (archive/'results/irq-stage-recovery-status.json').write_text(json.dumps(state,indent=2)+'\n')

def check_sources():
    for key in ('source_sha256','host_source_sha256'):
        assert all(digest(repo/p) == h for p,h in plan[key].items()), 'sources changed'
    assert digest(repo/'Cargo.lock') == plan['cargo_lock_sha256']
    assert all(digest(repo/p) == h for p,h in plan['controls'].items()), 'controls changed'

def call(command,env=None):
    subprocess.run(command,cwd=repo,check=True,env=env)

save()
try:
    check_sources()
    for name in ('irq-stages-qemu-current-32','irq-stages-board-memory-sgi-32'):
        assert json.loads((archive/'results'/name/'stages/summary.json').read_text())['samples'] == 64
    for run in runs:
        check_sources()
        state['active_run']=run['name'];save()
        print('IRQ_STAGE_CHECK_BEGIN '+run['name'],flush=True)
        env=dict(os.environ,VIRQ_RECORDING=run['mode'])
        if run.get('lower'):
            command=['sh',str(archive/'run-irq-stages-lower.sh'),run['name']]
        else:
            command=['sh',str(archive/'run-native-timechain.sh'),run['name'],run['runtime'],run['scenario'],run['pressure']]
        call(command,env=env)
        check_sources()
        provenance=json.loads((archive/'configs'/run['name']/'provenance.json').read_text())
        assert all(provenance[k] == plan[k] for k in ('source_sha256','host_source_sha256','cargo_lock_sha256'))
        call(['python3',str(archive/'verify-irq-stages.py'),run['name']]+(['--off'] if run['mode']=='off' else []))
        state['completed'].append(run['name']);state['active_run']=None;save()
    state.update(terminal=True,success=True,finished_unix=time.time());save()
    print('IRQ_STAGE_RECOVERY_DONE on_runs=1 off_runs=1 samples=128',flush=True)
except BaseException as error:
    state.update(terminal=True,success=False,error=repr(error),finished_unix=time.time());save()
    raise
