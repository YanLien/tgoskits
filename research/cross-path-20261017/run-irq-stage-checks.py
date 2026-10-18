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
plan_path = archive/'configs/irq-stage-check-plan.json'
assert not plan_path.exists(), 'Existing plan must be inspected, not restarted'
runs = [dict(name='irq-stages-board-memory-sgi-32', runtime='board', scenario='linux_memory', pressure='sgi', mode='on'),
        dict(name='irq-stages-qemu-lower-32', runtime='qemu', scenario='baseline', pressure='off', mode='on', lower=True),
        dict(name='irq-stages-qemu-off-32', runtime='qemu', scenario='linux_cpu', pressure='off', mode='off')]
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
plan = dict(runs=runs, source_sha256=baseline['source_sha256'],
            host_source_sha256=baseline['host_source_sha256'], cargo_lock_sha256=baseline['cargo_lock_sha256'],
            controls={str(p.relative_to(repo)):digest(p) for p in (
                Path(__file__),archive/'run-native-timechain.sh',archive/'run-irq-stages-lower.sh',archive/'verify-irq-stages.py')},
            scope='Directed functional/path validation, not a randomized interference or probe-cost experiment', M1=False,M2=False)
plan_path.write_text(json.dumps(plan,indent=2)+'\n')
state = dict(controller_pid=os.getpid(),started_unix=time.time(),terminal=False,success=False,completed=[],active_run=None)

def save():
    (archive/'results/irq-stage-check-status.json').write_text(json.dumps(state,indent=2)+'\n')

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
    call(['python3',str(archive/'verify-irq-stages.py'),'irq-stages-qemu-current-32'])
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
    print('IRQ_STAGE_CHECKS_DONE on_runs=3 off_runs=1 samples=256',flush=True)
except BaseException as error:
    state.update(terminal=True,success=False,error=repr(error),finished_unix=time.time());save()
    raise
