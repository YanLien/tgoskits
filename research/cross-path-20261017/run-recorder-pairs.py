#!/usr/bin/env python3
"""Run prospectively ordered equal-work recorder pairs; stop at any failure."""
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
analysis = repo/'virtualization/axvm/tests/analysis'
prefix = 'recorder-cost-board'
plan_path = archive/'configs/recorder-cost-pair-plan.json'
status_path = archive/'results/recorder-cost-pair-status.json'
assert not plan_path.exists(), 'An existing plan must be inspected, not restarted'
seed = 20261017
orders = [['on','off'],['on','off'],['off','on'],['off','on']]
random.Random(seed).shuffle(orders)
baseline = json.loads((archive/'configs/recorder-cost-qemu-off-32/provenance.json').read_text())
qemu = json.loads((archive/'results/recorder-cost-qemu-audit.json').read_text())
assert qemu['same_fixed_inputs'] and qemu['off_complete_chain_rejected']
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
plan = dict(seed=seed, runtime='board', scenario='linux_cpu', irq_pressure='off',
            blocks=[dict(block=i+1,order=order,
                         runs=[dict(mode=mode,name=f'{prefix}-b{i+1:02d}-{mode}-32') for mode in order])
                    for i,order in enumerate(orders)],
            source_sha256=baseline['source_sha256'],
            host_source_sha256=baseline['host_source_sha256'],
            cargo_lock_sha256=baseline['cargo_lock_sha256'],
            controller_sha256=digest(Path(__file__)),
            wrapper_sha256=digest(archive/'run-native-timechain.sh'),
            limitations=['Recorder incremental cost only; residual probes retained.',
                         'Frequency/temperature unverified; exploratory comparison, M1 incomplete.',
                         'Within-boot events are not independent repetitions.'])
plan_path.write_text(json.dumps(plan,indent=2)+'\n')
state = dict(controller_pid=os.getpid(), started_unix=time.time(), completed=[],
             active_run=None, terminal=False, success=False)


def save():
    status_path.write_text(json.dumps(state,indent=2)+'\n')


def check_sources():
    for key in ('source_sha256','host_source_sha256'):
        assert all(digest(repo/p) == h for p,h in plan[key].items()), 'live sources changed'
    assert digest(repo/'Cargo.lock') == plan['cargo_lock_sha256']
    assert digest(archive/'run-native-timechain.sh') == plan['wrapper_sha256']


def call(command, stream=None, env=None):
    subprocess.run(command,cwd=repo,env=env,check=True,stdout=stream,stderr=subprocess.STDOUT)


save()
try:
    for block in plan['blocks']:
        for run in block['runs']:
            check_sources()
            name, mode = run['name'], run['mode']
            state['active_run'] = name
            save()
            print(f'RECORDER_PAIR_BEGIN block={block["block"]} mode={mode} name={name}',flush=True)
            env = dict(os.environ,VIRQ_RECORDING=mode)
            call(['sh',str(archive/'run-native-timechain.sh'),name,'board','linux_cpu','off'],env=env)
            check_sources()
            out = archive/'results'/name
            with (archive/'raw'/(name+'-analysis.log')).open('w') as stream:
                if mode == 'on':
                    call(['sh',str(archive/'replay-throughput.sh'),name],stream)
                else:
                    call(['python3',str(archive/'prepare-analysis-input.py'),
                          str(archive/'raw'/(name+'.log')),str(out)],stream)
                    with (out/'complete-chain-rejection.log').open('w') as rejection:
                        result = subprocess.run(['python3',str(analysis/'analyze_virq_task.py'),
                            str(out/'analysis-input.log'),'--output-dir',str(out/'forbidden-full-chain')],
                            cwd=repo,stdout=rejection,stderr=subprocess.STDOUT)
                    assert result.returncode != 0
                    assert 'disabled recorder cannot establish a complete runtime chain' in (out/'complete-chain-rejection.log').read_text()
                call(['python3',str(analysis/'analyze_virq_probe_cost.py'),str(out/'analysis-input.log'),
                      '--output-dir',str(out/'probe_cost')],stream)
            identity = json.loads((archive/'configs'/name/'provenance.json').read_text())
            assert identity['exit_code'] == 0
            assert all(identity[k] == plan[k] for k in ('source_sha256','host_source_sha256','cargo_lock_sha256'))
            result = json.loads((out/'probe_cost/summary.json').read_text())
            assert result['recording_mode'] == mode and result['task_rounds'] == 4096
            assert result['task_wait_mode'] == 'blocked' and result['periodic']['jobs'] == 32
            assert result['linux_fences']['mode'] == 'serial'
            assert all(p['samples'] == 32 for p in result['policies'].values())
            state['completed'].append(dict(block=block['block'],name=name,mode=mode))
            print(f'RECORDER_PAIR_RUN_OK name={name} tasks=64 complete_chain={int(mode == "on")}',flush=True)
            state['active_run'] = None
            save()
    state['terminal'] = state['success'] = True
    state['finished_unix'] = time.time()
    save()
    print('RECORDER_PAIRS_DONE blocks=4 runs=8 task_observations=512',flush=True)
except BaseException as error:
    state.update(terminal=True,success=False,error=repr(error),finished_unix=time.time())
    save()
    raise
