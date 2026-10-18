#!/usr/bin/env python3
"""Replay hardware traces with their archived analysis sources in a new tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ARCHIVE = Path(__file__).resolve().parent
REPO = ARCHIVE.parent.parent
RELATIVE = ARCHIVE.relative_to(REPO)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def restore_sources(expected, archives, destination):
    """Restore only registered ordinary source files after verifying their bytes."""
    found = {}
    for path in archives:
        with tarfile.open(path) as stream:
            for member in stream:
                if member.name not in expected:
                    continue
                relative = Path(member.name)
                if (not member.isfile() or relative.is_absolute()
                        or '..' in relative.parts or member.name in found):
                    raise ValueError('invalid or duplicated registered source: '+member.name)
                data = stream.extractfile(member).read()
                if hashlib.sha256(data).hexdigest() != expected[member.name]:
                    raise ValueError('archived source bytes changed: '+member.name)
                found[member.name] = data
    if set(found) != set(expected):
        raise ValueError('archive does not contain the complete registered source corpus')
    for relative, data in found.items():
        path = destination/relative
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('source path escapes the new tree')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)


def source_packages(folder):
    provenance = read(folder/'provenance.json')
    packages = []
    for filename, meta, key in (
            ('sources.tar.gz', provenance, 'source_archive_sha256'),
            ('host-sources.tar.gz', provenance, 'host_source_archive_sha256'),
            ('cpu-sources.tar.gz', read(folder/'cpu-source-provenance.json'), 'archive_sha256'),
            ('driver-sources.tar.gz', read(folder/'driver-source-provenance.json'), 'archive_sha256')):
        path = folder/filename
        if digest(path) != meta[key]:
            raise ValueError('source package identity changed: '+str(path))
        packages.append(path)
    return packages


def verify_seal(plan, state):
    if (not state['terminal'] or not state['success'] or len(state['completed']) != 32
            or any(r['tasks'] != 64 for r in state['completed'])):
        raise ValueError('full replay requires the actual successful 32-boot primary cohort')
    audit = read(ARCHIVE/'results/phase12-checkpoint-audit.json')
    if audit['cohort'] != plan['cohort'] or not audit['source_and_analysis_identity_verified']:
        raise ValueError('primary checkpoint audit is not complete')
    manifest = ARCHIVE/'SHA256SUMS'
    original_manifest_sha = digest(manifest)
    paths = {}
    for line in manifest.read_text().splitlines():
        sha, relative = line.split('  ', 1)
        path = (REPO/relative).resolve()
        if not path.is_relative_to(ARCHIVE) or relative in paths:
            raise ValueError('invalid primary seal path')
        paths[relative] = sha
        if digest(path) != sha:
            raise ValueError('primary sealed bytes changed: '+relative)
    required = [f'configs/{plan["cohort"]}-plan.json', f'results/{plan["cohort"]}-status.json',
                'results/phase12-checkpoint-audit.json', 'results/factorial-summary.json',
                'results/factorial-report.md', 'results/factorial-run-means.csv',
                'results/factorial-task-endpoints.csv', 'results/factorial-environment.csv']
    for accepted in state['completed']:
        required.append('raw/'+accepted['name']+'.log')
        required.extend('results/'+accepted['name']+'/'+p for p in accepted['derived_sha256'])
    if (any(str(RELATIVE/p) not in paths for p in required)
            or digest(manifest) != original_manifest_sha):
        raise ValueError('primary manifest is incomplete or changed during verification')
    return original_manifest_sha


DRIVER = '''from pathlib import Path
import json
import sys
archive = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(archive))
import factorial_runner as f
options = json.loads((archive/'configs/replay-options.json').read_text())
plan = f.read(f.PLAN_FILE)
f.verify_frozen(plan)
if options['full']:
    f.validate_completed(plan, f.read('configs/replay-original-status.json'), f.digest(archive/f.PLAN_FILE))
records = []
for run in options['runs']:
    fixed, linux = f.identity_for(run)
    if (fixed != f.read('configs/'+plan['cohort']+'-fixed-inputs.json')
            or linux != f.read('configs/'+plan['cohort']+'-'+plan['conditions'][run['condition']]['scenario']+'-inputs.json')):
        raise ValueError('copied hardware inputs differ from original cohort')
    records.append(f.analyze_run(run))
    (archive/'results/replay-analysis-records.json').write_text(json.dumps(records, indent=2)+'\\n')
    print('FROZEN_REPLAY_ANALYZED', run['name'], flush=True)
modules = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
           if name in ('factorial_runner', 'factorial_statistics', 'stage_baseline') or name.startswith('analyze_virq_')}
if any(not Path(path).is_relative_to(f.REPO) for path in modules.values()):
    raise ValueError('an analysis module came from outside the restored tree')
(archive/'results/replay-imported-modules.json').write_text(json.dumps(modules, indent=2)+'\\n')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--runs', nargs='+', help='partial raw reanalysis only; no interaction summary')
    args = parser.parse_args()
    root = args.output_root.resolve()
    if root.exists() or root.is_relative_to(ARCHIVE):
        raise ValueError('output must be a new directory outside the original archive')
    plan_path, status_path = (ARCHIVE/p for p in ('configs/factorial-recovery-plan.json',
                                                 'results/factorial-recovery-status.json'))
    plan = read(plan_path)
    status_bytes = status_path.read_bytes()
    original = json.loads(status_bytes)
    if original['plan_sha256'] != digest(plan_path):
        raise ValueError('accepted state belongs to a different plan')
    full = args.runs is None
    seal = verify_seal(plan, original) if full else None
    registered = {run['name']: run for block in plan['blocks'] for run in block['runs']}
    accepted = {run['name']: run for run in original['completed']}
    names = list(registered) if full else args.runs
    if not names or len(set(names)) != len(names) or any(name not in accepted for name in names):
        raise ValueError('only unique actually accepted run names can be replayed')
    runs = [registered[name] for name in names]
    for run in runs:
        if (accepted[run['name']]['tasks'] != 64
                or any(accepted[run['name']][key] != value for key, value in run.items())):
            raise ValueError('accepted membership or task count differs from registration')
    root.mkdir(parents=True)
    target = root/RELATIVE
    for child in ('configs', 'raw', 'results'):
        (target/child).mkdir(parents=True)
    progress = dict(offline_reanalysis=True, hardware_boots_started=0, full=full,
                    controller_pid=os.getpid(), started_unix=time.time(), terminal=False,
                    success=False, completed=[], original_plan_sha256=digest(plan_path),
                    original_status_sha256=hashlib.sha256(status_bytes).hexdigest(),
                    original_seal_sha256=seal, script_sha256=digest(Path(__file__)))
    progress_path = target/'results/frozen-replay-status.json'

    def save():
        progress_path.write_text(json.dumps(progress, indent=2)+'\n')

    save()
    try:
        restore_sources(plan['source_sha256'], source_packages(ARCHIVE/'configs'/names[0]), root)
        for relative, expected in plan['control_sha256'].items():
            source = ARCHIVE/Path(relative).relative_to(RELATIVE)
            if digest(source) != expected:
                raise ValueError('archived control changed: '+relative)
            destination = root/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copy2(plan_path, target/'configs'/plan_path.name)
        (target/'configs/replay-original-status.json').write_bytes(status_bytes)
        for suffix in ('fixed', 'linux_cpu', 'linux_memory'):
            filename = plan['cohort']+'-'+suffix+'-inputs.json'
            shutil.copy2(ARCHIVE/'configs'/filename, target/'configs'/filename)
        for run in runs:
            name = run['name']
            reference = accepted[name]
            raw = ARCHIVE/'raw'/(name+'.log')
            if digest(raw) != reference['raw_sha256']:
                raise ValueError('accepted raw bytes changed: '+name)
            for relative, expected in reference['derived_sha256'].items():
                if digest(ARCHIVE/'results'/name/relative) != expected:
                    raise ValueError('accepted reference analysis changed: '+name+'/'+relative)
            source_packages(ARCHIVE/'configs'/name)
            shutil.copy2(raw, target/'raw'/raw.name)
            shutil.copytree(ARCHIVE/'configs'/name, target/'configs'/name)
        (target/'configs/replay-options.json').write_text(json.dumps(dict(full=full, runs=runs), indent=2)+'\n')
        driver = target/'configs/replay-driver.py'
        driver.write_text(DRIVER)
        environment = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH'}
        environment['FACTORIAL_COHORT'] = plan['cohort']
        with (target/'raw/frozen-replay.log').open('x') as stream:
            subprocess.run([sys.executable, str(driver)], cwd=root, env=environment,
                           check=True, stdout=stream, stderr=subprocess.STDOUT)
        replayed = read(target/'results/replay-analysis-records.json')
        for run, record in zip(runs, replayed):
            name = run['name']
            reference = accepted[name]
            if set(record['derived_sha256']) != set(reference['derived_sha256']):
                raise ValueError('replay derived file set differs: '+name)
            changed_path = False
            for relative, expected in reference['derived_sha256'].items():
                actual = target/'results'/name/relative
                if relative == 'analysis-input-provenance.json':
                    old, new = read(ARCHIVE/'results'/name/relative), read(actual)
                    old_path, new_path = old.pop('raw_path'), new.pop('raw_path')
                    if old != new or new_path != str(target/'raw'/(name+'.log')):
                        raise ValueError('decoder provenance differs beyond its copied raw path')
                    changed_path = old_path != new_path
                elif digest(actual) != expected:
                    raise ValueError('recomputed analysis differs: '+name+'/'+relative)
            progress['completed'].append(dict(name=name, tasks=record['tasks'],
                compared_derived_files=len(record['derived_sha256']), raw_path_changed=changed_path))
            save()
        if len(replayed) != len(runs):
            raise ValueError('the cold driver did not produce all selected runs')
        if full:
            offline = dict(original, offline_reanalysis=True, hardware_boots_started=0,
                           original_status_sha256=progress['original_status_sha256'], completed=[
                               dict(accepted[record['name']], derived_sha256=record['derived_sha256'])
                               for record in replayed])
            (target/'results'/status_path.name).write_text(json.dumps(offline, indent=2)+'\n')
            with (target/'raw/frozen-summary-replay.log').open('x') as stream:
                subprocess.run([sys.executable, str(target/'summarize-factorial.py')], cwd=root,
                               env=environment, check=True, stdout=stream, stderr=subprocess.STDOUT)
            summaries = ('factorial-summary.json', 'factorial-report.md', 'factorial-run-means.csv',
                         'factorial-task-endpoints.csv', 'factorial-environment.csv')
            for filename in summaries:
                if digest(target/'results'/filename) != digest(ARCHIVE/'results'/filename):
                    raise ValueError('complete summary differs: '+filename)
            progress['identical_complete_summary_files'] = list(summaries)
        progress.update(terminal=True, success=True, finished_unix=time.time())
        save()
        print('FROZEN_REPLAY_OK', 'runs='+str(len(runs)), 'full='+str(int(full)), flush=True)
    except BaseException as error:
        progress.update(terminal=True, success=False, error=repr(error), finished_unix=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
