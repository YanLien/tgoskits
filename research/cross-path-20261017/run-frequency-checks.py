#!/usr/bin/env python3
"""Directed native, QEMU and default-off snapshots, with immutable run inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
analysis = repo/'virtualization/axvm/tests/analysis'
plan_path = archive/'configs/frequency-check-plan.json'
assert not plan_path.exists(), 'Inspect the recorded plan; never restart it'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
roots = ('components/axcpu', 'virtualization/axvm/tests', 'virtualization/axvm/src', 'drivers/ax-driver')
sources = {str(p.relative_to(repo)): digest(p) for tree in roots for p in (repo/tree).rglob('*')
           if p.is_file() and p.suffix in ('.rs', '.py', '.c', '.h', '.toml', '.txt', '.dts', '.overlay') and '__pycache__' not in p.parts}
for path in ('virtualization/axvm/Cargo.toml', 'Cargo.lock'):
    sources[path] = digest(repo/path)
runs = [dict(name='frequency-qemu-on-32', runtime='qemu', scenario='linux_cpu', pressure='off', frequency='enabled'),
        dict(name='frequency-board-memory-sgi-32', runtime='board', scenario='linux_memory', pressure='sgi', frequency='enabled'),
        dict(name='frequency-qemu-off-32', runtime='qemu', scenario='linux_cpu', pressure='off', frequency='disabled')]
controls = {str(p.relative_to(repo)): digest(p) for p in (
    Path(__file__), archive/'run-frequency-timechain.sh', archive/'capture-frequency-cpu.py',
    archive/'capture-thermal-driver.py', archive/'capture-periodic.py', archive/'replay-throughput.sh')}
plan = dict(runs=runs, source_sha256=sources, control_sha256=controls,
            scope='Directed quiescent frequency functionality; not randomized interference or probe-cost inference', M1=False, M2=False)
plan_path.write_text(json.dumps(plan, indent=2)+'\n')
state = dict(controller_pid=os.getpid(), started_unix=time.time(), terminal=False, success=False, completed=[], active_run=None)


def save():
    (archive/'results/frequency-check-status.json').write_text(json.dumps(state, indent=2)+'\n')


def check_sources():
    assert all(digest(repo/p) == h for p, h in sources.items()), 'source changed during frequency cohort'
    assert all(digest(repo/p) == h for p, h in controls.items()), 'control changed during frequency cohort'


save()
try:
    for run in runs:
        check_sources()
        name = run['name']
        state['active_run'] = name
        save()
        print('FREQUENCY_CHECK_BEGIN '+name, flush=True)
        result = subprocess.run(['sh', str(archive/'run-frequency-timechain.sh'), name, run['runtime'],
                                 run['scenario'], run['pressure'], run['frequency']], cwd=repo)
        check_sources()
        provenance = json.loads((archive/'configs'/name/'provenance.json').read_text())
        assert result.returncode == provenance['exit_code'] == 0
        with (archive/'raw'/(name+'-analysis.log')).open('w') as stream:
            subprocess.run(['sh', str(archive/'replay-throughput.sh'), name], cwd=repo, check=True, stdout=stream, stderr=subprocess.STDOUT)
            for kind in ('stages', 'thermal', 'frequency'):
                subprocess.run(['python3', str(analysis/('analyze_virq_'+kind+'.py')),
                                str(archive/'results'/name/'analysis-input.log'), '--output-dir',
                                str(archive/'results'/name/kind)], cwd=repo, check=True, stdout=stream, stderr=subprocess.STDOUT)
        summary = json.loads((archive/'results'/name/'frequency/summary.json').read_text())
        assert summary['task_observations'] == 64 and summary['window_frequency_hz'] is None
        assert summary['observations_available'] == (run['frequency'] == 'enabled')
        assert not summary['continuous_coverage'] and not summary['M1'] and not summary['M2']
        thermal = json.loads((archive/'results'/name/'thermal/summary.json').read_text())
        assert thermal['observations_available'] == (run['runtime'] == 'board' and run['frequency'] == 'enabled')
        state['completed'].append(dict(name=name, measurement_accepted=True))
        state['active_run'] = None
        save()
        print('FREQUENCY_CHECK_OK '+name, flush=True)
    state.update(terminal=True, success=True, finished_unix=time.time())
    save()
    print('FREQUENCY_CHECKS_DONE accepted_boots=3 task_observations=192 snapshots=32', flush=True)
except BaseException as error:
    state.update(terminal=True, success=False, error=repr(error), finished_unix=time.time())
    save()
    raise
