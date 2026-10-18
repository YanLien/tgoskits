#!/usr/bin/env python3
"""Preregister QEMU contracts and eight balanced pairs of independent board boots."""
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time
import tomllib

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
analysis = repo/'virtualization/axvm/tests/analysis'
plan_path = archive/'configs/recorder-ops-plan.json'
status_path = archive/'results/recorder-ops-status.json'
assert not plan_path.exists(), 'Inspect an existing plan; never restart it'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
seed = 20261021
orders = [['on', 'off'] for _ in range(4)]+[['off', 'on'] for _ in range(4)]
random.Random(seed).shuffle(orders)
pilots = [dict(name=f'recorder-ops-qemu-{mode}-32', runtime='qemu', mode=mode, block=None) for mode in ('on', 'off')]
blocks = [dict(block=i+1, order=order, runs=[dict(name=f'recorder-ops-board-b{i+1:02d}-{mode}-32', runtime='board', mode=mode, block=i+1)
                                           for mode in order]) for i, order in enumerate(orders)]
roots = ('components/axcpu', 'virtualization/axvm/tests', 'virtualization/axvm/src', 'drivers/ax-driver')
sources = {str(p.relative_to(repo)): digest(p) for tree in roots for p in (repo/tree).rglob('*')
           if p.is_file() and p.suffix in ('.rs', '.py', '.c', '.h', '.toml', '.txt', '.dts', '.overlay') and '__pycache__' not in p.parts}
for p in ('virtualization/axvm/Cargo.toml', 'Cargo.lock'):
    sources[p] = digest(repo/p)
controls = {str(p.relative_to(repo)): digest(p) for p in (
    Path(__file__), archive/'run-frequency-timechain.sh', archive/'capture-frequency-cpu.py',
    archive/'capture-thermal-driver.py', archive/'capture-periodic.py', archive/'replay-throughput.sh',
    archive/'replay-periodic.sh', archive/'prepare-analysis-input.py')}
plan = dict(seed=seed, pilots=pilots, blocks=blocks, source_sha256=sources, control_sha256=controls,
    fixed_scenario='linux_cpu', fixed_irq_pressure='off', recording_declaration_version=2,
    comparison_scope='recorder_operations', independent_pairs=8, native_boots=16,
    primary_metric='scheduled release to Guest task completion using retained offset bounds; not an observed T0 in off',
    statistics=dict(unit='complete independent boot pair', resamples=10000, bootstrap_seed=seed+1,
                    interval='2.5th percentile of lower endpoint means through 97.5th percentile of upper endpoint means',
                    tail='descriptive nearest-rank; no percentile nonadditivity coupling claim'),
    stopping_rule='Stop at any build/runtime/correctness/completeness/source failure; preserve failed run; never replace it silently',
    limitations=['Frequency and temperature are quiescent snapshots, not window-constant guarantees.',
                 'Board firmware identity is incomplete; no new U-Boot/BL31 identity claim.',
                 'Eight pairs provide an empirical bootstrap envelope, not established coverage or pure per-instruction costs.',
                 'Recorder operation increment does not isolate all retained instrumentation costs.'], M1=False, M2=False)
plan_path.write_text(json.dumps(plan, indent=2)+'\n')
state = dict(controller_pid=os.getpid(), started_unix=time.time(), terminal=False, success=False, completed=[], active_run=None)
references = {}


def save():
    status_path.write_text(json.dumps(state, indent=2)+'\n')


def check_sources():
    assert all(digest(repo/p) == h for p, h in sources.items()), 'live source changed during recorder pairs'
    assert all(digest(repo/p) == h for p, h in controls.items()), 'run control changed during recorder pairs'


def call(command, stream=None, env=None):
    subprocess.run(command, cwd=repo, check=True, env=env, stdout=stream, stderr=subprocess.STDOUT)


def check_identity(run):
    name, runtime, mode = run['name'], run['runtime'], run['mode']
    folder = archive/'configs'/name
    p = json.loads((folder/'provenance.json').read_text())
    assert p['exit_code'] == 0 and p['runtime'] == runtime
    fixture = tomllib.loads((folder/'measurement.toml').read_text())
    assert fixture.pop('recording') == mode
    environment = [s for s in (folder/'environment.txt').read_text().splitlines() if not s.startswith('VIRQ_RECORDING=')]
    artifacts = {f: digest(folder/f) for f in ('realtime.elf', 'realtime.bin', 'realtime-input.dtb', 'linux-input.dtb',
                  'zephyr.config', 'linux-build.json', 'realtime-vm.toml', 'linux-vm.toml')}
    if runtime == 'board':
        artifacts['host-input.dtb'] = digest(folder/'host-input.dtb')
    identity = dict(fixture=fixture, environment=environment, artifacts=artifacts,
                    tools=(folder/'tool-versions-before-build.txt').read_text().splitlines()[1:],
                    git_commit=p['git_commit'], tests=p['source_sha256'], host=p['host_source_sha256'],
                    cpu=json.loads((folder/'cpu-source-provenance.json').read_text())['source_sha256'],
                    driver=json.loads((folder/'driver-source-provenance.json').read_text())['source_sha256'])
    if runtime not in references:
        references[runtime] = identity
        (archive/'configs'/f'recorder-ops-{runtime}-fixed-inputs.json').write_text(json.dumps(identity, indent=2)+'\n')
    assert references[runtime] == identity, 'a supposedly fixed workload or build input changed'
    return p


def analyze_run(run):
    name, mode = run['name'], run['mode']
    out = archive/'results'/name
    with (archive/'raw'/(name+'-analysis.log')).open('w') as stream:
        if mode == 'on':
            call(['sh', str(archive/'replay-throughput.sh'), name], stream)
            call(['python3', str(analysis/'analyze_virq_stages.py'), str(out/'analysis-input.log'), '--output-dir', str(out/'stages')], stream)
        else:
            call(['python3', str(archive/'prepare-analysis-input.py'), str(archive/'raw'/(name+'.log')), str(out)], stream)
            for kind, expected in (('task', 'disabled recorder cannot establish a complete runtime chain'),
                                   ('stages', 'disabled recorder has no IRQ stage observations')):
                reject_path = out/f'complete-{kind}-rejection.log'
                with reject_path.open('w') as rejection:
                    result = subprocess.run(['python3', str(analysis/f'analyze_virq_{kind}.py'), str(out/'analysis-input.log'),
                                             '--output-dir', str(out/f'forbidden-{kind}')], cwd=repo, stdout=rejection, stderr=subprocess.STDOUT)
                assert result.returncode != 0 and expected in reject_path.read_text()
        for kind in ('probe_cost', 'thermal', 'frequency', 'counter'):
            call(['python3', str(analysis/f'analyze_virq_{kind}.py'), str(out/'analysis-input.log'), '--output-dir', str(out/kind)], stream)
    result = json.loads((out/'probe_cost/summary.json').read_text())
    assert result['recording_mode'] == mode and result['recording_declaration_version'] == 2 and result['comparison_scope'] == 'recorder_operations'
    assert result['complete_chain_accepted'] == (mode == 'on') and result['task_observations_valid']
    assert result['task_rounds'] == 4096 and result['task_wait_mode'] == 'blocked' and result['periodic']['jobs'] == 32
    assert result['task_deadline_origin'] == 'scheduled_release' and result['linux_fences']['mode'] == 'serial'
    assert all(p['samples'] == 32 for p in result['policies'].values())
    for kind in ('frequency', 'counter'):
        environmental = json.loads((out/kind/'summary.json').read_text())
        assert environmental['task_observations'] == 64 and environmental['observations_available']
        assert environmental['recording_mode'] == mode
    counter = json.loads((out/'counter/summary.json').read_text())
    assert counter['series'] == 48 and counter['raw_reads'] == 12288 and not counter['effective_resolution_verified']
    thermal = json.loads((out/'thermal/summary.json').read_text())
    assert thermal['observations_available'] == (run['runtime'] == 'board')


save()
try:
    for run in pilots+[r for b in blocks for r in b['runs']]:
        check_sources()
        state['active_run'] = run['name']
        save()
        print(f'RECORDER_OPS_BEGIN runtime={run["runtime"]} block={run["block"]} mode={run["mode"]} name={run["name"]}', flush=True)
        env = dict(os.environ, VIRQ_RECORDING=run['mode'])
        call(['sh', str(archive/'run-frequency-timechain.sh'), run['name'], run['runtime'], 'linux_cpu', 'off', 'enabled'], env=env)
        check_sources()
        check_identity(run)
        analyze_run(run)
        check_sources()
        state['completed'].append(dict(**run, tasks=64, complete_chain=run['mode']=='on'))
        state['active_run'] = None
        save()
        print(f'RECORDER_OPS_RUN_OK name={run["name"]} tasks=64 complete_chain={int(run["mode"]=="on")}', flush=True)
    state.update(terminal=True, success=True, finished_unix=time.time())
    save()
    print('RECORDER_OPS_DONE qemu_boots=2 native_pairs=8 native_boots=16 native_tasks=1024', flush=True)
except BaseException as error:
    state.update(terminal=True, success=False, error=repr(error), finished_unix=time.time())
    save()
    raise
