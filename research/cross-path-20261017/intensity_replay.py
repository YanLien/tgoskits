#!/usr/bin/env python3
"""Cold replay of accepted intensity traces using their frozen archived sources.

--archive changes only the read-only evidence location, never the registered plan.
No build, hardware request, automatic retry, or existing-output overwrite is used.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import time


RELATIVE = Path('research/cross-path-20261017')
PLAN = 'configs/intensity-v3-plan.json'
STATUS = 'results/intensity-v3-status.json'
DECODER = 'analysis-input-provenance.json'
PLOT_PYTHON = '/tmp/crosspath-plot-env/bin/python3'
SEALS = {'SHA256SUMS': 'b1a201fac9200b0a2c7efc5475640ea27dde5512ddaf21d16a84381f225794d3',
         'SHA256SUMS.postseal-v1': 'be93e8b556e7685f751839d4cfba35e9e2e9862e3bf98a001378571ca95c2abf'}


def relative_path(value):
    path = Path(value)
    if (not isinstance(value, str) or not value or path.is_absolute()
            or '..' in path.parts or '.' in value.split('/') or str(path) != value
            or '.git' in path.parts):
        raise ValueError('invalid registered relative path: '+str(value))
    return path


def regular(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('ordinary file required: '+str(path))
    return path


def digest(path):
    with regular(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(regular(path).read_bytes())


def check_hash(path, expected):
    observed = digest(path)
    if observed != expected:
        raise ValueError('file identity changed: '+str(path))
    return observed


def derived_files(folder):
    found = {}
    for path in folder.rglob('*'):
        if path.is_symlink():
            raise ValueError('nonordinary analysis member: '+str(path))
        if path.is_file() and path.suffix in ('.json', '.csv'):
            found[str(path.relative_to(folder))] = digest(path)
    return found


def compare_run(original, restored, accepted, record):
    """Compare actual derived bytes; allow only the exactly relocated raw path."""
    name = str(relative_path(accepted['name']))
    if '/' in name or accepted.get('tasks') != 64 or record.get('tasks') != 64:
        raise ValueError('a complete accepted boot is required')
    old_raw, new_raw = (archive/'raw'/(name+'.log') for archive in (original, restored))
    check_hash(old_raw, accepted['raw_sha256'])
    check_hash(new_raw, accepted['raw_sha256'])
    old_dir, new_dir = (archive/'results'/name for archive in (original, restored))
    expected, actual = accepted['derived_sha256'], record['derived_sha256']
    for filename in expected:
        relative_path(filename)
    if (derived_files(old_dir) != expected or derived_files(new_dir) != actual
            or set(actual) != set(expected) or DECODER not in expected):
        raise ValueError('derived file identity or set differs: '+name)
    old, new = read(old_dir/DECODER), read(new_dir/DECODER)
    if 'raw_path' not in old or new.get('raw_path') != str(new_raw):
        raise ValueError('decoder raw path is not the copied raw file')
    relocated = dict(old, raw_path=str(new_raw))
    if new != relocated:
        raise ValueError('decoder provenance differs beyond its copied raw path')
    for filename, sha in expected.items():
        if filename != DECODER and actual[filename] != sha:
            raise ValueError('recomputed analysis differs: '+name+'/'+filename)
    wanted = copy.deepcopy(accepted)
    wanted['derived_sha256'][DECODER] = actual[DECODER]
    if wanted != record:
        raise ValueError('recomputed acceptance differs beyond decoder representation: '+name)
    return dict(name=name, tasks=record['tasks'], compared_derived_files=len(expected),
                decoder=dict(old_path=old['raw_path'], new_path=new['raw_path'],
                             old_sha256=expected[DECODER], new_sha256=actual[DECODER]))


def compare_summary_json(old, new, original, restored, comparisons):
    """Permit exactly the state, relocated decoder, and actual PDF SHA bindings."""
    normalized = copy.deepcopy(old)
    differences = []

    def bound(path, old_value, new_value):
        if old_value != digest(original/path) or new_value != digest(restored/path):
            raise ValueError('summary value is not bound to actual bytes: '+str(path))
        differences.append(dict(path=str(path), old_sha256=old_value, new_sha256=new_value))

    bound(Path(STATUS), old['status_sha256'], new['status_sha256'])
    normalized['status_sha256'] = new['status_sha256']
    before, after = old['accepted_runs'], new['accepted_runs']
    if len(before) != len(after) or len(before) != len(comparisons):
        raise ValueError('summary accepted membership changed')
    for index, (accepted, replayed, proof) in enumerate(zip(before, after, comparisons)):
        fresh = compare_run(original, restored, accepted, replayed)
        if fresh != proof:
            raise ValueError('decoder comparison evidence changed')
        normalized['accepted_runs'][index]['derived_sha256'][DECODER] = fresh['decoder']['new_sha256']
        differences.append(dict(path='accepted_runs/'+str(index)+'/derived_sha256/'+DECODER,
                                **fresh['decoder']))
    if set(old['figures']) != set(new['figures']):
        raise ValueError('summary figure set differs')
    for name, figure in old['figures'].items():
        relative = relative_path(name)
        if relative.suffix == '.pdf':
            bound(Path('results')/relative, figure['sha256'], new['figures'][name]['sha256'])
            normalized['figures'][name]['sha256'] = new['figures'][name]['sha256']
    if normalized != new:
        raise ValueError('summary differs beyond exact state, decoder and PDF bindings')
    return differences


def evidence_path(archive, value):
    path = archive/relative_path(value)
    if not path.resolve().is_relative_to(archive.resolve()):
        raise ValueError('evidence path escapes the read-only archive: '+value)
    return regular(path)


def copy_file(source, destination, expected=None):
    """Exclusive copy, permitting a collision only for identical registered bytes."""
    sha = digest(source)
    if expected is not None and sha != expected:
        raise ValueError('copy source changed: '+str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        check_hash(destination, sha)
        return
    with regular(source).open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    check_hash(destination, sha)


def copy_config_tree(source, destination):
    for path in sorted(source.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError('nonordinary captured config: '+str(path))
        if path.is_file():
            copy_file(path, destination/path.relative_to(source))


def exact_packages(expected, packages):
    """Check the complete ordinary member set before using the frozen restorer."""
    found = {}
    for package in packages:
        with tarfile.open(regular(package)) as stream:
            for member in stream:
                relative_path(member.name)
                if member.isdir():
                    continue
                if not member.isfile() or member.name in found:
                    raise ValueError('invalid or duplicate captured source: '+member.name)
                found[member.name] = hashlib.sha256(stream.extractfile(member).read()).hexdigest()
    if found != expected:
        raise ValueError('actual complete source corpus differs from registered members')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, regular(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def frozen_modules(archive, plan):
    """Import only checked archive orchestration; never current analysis sources."""
    sealed = seal_entries(archive)
    helper_path = evidence_path(archive, 'frozen_replay.py')
    check_hash(helper_path, sealed[str(RELATIVE/'frozen_replay.py')])
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(archive))
    # The factorial controller only accepts these two names; intensity uses its
    # pure analysis functions, so an inherited collection selector is irrelevant.
    os.environ['FACTORIAL_COHORT'] = 'factorial'
    names = ('factorial_statistics', 'factorial_runner', 'intensity_sensitivity')
    observed = {}
    for name in names:
        path = evidence_path(archive, name+'.py')
        check_hash(path, plan['control_sha256'][str(RELATIVE/(name+'.py'))])
        module = load_module(name, path)
        observed[name] = dict(path=str(Path(module.__file__).resolve()), sha256=digest(path))
    helper = load_module('_intensity_frozen_replay', helper_path)
    observed['frozen_replay'] = dict(path=str(helper_path), sha256=digest(helper_path))
    summary = load_module('_intensity_summary', archive/'summarize-intensity.py')
    observed['summarize-intensity'] = dict(path=str(archive/'summarize-intensity.py'), sha256=digest(archive/'summarize-intensity.py'))
    return sys.modules['intensity_sensitivity'], helper, summary, observed


def seal_entries(archive):
    entries = {}
    for filename, expected in SEALS.items():
        path = evidence_path(archive, filename)
        check_hash(path, expected)
        seen = set()
        for line in path.read_text().splitlines():
            sha, value = line.split('  ', 1)
            relative = relative_path(value)
            if not relative.is_relative_to(RELATIVE) or value in seen:
                raise ValueError('invalid or duplicate prior seal path')
            if value in entries and entries[value] != sha:
                raise ValueError('prior seals disagree about bytes')
            seen.add(value)
            entries[value] = sha
    return entries


def base_sources(archive, plan):
    manifest = read(evidence_path(archive, 'configs/reproduction-base-inputs/manifest.json'))
    if set(manifest['inputs']) != {'linux.kernel', 'base-initramfs.cpio.gz'}:
        raise ValueError('both sealed Linux base inputs are required')
    result = {}
    for filename, entry in manifest['inputs'].items():
        relative = str(relative_path(entry['original_path']))
        if plan['base_inputs'][entry['build_metadata_field']] != dict(path=relative, sha256=entry['sha256']):
            raise ValueError('sealed base manifest differs from registered input')
        source = evidence_path(archive, 'configs/reproduction-base-inputs/'+filename)
        if source.stat().st_size != entry['bytes']:
            raise ValueError('sealed Linux base input size changed')
        check_hash(source, entry['sha256'])
        result[relative] = (source, entry['sha256'])
    if set(plan['base_inputs']) != {v['build_metadata_field'] for v in manifest['inputs'].values()}:
        raise ValueError('unexpected registered base input')
    return result


def control_source(archive, value, bases):
    relative = relative_path(value)
    if value in bases:
        return bases[value][0]
    if not relative.is_relative_to(RELATIVE):
        raise ValueError('control is outside archive or sealed base inputs: '+value)
    return evidence_path(archive, str(relative.relative_to(RELATIVE)))


def summary_identity(archive, plan_sha, state, summary):
    """Bind every formal output to the actual successful accepted cohort."""
    result = archive/'results'
    report = read(result/'intensity-v3-summary.json')
    if (report['plan_sha256'] != plan_sha or report['status_sha256'] != digest(archive/STATUS)
            or report['accepted_runs'] != state['completed']
            or report['native_boots'] != 96 or report['task_observations'] != 6144
            or report['summary_script_sha256'] != digest(archive/'summarize-intensity.py')
            or report['acceptance_script_sha256'] != digest(archive/'intensity_sensitivity.py')):
        raise ValueError('formal summary is not bound to actual complete accepted inputs')
    if set(report['derived_tables_sha256']) != set(summary.TABLES):
        raise ValueError('formal table set differs')
    hashes = {}
    for name in (*summary.TABLES, 'intensity-v3-report.md', 'intensity-v3-summary.json'):
        path = evidence_path(archive, 'results/'+name)
        hashes[name] = digest(path)
        if name in summary.TABLES:
            check_hash(path, report['derived_tables_sha256'][name])
    expected_figures = {'figures/'+stem+'.'+extension for stem in summary.FIGURES for extension in ('png', 'pdf')}
    if set(report['figures']) != expected_figures:
        raise ValueError('formal figure set differs')
    for name, metadata in report['figures'].items():
        hashes[name] = check_hash(evidence_path(archive, 'results/'+name), metadata['sha256'])
        if (not metadata['source_tables_sha256'] or any(
                report['derived_tables_sha256'].get(table) != sha
                for table, sha in metadata['source_tables_sha256'].items())):
            raise ValueError('formal figure is not bound to actual CSVs')
    for paths in report['source_files_sha256'].values():
        for relative, sha in paths.items():
            check_hash(evidence_path(archive, relative), sha)
    # The Markdown is a deterministic view of this very report.
    if (result/'intensity-v3-report.md').read_text() != summary.render_report(report):
        raise ValueError('formal Markdown differs from its actual summary')
    return hashes


def preflight(archive, selected):
    """Only archive-side identity checks; no current target or source verification."""
    plan_path, status_path = evidence_path(archive, PLAN), evidence_path(archive, STATUS)
    plan_bytes, state_bytes = plan_path.read_bytes(), status_path.read_bytes()
    plan, state = json.loads(plan_bytes), json.loads(state_bytes)
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    if state.get('plan_sha256') != plan_sha or state.get('offline_reanalysis') or state.get('hardware_boots_started') == 0:
        raise ValueError('state must be the actual hardware cohort bound to the frozen plan')
    if len(plan['source_sha256']) != 696:
        raise ValueError('the registered 696-source corpus is required')
    for value in plan['source_sha256']:
        relative_path(value)
    entries = seal_entries(archive)
    # Verify the sealed manifest before interpreting its archive-to-target map.
    manifest_name = str(RELATIVE/'configs/reproduction-base-inputs/manifest.json')
    check_hash(evidence_path(archive, 'configs/reproduction-base-inputs/manifest.json'), plan['control_sha256'][manifest_name])
    bases = base_sources(archive, plan)
    for relative, sha in plan['control_sha256'].items():
        if relative in plan['source_sha256'] and sha != plan['source_sha256'][relative]:
            raise ValueError('control and source registration conflict')
        check_hash(control_source(archive, relative, bases), sha)
    intensity, helper, summary, modules = frozen_modules(archive, plan)
    registered = intensity.registered_runs(plan)
    accepted = {}
    for index, record in enumerate(state['completed']):
        if index >= len(registered) or record.get('name') in accepted:
            raise ValueError('accepted cohort is duplicated or exceeds registration')
        run = registered[index]
        if record.get('tasks') != 64 or any(record.get(k) != v for k, v in run.items()):
            raise ValueError('accepted membership, order or task count changed')
        accepted[record['name']] = record
    full = selected is None
    if full:
        intensity.validate_completed(plan, state, plan_sha)
        formal = summary_identity(archive, plan_sha, state, summary)
    else:
        formal = None
        if not selected or len(set(selected)) != len(selected) or any(name not in accepted for name in selected):
            raise ValueError('only unique actually accepted run names can be replayed')
    names = set(accepted) if full else set(selected)
    runs = [run for run in registered if run['name'] in names]
    for run in runs:
        name, record = run['name'], accepted[run['name']]
        check_hash(evidence_path(archive, 'raw/'+name+'.log'), record['raw_sha256'])
        for relative, sha in record['derived_sha256'].items():
            check_hash(evidence_path(archive, 'results/'+name+'/'+str(relative_path(relative))), sha)
        if derived_files(archive/'results'/name) != record['derived_sha256']:
            raise ValueError('accepted reference derived set changed')
        packages = helper.source_packages(archive/'configs'/name)
        exact_packages(plan['source_sha256'], packages)
        for relative, sha in record['reference_files_sha256'].items():
            check_hash(evidence_path(archive, relative), sha)
    if full:
        for relative, sha in entries.items():
            check_hash(evidence_path(archive, str(Path(relative).relative_to(RELATIVE))), sha)
    if plan_path.read_bytes() != plan_bytes:
        raise ValueError('registered plan changed during preflight')
    return dict(plan=plan, state=state, plan_bytes=plan_bytes, state_bytes=state_bytes,
                plan_sha=plan_sha, full=full, runs=runs, accepted=accepted, helper=helper,
                summary=summary, parent_modules=modules, bases=bases, seals=entries, formal=formal)


DRIVER = r'''from pathlib import Path
import hashlib
import json
import sys
archive = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(archive))
import factorial_runner as f
import intensity_sensitivity as intensity
options = json.loads((archive/'configs/intensity-replay-options.json').read_text())
plan = intensity.read_plan()
intensity.check_inputs(plan)
records = []
for run in options['runs']:
    accepted = f.analyze_run(run)
    fit = archive/'configs'/run['name']/'host-boot.fit'
    accepted.update(reference_files_sha256={relative: f.digest(archive/relative)
                    for relative in intensity.reference_paths(run)},
                    host_fit_sha256=f.digest(fit),
                    host_fit_content_sha256=f.normalized_fit_sha256(fit.read_bytes()))
    intensity.verify_run(plan, run, accepted)
    intensity.check_inputs(plan)
    records.append(accepted)
    (archive/'results/intensity-replay-analysis-records.json').write_text(json.dumps(records, indent=2)+'\n')
    print('INTENSITY_REPLAY_ANALYZED', run['name'], flush=True)
'''


AUDIT_HOOK = r'''"""Record actual analysis imports in every inherited Python process."""
import atexit
import hashlib
import json
import os
from pathlib import Path
import sys

def _audit():
    options_path = Path(os.environ['INTENSITY_REPLAY_AUDIT_OPTIONS'])
    options = json.loads(options_path.read_text())
    root = Path(options['root'])
    archive = root/options['relative']
    analysis = root/'virtualization/axvm/tests/analysis'
    modules, errors = {}, []
    for name, module in tuple(sys.modules.items()):
        value = getattr(module, '__file__', None)
        # CPython may remove __main__.__file__ before exit callbacks, while
        # its actual SourceFileLoader retains the executed script path.
        if name == '__main__' and not value:
            value = getattr(getattr(module, '__loader__', None), 'path', None)
        if not value:
            continue
        path = Path(value).resolve()
        watched = (name == '__main__' or name.startswith(('analyze_virq_', 'virq_', 'factorial_'))
                   or name in ('stage_baseline', 'intensity_sensitivity')
                   or path.is_relative_to(archive) or path.is_relative_to(analysis))
        if not watched:
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        modules[name] = dict(path=str(path), sha256=sha)
        relative = str(path.relative_to(root)) if path.is_relative_to(root) else None
        if relative is None or options['expected'].get(relative) != sha:
            errors.append('unregistered or external actual analysis module: '+name+' '+str(path))
    result = dict(pid=os.getpid(), argv=sys.argv, cwd=str(Path.cwd()),
                  executable=sys.executable, python=sys.version, modules=modules,
                  hook=dict(path=str(Path(__file__).resolve()),
                            sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), errors=errors)
    destination = Path(options['records'])/(str(os.getpid())+'.json')
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    if errors:
        os._exit(86)
def _audit_guard():
    try:
        _audit()
    except BaseException as error:
        print('INTENSITY_REPLAY_AUDIT_FAILED', repr(error), file=sys.stderr, flush=True)
        os._exit(87)
atexit.register(_audit_guard)
'''


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(value)


def write_json_new(path, value):
    write_new(path, json.dumps(value, indent=2, allow_nan=False)+'\n')


def verify_audits(target, root, runs, hook, driver, full=False):
    records = []
    main_entries = set()
    modules = set()
    for path in sorted((target/'results/intensity-replay-imports').glob('*.json')):
        record = read(path)
        if (record['errors'] or record['hook']['path'] != str(hook)
                or record['hook']['sha256'] != digest(hook)):
            raise ValueError('actual child import audit failed: '+str(path))
        for name, meta in record['modules'].items():
            source = Path(meta['path'])
            if not source.is_relative_to(root) or digest(source) != meta['sha256']:
                raise ValueError('actual analysis source changed after use')
            modules.add(source.name)
        entry = record['modules'].get('__main__')
        if entry:
            main_entries.add(Path(entry['path']).name)
        records.append(record)
    required = {'intensity-replay-driver.py', 'prepare-analysis-input.py'}
    required.update('analyze_virq_'+kind+'.py' for kind in
                    ('physical', 'runtime', 'ready', 'isr', 'load', 'task', 'irq_service',
                     'irq_pressure', 'periodic', 'linux_fence', 'stages', 'probe_cost',
                     'thermal', 'frequency', 'counter'))
    if full:
        required.add('summarize-intensity.py')
    if not required.issubset(main_entries) or not {'factorial_runner.py', 'intensity_sensitivity.py', 'stage_baseline.py'}.issubset(modules):
        raise ValueError('missing actual analysis entry or imported module evidence: '+str(required-main_entries))
    # Every selected trace must have its own actual analysis process evidence.
    for run in runs:
        seen = {Path(record['modules']['__main__']['path']).name for record in records
                if '__main__' in record['modules'] and any(run['name'] in value for value in record['argv'])}
        if not (required-{'intensity-replay-driver.py', 'summarize-intensity.py'}).issubset(seen):
            raise ValueError('missing per-trace actual child analysis evidence: '+run['name'])
    return dict(processes=len(records), actual_entry_points=sorted(main_entries),
                actual_module_files=sorted(modules), records=[str(p.relative_to(target)) for p in
                sorted((target/'results/intensity-replay-imports').glob('*.json'))])


def pdf_metadata(path):
    command = ['/usr/bin/pdfinfo', '-isodates', str(regular(path))]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    fields = {}
    for line in result.stdout.splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            fields[key.strip()] = value.strip()
    return fields


def compare_pdf(original, replayed, binding, audit):
    """Compare PDF CSV Subject, page geometry and 72 dpi rendered PNG bytes."""
    audit.mkdir(parents=True)
    metadata = [pdf_metadata(path) for path in (original, replayed)]
    if (any(json.loads(fields.get('Subject', 'null')) != binding for fields in metadata)
            or any(metadata[0].get(key) != metadata[1].get(key) for key in ('Pages', 'Page size'))
            or int(metadata[0].get('Pages', '0')) <= 0):
        raise ValueError('PDF source CSV binding or page geometry differs')
    for label, source in (('original', original), ('replayed', replayed)):
        folder = audit/label
        folder.mkdir()
        copy_file(source, folder/source.name)
        subprocess.run(['/usr/bin/pdftoppm', '-r', '72', '-png', str(source), str(folder/'page')],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    rasters = [{p.name: digest(p) for p in (audit/label).glob('page-*.png')}
               for label in ('original', 'replayed')]
    if (len(rasters[0]) != int(metadata[0]['Pages']) or rasters[0] != rasters[1]):
        raise ValueError('PDF rendered pixels differ at 72 dpi')
    differences = {key: dict(original=metadata[0].get(key), replayed=metadata[1].get(key))
                   for key in metadata[0].keys() | metadata[1].keys()
                   if metadata[0].get(key) != metadata[1].get(key)}
    result = dict(original_sha256=digest(original), replayed_sha256=digest(replayed),
                  content_equivalent=True, binary_identical=digest(original) == digest(replayed),
                  dpi=72, renderer='/usr/bin/pdftoppm',
                  renderer_version=subprocess.run(['/usr/bin/pdftoppm', '-v'], check=True,
                      text=True, capture_output=True).stderr.strip(),
                  metadata_original=metadata[0], metadata_replayed=metadata[1],
                  metadata_differences=differences, identical_raster_sha256=rasters[0])
    write_json_new(audit/'comparison.json', result)
    return result


def compare_full(archive, target, prepared, comparisons):
    formal, summary = prepared['formal'], prepared['summary']
    for name, sha in formal.items():
        check_hash(evidence_path(archive, 'results/'+name), sha)
    identical = [*summary.TABLES, 'intensity-v3-report.md']
    identical.extend('figures/'+stem+'.png' for stem in summary.FIGURES)
    for name in identical:
        check_hash(target/'results'/name, formal[name])
    original_report = read(archive/'results/intensity-v3-summary.json')
    new_report = read(target/'results/intensity-v3-summary.json')
    differences = compare_summary_json(original_report, new_report, archive, target, comparisons)
    pdfs = {}
    for stem in summary.FIGURES:
        name = 'figures/'+stem+'.pdf'
        pdfs[name] = compare_pdf(archive/'results'/name, target/'results'/name,
                                original_report['figures'][name]['source_tables_sha256'],
                                target/'results/intensity-replay-pdf-audit'/stem)
    return dict(identical_files=identical, json_binding_differences=differences, pdfs=pdfs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--runs', nargs='+', help='accepted names only; partial mode never summarizes')
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parent,
                        help='read-only evidence location; does not change the measurement plan')
    args = parser.parse_args()
    archive = args.archive.resolve()
    root = args.output_root.resolve()
    if root.exists() or root.is_relative_to(archive) or archive.is_relative_to(root):
        raise ValueError('output must be a nonexistent directory separate from the original archive')
    prepared = preflight(archive, args.runs)
    plan, original = prepared['plan'], prepared['state']
    # From here onward failures are retained in an explicitly offline status.
    root.mkdir(parents=True)
    target = root/RELATIVE
    (target/'results').mkdir(parents=True)
    progress_path = target/'results/intensity-replay-status.json'
    progress = dict(offline_reanalysis=True, hardware_boots_started=0,
                    mode='full' if prepared['full'] else 'partial',
                    controller_pid=os.getpid(), started_unix=time.time(), terminal=False,
                    success=False, completed=[], source_members=len(plan['source_sha256']),
                    original_archive=str(archive), restored_repository=str(root),
                    original_plan_sha256=prepared['plan_sha'],
                    original_status_sha256=hashlib.sha256(prepared['state_bytes']).hexdigest(),
                    wrapper_sha256=digest(Path(__file__).resolve()),
                    parent_python=sys.version, parent_modules=prepared['parent_modules'],
                    original_seal_sha256=SEALS)

    def save():
        progress_path.write_text(json.dumps(progress, indent=2, allow_nan=False)+'\n')

    save()
    try:
        first = prepared['runs'][0]['name']
        packages = prepared['helper'].source_packages(archive/'configs'/first)
        exact_packages(plan['source_sha256'], packages)
        prepared['helper'].restore_sources(plan['source_sha256'], packages, root)
        for relative, expected in plan['source_sha256'].items():
            check_hash(root/relative_path(relative), expected)
        for relative, expected in plan['control_sha256'].items():
            copy_file(control_source(archive, relative, prepared['bases']), root/relative_path(relative), expected)
        if prepared['full']:
            for relative, expected in prepared['seals'].items():
                copy_file(evidence_path(archive, str(Path(relative).relative_to(RELATIVE))),
                          root/relative_path(relative), expected)
        for relative, (source, expected) in prepared['bases'].items():
            copy_file(source, root/relative_path(relative), expected)
        copy_file(archive/PLAN, target/PLAN, prepared['plan_sha'])
        destination = target/'configs/intensity-replay-original-status.json'
        with destination.open('xb') as stream:
            stream.write(prepared['state_bytes'])
        for run in prepared['runs']:
            name, record = run['name'], prepared['accepted'][run['name']]
            copy_file(evidence_path(archive, 'raw/'+name+'.log'), target/'raw'/(name+'.log'), record['raw_sha256'])
            copy_config_tree(archive/'configs'/name, target/'configs'/name)
            for relative, expected in record['reference_files_sha256'].items():
                copy_file(evidence_path(archive, relative), target/relative_path(relative), expected)
        write_json_new(target/'configs/intensity-replay-options.json', dict(full=prepared['full'], runs=prepared['runs']))
        driver = target/'configs/intensity-replay-driver.py'
        write_new(driver, DRIVER)
        audit_folder = target/'configs/intensity-replay-audit'
        hook = audit_folder/'sitecustomize.py'
        write_new(hook, AUDIT_HOOK)
        records_path = target/'results/intensity-replay-imports'
        records_path.mkdir()
        expected = dict(plan['source_sha256'])
        expected.update(plan['control_sha256'])
        expected.update({str(path.relative_to(root)): digest(path) for path in (driver, hook)})
        audit_options = audit_folder/'options.json'
        write_json_new(audit_options, dict(root=str(root), relative=str(RELATIVE), expected=expected, records=str(records_path)))
        progress.update(driver_sha256=digest(driver), audit_hook_sha256=digest(hook),
                        audit_options_sha256=digest(audit_options), analysis_runs=[run['name'] for run in prepared['runs']])
        save()
        environment = {key: value for key, value in os.environ.items()
                       if key not in ('PYTHONPATH', 'PYTHONHOME', 'FACTORIAL_COHORT')}
        environment.update(PYTHONPATH=str(audit_folder), PYTHONDONTWRITEBYTECODE='1',
                           FACTORIAL_COHORT='factorial', INTENSITY_REPLAY_AUDIT_OPTIONS=str(audit_options),
                           MPLCONFIGDIR='/tmp/crosspath-matplotlib-cache')
        with (target/'raw/intensity-replay-driver.log').open('x') as stream:
            subprocess.run([sys.executable, str(driver)], cwd=root, env=environment,
                           check=True, stdout=stream, stderr=subprocess.STDOUT)
        replayed = read(target/'results/intensity-replay-analysis-records.json')
        if len(replayed) != len(prepared['runs']):
            raise ValueError('cold driver did not produce every selected run')
        for run, record in zip(prepared['runs'], replayed):
            progress['completed'].append(compare_run(archive, target, prepared['accepted'][run['name']], record))
            save()
        progress['import_audit'] = verify_audits(target, root, prepared['runs'], hook, driver)
        if prepared['full']:
            offline = copy.deepcopy(original)
            offline.update(offline_reanalysis=True, hardware_boots_started=0,
                           original_status_sha256=progress['original_status_sha256'])
            for accepted, comparison in zip(offline['completed'], progress['completed']):
                accepted['derived_sha256'][DECODER] = comparison['decoder']['new_sha256']
            write_json_new(target/STATUS, offline)
            with (target/'raw/intensity-replay-summary.log').open('x') as stream:
                subprocess.run([PLOT_PYTHON, str(target/'summarize-intensity.py')], cwd=root, env=environment,
                               check=True, stdout=stream, stderr=subprocess.STDOUT)
            progress['import_audit'] = verify_audits(target, root, prepared['runs'], hook, driver, full=True)
            progress['complete_summary_comparison'] = compare_full(archive, target, prepared, progress['completed'])
        progress.update(terminal=True, success=True, finished_unix=time.time())
        save()
        print('INTENSITY_REPLAY_OK runs='+str(len(replayed))+' mode='+progress['mode']+' hardware_boots_started=0', flush=True)
    except BaseException as error:
        progress.update(terminal=True, success=False, error=repr(error), finished_unix=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
