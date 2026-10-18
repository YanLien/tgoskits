#!/usr/bin/env python3
"""Preregister and accept repeated pressure-intensity blocks without changing probes."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import tarfile

import factorial_runner as prior
from factorial_statistics import balanced_blocks

ARCHIVE, REPO = prior.ARCHIVE, prior.REPO
PLAN_FILE = 'configs/intensity-v3-plan.json'
STATUS_FILE = 'results/intensity-v3-status.json'
PLOT_PYTHON = '/tmp/crosspath-plot-env/bin/python3'
STRATA = dict(reference=dict(irq_period_us=2000, memory_every=1),
              irq2x=dict(irq_period_us=1000, memory_every=1),
              memory_sparse=dict(irq_period_us=2000, memory_every=8))
SEEDS = dict(reference=20261025, irq2x=20261026, memory_sparse=20261027)
MEMBERS_AUDIT = 'results/complete-source-members-audit.json'
SEALS = {'SHA256SUMS': 'b1a201fac9200b0a2c7efc5475640ea27dde5512ddaf21d16a84381f225794d3',
         'SHA256SUMS.postseal-v1': 'be93e8b556e7685f751839d4cfba35e9e2e9862e3bf98a001378571ca95c2abf'}


def design_plan():
    orders = {name: balanced_blocks(seed) for name, seed in SEEDS.items()}
    rng, blocks = random.Random(20261028), []
    for block in range(1, 9):
        strata = list(STRATA)
        rng.shuffle(strata)
        runs = []
        for name in strata:
            for position, condition in enumerate(orders[name][block-1], 1):
                runs.append(dict(block=block, stratum=name, position=position,
                                 macro_position=len(runs)+1, condition=condition,
                                 name=f'intensity-v3-b{block:02d}-{name}-{condition.lower()}-32'))
        blocks.append(dict(block=block, stratum_order=strata, runs=runs))
    return dict(schema_version=1, cohort='intensity-v3', strata=copy.deepcopy(STRATA),
                seeds=copy.deepcopy(SEEDS), stratum_order_seed=20261028, bootstrap_seed=20261029,
                paired_bootstrap_seed=20261030, bootstrap_resamples=10000,
                independent_macroblocks=8, native_boots=96, tasks_per_policy_per_boot=32,
                blocks=blocks)


def registered_runs(plan):
    expected = design_plan()
    if any(plan.get(key) != value for key, value in expected.items()):
        raise ValueError('registered intensity design, seeds or membership changed')
    return [run for block in plan['blocks'] for run in block['runs']]


def validate_completed(plan, state, plan_sha256):
    runs = registered_runs(plan)
    if (not state.get('terminal') or not state.get('success')
            or state.get('plan_sha256') != plan_sha256 or len(state['completed']) != len(runs)):
        raise ValueError('the complete successful registered intensity cohort is required')
    for run, accepted in zip(runs, state['completed']):
        if accepted.get('tasks') != 64 or any(accepted.get(k) != v for k, v in run.items()):
            raise ValueError('accepted intensity boot is incomplete, reordered or misassigned')
    return runs


def normalize_identity(fixed, linux, stratum, condition):
    """Remove only assigned intensity fields, after checking both declarations."""
    settings = STRATA[stratum]
    memory = condition in ('B', 'AB')
    every = settings['memory_every'] if memory else 1
    fixture = fixed['fixture']
    if ((fixture['irq_pressure_period_us'], fixture['irq_pressure_burst'],
         fixture['linux_memory_every'], fixture['linux_host_cpu'], fixture['explicit_dtb_enabled'])
            != (settings['irq_period_us'], 2, every, 3, True)
            or (linux['host_cpu'], linux['working_set_bytes'], linux['memory_every_batches'], linux['fences_enabled'])
            != (3, 16777216 if memory else 0, every, True)):
        raise ValueError('generated pressure or Linux input differs from assigned intensity')
    expected = {'VIRQ_IRQ_PRESSURE_PERIOD_US': str(settings['irq_period_us']),
                'VIRQ_LINUX_MEMORY_EVERY': str(settings['memory_every'])}
    for key, value in expected.items():
        declared = [line for line in fixed['environment'] if line.startswith(key+'=')]
        if declared != [key+'='+value]:
            raise ValueError('missing, duplicate or incorrect external intensity declaration')
    result = copy.deepcopy(fixed)
    for key in ('irq_pressure_period_us', 'linux_memory_every'):
        del result['fixture'][key]
    result['environment'] = [line for line in result['environment']
                             if line.split('=', 1)[0] not in expected]
    result['common_linux_build'] = {key: linux[key] for key in
        ('compiler_version', 'base_profile', 'kernel_sha256', 'base_initramfs_sha256',
         'workload_source_sha256')}
    return result


def validate_exposure(stratum, condition, load, pressure):
    scenario, mode = prior.SETTINGS[condition]
    settings = STRATA[stratum]
    if (load['scenario'] != scenario or set(load['loads']) != {'fair', 'fifo80'}
            or (pressure['mode'], pressure['period_us'], pressure['burst'])
            != (mode, settings['irq_period_us'], 2)):
        raise ValueError('observed pressure configuration differs from assignment')
    for peer in load['loads'].values():
        if (peer['host_cpu'] != 3 or not peer['stopped']
                or not peer['runtime_observation']['time_window_verified']):
            raise ValueError('Linux pressure residency or retirement is unverified')
        if scenario == 'linux_memory' and (peer['working_set_bytes'], peer['every_batches']) != (16777216, settings['memory_every']):
            raise ValueError('observed Linux memory divisor differs from assignment')
    if mode == 'off':
        if pressure['policies']:
            raise ValueError('disabled pressure has active observations')
    else:
        if set(pressure['policies']) != {'fair', 'fifo80'}:
            raise ValueError('missing pressure policy')
        for policy in pressure['policies'].values():
            if (not 0 < policy['sent'] == policy['handled'] <= 4096
                    or policy['skipped_periods'] != 0 or not policy['joined'] or not policy['retired']):
                raise ValueError('pressure skipped its grid or failed completion/retirement')


def paired_difference(reference, changed, *, seed, resamples=10000):
    if (len(reference) < 2 or len(reference) != len(changed)
            or len({r['block'] for r in reference}) != len(reference)
            or [r['block'] for r in reference] != [r['block'] for r in changed]
            or isinstance(seed, bool) or not isinstance(seed, int)
            or isinstance(resamples, bool) or not isinstance(resamples, int)
            or not 200 <= resamples <= 100000):
        raise ValueError('paired independent macroblocks and integer resampling settings required')
    for row in reference+changed:
        endpoints = row['bounds_ns']
        if (len(endpoints) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) for v in endpoints) or endpoints[0] > endpoints[1]):
            raise ValueError('finite ordered interaction bounds required')
    deltas = [[b['bounds_ns'][0]-a['bounds_ns'][1], b['bounds_ns'][1]-a['bounds_ns'][0]]
              for a, b in zip(reference, changed)]
    average = lambda rows: [statistics.mean(r[i] for r in rows) for i in (0, 1)]
    rng = random.Random(seed)
    draws = [average(rng.choices(deltas, k=len(deltas))) for _ in range(resamples)]
    lows, highs = (sorted(r[i] for r in draws) for i in (0, 1))
    return dict(independent_paired_macroblocks=len(deltas), mean_bounds_ns=average(deltas),
                bootstrap_95_bounds_ns=[lows[math.ceil(.025*resamples)-1], highs[math.ceil(.975*resamples)-1]],
                block_differences=[dict(block=r['block'], bounds_ns=d) for r, d in zip(reference, deltas)],
                sampling_unit='paired_macroblock_of_three_complete_four_boot_subblocks',
                seed=seed, resamples=resamples)


def read_plan():
    plan = prior.read(PLAN_FILE)
    registered_runs(plan)
    return plan


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def plot_environment():
    command = ['import json,sys,matplotlib',
               'print(json.dumps(dict(executable=sys.executable,python=sys.version,matplotlib=matplotlib.__version__)))']
    result = subprocess.run([PLOT_PYTHON, '-c', ';'.join(command)], check=True, capture_output=True,
                            text=True, env=dict(os.environ, MPLCONFIGDIR='/tmp/crosspath-matplotlib-cache'))
    observed = json.loads(result.stdout)
    if observed['matplotlib'] != '3.11.2':
        raise ValueError('the pinned plotting environment is unavailable')
    return observed


def check_base_inputs(plan, linux=None):
    """Check shared binary bytes before requests and their actual build identity."""
    if set(plan['base_inputs']) != {'kernel_sha256', 'base_initramfs_sha256'}:
        raise ValueError('both registered Linux base inputs are required')
    for field, entry in plan['base_inputs'].items():
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or file_digest(REPO/relative) != entry['sha256']:
            raise ValueError('registered Linux base bytes changed')
        if linux is not None and linux[field] != entry['sha256']:
            raise ValueError('actual Linux build differs from shared base input')


def check_inputs(plan, *, full_seals=False):
    registered_runs(plan)
    prior.verify_frozen(plan)
    native_members = prior.read(MEMBERS_AUDIT)['cohorts'][1]['all_members_sha256']
    if plan['source_sha256'] != native_members:
        raise ValueError('intensity source corpus differs from verified v3 members')
    check_base_inputs(plan)
    for name, expected in SEALS.items():
        path = ARCHIVE/name
        if file_digest(path) != expected:
            raise ValueError('prior evidence seal identity changed')
        if full_seals:
            seen = set()
            for line in path.read_text().splitlines():
                sha, relative = line.split('  ', 1)
                source = (REPO/relative).resolve()
                if not source.is_relative_to(ARCHIVE) or relative in seen or file_digest(source) != sha:
                    raise ValueError('prior sealed evidence changed: '+relative)
                seen.add(relative)
    prior.validate_runtime_sidecars(ARCHIVE/'configs/intensity-v3/board.toml',
                                   REPO/'virtualization/axvm/tests/vcpu-runtime/frequency')
    if full_seals and plan['plot_environment'] != plot_environment():
        raise ValueError('registered plotting environment changed')


def verify_source_packages(plan, name):
    folder = ARCHIVE/'configs'/name
    metadata = prior.read(f'configs/{name}/provenance.json')
    found = {}
    for filename, info, key in (
            ('sources.tar.gz', metadata, 'source_archive_sha256'),
            ('host-sources.tar.gz', metadata, 'host_source_archive_sha256'),
            ('cpu-sources.tar.gz', prior.read(f'configs/{name}/cpu-source-provenance.json'), 'archive_sha256'),
            ('driver-sources.tar.gz', prior.read(f'configs/{name}/driver-source-provenance.json'), 'archive_sha256')):
        path = folder/filename
        if file_digest(path) != info[key]:
            raise ValueError('captured source package changed')
        with tarfile.open(path) as stream:
            seen = set()
            for member in stream:
                if member.isdir():
                    continue
                if not member.isfile() or member.name in seen or member.name in found:
                    raise ValueError('invalid or duplicate ordinary source member')
                seen.add(member.name)
                found[member.name] = hashlib.sha256(stream.extractfile(member).read()).hexdigest()
    if found != plan['source_sha256']:
        raise ValueError('actual archived source members differ from registration')


def reference_paths(run):
    if run['condition'] in ('B', 'AB'):
        workload = 'memory-every'+str(STRATA[run['stratum']]['memory_every'])
    else:
        workload = 'cpu'
    return ('configs/intensity-v3-fixed-inputs.json', f'configs/intensity-v3-linux-{workload}-inputs.json')


def verify_run(plan, run, accepted):
    """Validate actual data and immutable input references before statistical use."""
    name, output = run['name'], ARCHIVE/'results'/run['name']
    fixed, linux = prior.identity_for(run)
    fixed = normalize_identity(fixed, linux, run['stratum'], run['condition'])
    check_base_inputs(plan, linux)
    verify_source_packages(plan, name)
    prior.verify_derived(output, accepted)
    if (accepted.get('tasks') != 64 or any(accepted.get(k) != v for k, v in run.items())
            or accepted['raw_sha256'] != file_digest(ARCHIVE/'raw'/(name+'.log'))
            or accepted['analysis_input_sha256'] != file_digest(output/'analysis-input.log')):
        raise ValueError('accepted measurement identity or task count changed')
    runtime = prior.read(f'results/{name}/runtime/summary.json')
    probe = prior.read(f'results/{name}/probe_cost/summary.json')
    if (runtime['dropped'] or runtime['incomplete'] or not probe['task_observations_valid']
            or not probe['complete_chain_accepted'] or probe['recording_mode'] != 'on'):
        raise ValueError('lossy or invalid measurement cannot enter intensity statistics')
    validate_exposure(run['stratum'], run['condition'], prior.read(f'results/{name}/load/summary.json'),
                      prior.read(f'results/{name}/irq_pressure/summary.json'))
    refs = accepted['reference_files_sha256']
    paths = reference_paths(run)
    if set(refs) != set(paths):
        raise ValueError('accepted input references differ from assigned workload')
    for path, actual in zip(paths, (fixed, linux)):
        if file_digest(ARCHIVE/path) != refs[path] or prior.read(path) != actual:
            raise ValueError('fixed or workload input reference changed')
    fit = ARCHIVE/'configs'/name/'host-boot.fit'
    if (accepted['host_fit_sha256'] != file_digest(fit)
            or accepted['host_fit_content_sha256'] != prior.normalized_fit_sha256(fit.read_bytes())
            or accepted['firmware'] != prior.firmware_for(name)):
        raise ValueError('actual boot FIT or observed firmware changed')
    return fixed, linux


def prepare_plan():
    for path in (PLAN_FILE, STATUS_FILE):
        if (ARCHIVE/path).exists():
            raise FileExistsError('preserve the existing intensity plan or state')
    for name in ('factorial-recovery-status.json', 'topology-native-v3-status.json'):
        state = prior.read('results/'+name)
        if not state['terminal'] or not state['success']:
            raise ValueError('previous native collection has not completed')
    if not prior.read('results/phase01-final-acceptance.json')['M1']:
        raise ValueError('the evidence-based M1 acceptance is required')
    plan = design_plan()
    plan['source_sha256'] = prior.read(MEMBERS_AUDIT)['cohorts'][1]['all_members_sha256']
    native = prior.read('configs/topology-native-v3-plan.json')
    controls = dict(native['control_sha256'])
    controls.update(prior.read('configs/factorial-recovery-plan.json')['control_sha256'])
    names = ['intensity_sensitivity.py', 'run-intensity-timechain.sh', 'summarize-intensity.py',
             'test_intensity_sensitivity.py', 'test_intensity_report.py',
             'design/phase2-intensity-sensitivity-plan.md', MEMBERS_AUDIT,
             'results/phase01-final-acceptance.json', 'results/topology-native-v3-status.json',
             'results/frozen-replay-complete-v1-audit.json',
             'configs/reproduction-base-inputs/manifest.json',
             'configs/intensity-v3/board.toml', 'configs/intensity-v3/guest-builds.toml',
             'configs/intensity-v3/host-initramfs.toml', *SEALS]
    controls.update({str((ARCHIVE/name).relative_to(REPO)): file_digest(ARCHIVE/name) for name in names})
    plan['control_sha256'] = controls
    plan['M1_evidence_sha256'] = file_digest(ARCHIVE/'results/phase01-final-acceptance.json')
    plan['base_inputs'] = {entry['build_metadata_field']: dict(path=entry['original_path'], sha256=entry['sha256'])
                          for entry in prior.read('configs/reproduction-base-inputs/manifest.json')['inputs'].values()}
    plan['plot_environment'] = plot_environment()
    plan['scope'] = 'CPU3 dual-VM intensity sensitivity; new v3 reference and two assigned pressure changes'
    plan['stopping_rule'] = '96 accepted boots or first build, identity, exposure, correctness, loss or analysis failure; never replace failed boots'
    plan['limitations'] = ['Continuous B has no independently controlled peak phase.',
                          'Recorder and residual protocols are identical here; old-version on/off is not a new-version correction.',
                          'Eight macroblocks do not establish interval coverage, power or causal propagation.']
    check_inputs(plan, full_seals=True)
    with (ARCHIVE/PLAN_FILE).open('x') as stream:
        stream.write(json.dumps(plan, indent=2)+'\n')
    print('INTENSITY_PLAN_CREATED boots=96 tasks=6144 sha256='+file_digest(ARCHIVE/PLAN_FILE))


def collect(plan):
    check_inputs(plan, full_seals=True)
    runs = registered_runs(plan)
    if (ARCHIVE/STATUS_FILE).exists():
        raise FileExistsError('inspect the existing controller; never restart automatically')
    for run in runs:
        if any(path.exists() for path in (ARCHIVE/'raw'/(run['name']+'.log'),
                                         ARCHIVE/'configs'/run['name'], ARCHIVE/'results'/run['name'])):
            raise FileExistsError('preserve an existing intensity run')
    for path in ('results/factorial-recovery-status.json', 'results/topology-native-v3-status.json'):
        state = prior.read(path)
        try:
            os.kill(state['controller_pid'], 0)
        except ProcessLookupError:
            continue
        raise ValueError('previous native controller still exists')
    plan_sha = file_digest(ARCHIVE/PLAN_FILE)
    input_references, fit_references = {}, {}
    firmware_reference = None

    def run_one(run):
        nonlocal firmware_reference
        if file_digest(ARCHIVE/PLAN_FILE) != plan_sha:
            raise ValueError('intensity plan changed during execution')
        check_inputs(plan)
        settings = STRATA[run['stratum']]
        scenario, pressure = prior.SETTINGS[run['condition']]
        subprocess.run(['sh', str(ARCHIVE/'run-intensity-timechain.sh'), run['name'], scenario, pressure,
                        str(settings['irq_period_us']), str(settings['memory_every'])], cwd=REPO, check=True)
        check_inputs(plan)
        fixed, linux = prior.identity_for(run)
        fixed = normalize_identity(fixed, linux, run['stratum'], run['condition'])
        refs = {}
        for relative, actual in zip(reference_paths(run), (fixed, linux)):
            if relative not in input_references:
                with (ARCHIVE/relative).open('x') as stream:
                    stream.write(json.dumps(actual, indent=2)+'\n')
                input_references[relative] = actual
            if actual != input_references[relative]:
                raise ValueError('nonassigned source, tool, workload or platform identity changed')
            refs[relative] = file_digest(ARCHIVE/relative)
        accepted = prior.analyze_run(run)
        fit = ARCHIVE/'configs'/run['name']/'host-boot.fit'
        content = prior.normalized_fit_sha256(fit.read_bytes())
        key = (run['stratum'], run['condition'])
        if fit_references.setdefault(key, content) != content:
            raise ValueError('Host FIT content changed within an assigned condition')
        observed = accepted['firmware']
        if not observed['uboot_build_banners'] or not observed['bl31_build_banners']:
            raise ValueError('actual firmware version text is missing')
        if firmware_reference is None:
            firmware_reference = observed
        if observed != firmware_reference:
            raise ValueError('actual firmware version text changed')
        accepted.update(reference_files_sha256=refs, host_fit_sha256=file_digest(fit),
                        host_fit_content_sha256=content)
        verify_run(plan, run, accepted)
        check_inputs(plan)
        return accepted

    prior.execute_runs(runs, ARCHIVE/STATUS_FILE, run_one, plan_sha256=plan_sha)
    print('INTENSITY_COLLECTION_DONE boots=96 tasks=6144', flush=True)
    subprocess.run([PLOT_PYTHON, str(ARCHIVE/'summarize-intensity.py')], cwd=REPO, check=True,
                   env=dict(os.environ, MPLCONFIGDIR='/tmp/crosspath-matplotlib-cache'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--prepare', action='store_true')
    actions.add_argument('--check-ready', action='store_true')
    actions.add_argument('--check-run', nargs=5, metavar=('NAME', 'SCENARIO', 'PRESSURE', 'PERIOD', 'EVERY'))
    args = parser.parse_args()
    if args.prepare:
        prepare_plan()
        return
    plan = read_plan()
    if args.check_ready:
        check_inputs(plan, full_seals=True)
        print('INTENSITY_READY boots=96 source_members=696')
    elif args.check_run:
        name, scenario, pressure, period, every = args.check_run
        matches = [run for run in registered_runs(plan) if run['name'] == name]
        if len(matches) != 1:
            raise ValueError('unknown registered intensity run')
        settings = STRATA[matches[0]['stratum']]
        if (scenario, pressure) != prior.SETTINGS[matches[0]['condition']] or (period, every) != (str(settings['irq_period_us']), str(settings['memory_every'])):
            raise ValueError('wrapper arguments differ from registration')
        check_inputs(plan)
    else:
        collect(plan)


if __name__ == '__main__':
    main()
