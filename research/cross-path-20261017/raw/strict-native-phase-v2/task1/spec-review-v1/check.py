#!/usr/bin/env python3
"""Read-only identity/semantic review; never import or run candidate tools."""
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile

W = Path(__file__).resolve().parent.parent
R = W.parents[2]
REPO = R.parents[1]
A = W / 'frozen-tools'
E = A / 'evidence'
OLD = Path('/tmp/strict-native-phase-tools-kevemo32')
PARENT = Path('/tmp/crosspath-strict-native-src-ii_h4jde')
CHANGED = 'virtualization/axvm/src/diagnostics.rs'
checks = []
evidence = {}


def load(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def identity(path):
    path = Path(path)
    value = path.lstat()
    if stat.S_ISLNK(value.st_mode):
        return {'type': 'symlink', 'target': os.readlink(path)}
    assert stat.S_ISREG(value.st_mode), str(path)
    return {'bytes': value.st_size, 'mode': stat.S_IMODE(value.st_mode), 'sha256': digest(path)}


def require(name, condition, detail=None):
    row = {'name': name, 'passed': bool(condition)}
    if detail is not None:
        row['detail'] = detail
    checks.append(row)


def bind(path, sha):
    actual = identity(path)
    evidence[str(path)] = actual
    require('sha:' + str(path), actual.get('sha256') == sha)
    return actual


def verify_members(name, root, manifest):
    failures = []
    for rel, expected in manifest.items():
        p = PurePosixPath(rel)
        if p.is_absolute() or '..' in p.parts:
            failures.append({'path': rel, 'reason': 'unsafe member'})
            continue
        try:
            actual = identity(root / rel)
            if actual != expected:
                failures.append({'path': rel, 'expected': expected, 'actual': actual})
        except (OSError, AssertionError) as error:
            failures.append({'path': rel, 'error': str(error)})
    require(name, not failures, {'members': len(manifest), 'failures': failures})


def receipt(stem, wait, argv=None, env=None, cwd=None):
    row = load(W / (stem + '.receipt.json'))
    require(stem + ':actual-wait', row['actual_Popen_wait'] == wait)
    for channel in ('stdout', 'stderr'):
        require(stem + ':' + channel, identity(W / (stem + '.' + channel)) == row[channel])
    require(stem + ':time-order', row['start_unix_ns'] < row['end_unix_ns'])
    if argv is not None:
        require(stem + ':argv', row['argv'] == argv)
    if env is not None:
        require(stem + ':environment', row['environment'] == env)
    if cwd is not None:
        require(stem + ':cwd', row['cwd'] == str(cwd))
    return row


for rel, expected in {
    'design/phase2-native-trace-capacity-v2-design.md': '5dbf286e5275dde7f8553de3785835b246f8df6ef7ad2b2e010bbe9357bb3ccd',
    'design/phase2-native-trace-capacity-v2-plan-v2.md': '54a43488604d56ea9bf02b5cdf06d1ab9b6d8bceb4248f91504c00e491534e27',
    'results/strict-native-trace-capacity-v2-design-plan-review-v2.json': 'df19eac41e66bbb608ec7ee944bd55aac404ab6629de778ce997529848fae4fd',
    'results/strict-native-trace-capacity-v2-task1.json': '74eace0f3fd2a8611fcb49fe981a754bb722104dc89efd737acddf81a5087429',
    'results/strict-native-trace-capacity-v2-task1.md': '6629813889ce01c09c3aab7b5e1aa3461931d2efac8dfed16c795e95189595f3',
    'raw/strict-native-phase-v2/base-input-restoration-v1.json': 'a0d90cb91d8ad68a16af12b92598f7eadd758b1965811cc504f764ef1af1142f',
}.items():
    bind(R / rel, expected)
report = load(R / 'results/strict-native-trace-capacity-v2-task1.json')
paths = load(W / 'paths.json')
SOURCE, TOOLS, TARGET = (Path(paths[k]) for k in ('source', 'tools', 'target'))
require('new-isolated-paths', all(p.is_dir() and not p.is_symlink() and str(p).startswith(prefix)
    for p, prefix in ((SOURCE, '/tmp/crosspath-native-capacity-v2-src-'),
                      (TOOLS, '/tmp/crosspath-native-capacity-v2-tools-'),
                      (TARGET, '/tmp/crosspath-native-capacity-v2-target-'))))
require('new-paths-exact', paths == report['candidate']['paths'])
bind(W / 'archive-manifest.json', 'a96095c74d41355d2e4b79c4d4ee6118aabd6428be539f2475bd2f0abb6041d3')
archive = load(W / 'archive-manifest.json')
require('archive-index-count', len(archive) == 155)
verify_members('archive-index-all-members', W, archive)
archive_bytes = sum(v.get('bytes', 0) for v in archive.values()) + (W / 'archive-manifest.json').stat().st_size
require('archive-budget', archive_bytes == 104178056 and archive_bytes < 1024 ** 3,
        {'indexed_bytes_with_index': archive_bytes, 'budget_bytes': 1024 ** 3,
         'review_additions_are_outside_original_index': True})

freeze_sha = '6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9'
bind(A / 'freeze-manifest.json', freeze_sha)
bind(TOOLS / 'freeze-manifest.json', freeze_sha)
frozen = load(A / 'freeze-manifest.json')
require('freeze-count', len(frozen) == 69)
verify_members('freeze-archive-all-members', A, frozen)
verify_members('freeze-execution-all-members', TOOLS, frozen)
candidate = load(W / 'candidate-identities.json')
for key, rel in {'capture': 'capture_native.py', 'controller': 'native_once.py',
                 'inputs': 'inputs.json', 'freeze_manifest': 'freeze-manifest.json',
                 'normal702': 'evidence/sources-702.json', 'normal702_tar': 'evidence/sources-702.tar.gz',
                 'ordinary': 'evidence/ordinary-identities.json', 'control': 'evidence/control-identities.json',
                 'virq_cache': 'evidence/cache-identities.json', 'cargo_cache': 'evidence/cargo-cache-identities.json'}.items():
    require('candidate-binding:' + key, identity(TOOLS / rel) == candidate[key] == report['candidate'][key])

bind(E / 'sources-702.json', '0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb')
bind(E / 'capacity-v2-parent-sources-702.json', '9e2fe24f40d95cf54390ad476d89c8162e2bfba9e257966a4a2cb3b9c31b918f')
bind(E / 'sources-702.tar.gz', '072c67c53641c3428ddfaa031692a506443105b0a023376dff90e307e1f8f29d')
normal = load(E / 'sources-702.json')
parent_normal = load(E / 'capacity-v2-parent-sources-702.json')
ordinary = load(E / 'ordinary-identities.json')
parent_ordinary = load(E / 'capacity-v2-parent-ordinary-identities.json')
require('702-identical-member-set', len(normal) == len(parent_normal) == 702 and normal.keys() == parent_normal.keys())
require('702-sole-change', [k for k in normal if normal[k] != parent_normal[k]] == [CHANGED])
require('ordinary-identical-member-set', len(ordinary) == len(parent_ordinary) == 9642 and ordinary.keys() == parent_ordinary.keys())
require('ordinary-sole-change', [k for k in ordinary if ordinary[k] != parent_ordinary[k]] == [CHANGED])
require('ordinary-diagnostics-mode-unchanged', ordinary[CHANGED]['mode'] == parent_ordinary[CHANGED]['mode'])
verify_members('all-702-current-candidate-bytes-mode', SOURCE, {k: ordinary[k] for k in normal})
verify_members('all-702-current-parent-bytes-mode', PARENT, {k: parent_ordinary[k] for k in parent_normal})
require('702-shas-agree-with-ordinary', all(normal[k] == ordinary[k]['sha256'] and
    parent_normal[k] == parent_ordinary[k]['sha256'] for k in normal))
tar_members = {}
tar_unsafe_members = []
with tarfile.open(E / 'sources-702.tar.gz', 'r:gz') as stream:
    for member in stream.getmembers():
        safe = not PurePosixPath(member.name).is_absolute() and '..' not in PurePosixPath(member.name).parts
        if not (safe and member.isfile() and member.name not in tar_members):
            tar_unsafe_members.append(member.name)
        if safe and member.isfile():
            tar_members[member.name] = {'bytes': member.size, 'mode': member.mode,
                'sha256': hashlib.sha256(stream.extractfile(member).read()).hexdigest()}
require('tar-all-members-safe-unique-ordinary', not tar_unsafe_members, tar_unsafe_members)
require('tar-all-702-identities', tar_members == {k: ordinary[k] for k in normal})
before = (PARENT / CHANGED).read_text()
after = (SOURCE / CHANGED).read_text()
evidence[str(PARENT / CHANGED)] = identity(PARENT / CHANGED)
evidence[str(SOURCE / CHANGED)] = identity(SOURCE / CHANGED)
old_line = 'const CAPACITY: usize = 16_384;'
new_lines = ('// Measurement capacity uses 10 MiB of slots across four CPUs.\n'
             '// Its memory cost requires new matched recording-on/off measurements.\n'
             'const CAPACITY: usize = 65_536;')
require('rust-exact-permitted-replacement', before.count(old_line) == 1 and after == before.replace(old_line, new_lines))
require('slot-byte-estimate', 4 * 65536 * 5 * 8 == 10485760 and 4 * 16384 * 5 * 8 == 2621440)
controls = load(E / 'control-identities.json')
require('three-controls-and-lock-unchanged', len(controls) == 3 and ordinary['Cargo.lock'] == parent_ordinary['Cargo.lock'])
verify_members('current-three-controls', SOURCE, controls)
verify_members('parent-three-controls', PARENT, controls)
require('inherited-source-post-validation', load(W / 'source-post-validation.json')['all_other_ordinary_bytes_modes_equal'] is True
        and load(W / 'source-post-validation.json')['recording_algorithm_unchanged'] is True)

old_controller = (OLD / 'native_once.py').read_text()
new_controller = (TOOLS / 'native_once.py').read_text()
old_output = "ARCHIVE/'raw/strict-native-phase-v1'/args.run"
new_output = "ARCHIVE/'raw/strict-native-phase-v2'/args.run"
require('controller-exact-only-output-root-change', old_controller.count(old_output) == 1 and
        new_controller == old_controller.replace(old_output, new_output))
require('controller-ast-only-output-root-change', ast.dump(ast.parse(old_controller.replace(old_output, new_output))) == ast.dump(ast.parse(new_controller)))
approved_capture = R / 'raw/strict-native-followup-v1/fit-capture-repair-v1/repaired/capture_native.py'
capture_sha = 'e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2'
bind(approved_capture, capture_sha)
bind(TOOLS / 'capture_native.py', capture_sha)
authority = load(E / 'capacity-v2-authority-provenance.json')
for name, sha in authority['new_exact_references'].items():
    bind(name, sha)
require('capture-approval-references', all((E / 'authorities' / Path(name).name).exists()
    and digest(E / 'authorities' / Path(name).name) == sha for name, sha in authority['new_exact_references'].items()))

inputs = load(TOOLS / 'inputs.json')
parent_inputs = load(E / 'capacity-v2-parent-inputs.json')
allowed_top = {'environment', 'execution_tools_root', 'normal702_sha256', 'source', 'target'}
require('input-only-paths-and-new702', {k for k in inputs if inputs[k] != parent_inputs[k]} == allowed_top)
require('input-key-set', inputs.keys() == parent_inputs.keys())
expected_env = dict(parent_inputs['environment'])
expected_env.update(AXBUILD_TARGET_DIR=str(TARGET), CARGO_TARGET_DIR=str(TARGET), CARGO_HOME=str(TOOLS / 'cache/cargo'),
    CCACHE_DIR=str(TOOLS / 'cache/ccache'), VIRQ_CACHE_DIR=str(TOOLS / 'cache/vcpu-runtime-cache'))
require('environment-exact-path-only-replacements', inputs['environment'] == expected_env)
require('inputs-new-source-tools-target', inputs['source'] == str(SOURCE) and inputs['execution_tools_root'] == str(TOOLS)
        and inputs['target'] == str(TARGET) and inputs['normal702_sha256'] == digest(E / 'sources-702.json'))
require('limits-preserved', inputs['limits'] == parent_inputs['limits'] == {
    'board_seconds': 900, 'capture_seconds': 30, 'cleanup_seconds': 10, 'max_artifact_versions_per_path': 4,
    'max_capture_bytes': 536870912, 'outer_seconds': 920})
require('stress-inputs-preserved', all(inputs['environment'][k] == v for k, v in {
    'VIRQ_SAMPLES': '32', 'VIRQ_PERIOD_US': '20000', 'VIRQ_TASK_DEADLINE_US': '10000',
    'VIRQ_IRQ_PRESSURE_PERIOD_US': '2000', 'VIRQ_IRQ_PRESSURE_BURST': '2'}.items())
    and inputs['cases'] == parent_inputs['cases'])
for name, item in inputs['external_inputs'].items():
    # The inherited static contract follows system executable aliases with stat().
    # Source/cache members above retain their explicit no-symlink/link-target rules.
    require('current-fixed-external-input:' + name, identity(Path(name).resolve()) == item)
    if Path(name).is_symlink():
        evidence[name] = {'alias': identity(name), 'resolved_path': str(Path(name).resolve()),
                          'resolved_identity': identity(Path(name).resolve())}
restoration = load(R / 'raw/strict-native-phase-v2/base-input-restoration-v1.json')
require('restoration-same-fixed-inputs', restoration['candidate_freeze_sha256'] == freeze_sha and
    restoration['prior_original_AB1_capture_or_release_backfilled'] is False and restoration['hardware_started'] == 0)
for item in restoration['files']:
    require('restoration-source-and-destination:' + item['destination'], identity(item['source']) ==
        identity(item['destination']) == item['expected_and_observed'] == inputs['external_inputs'][item['destination']])

relocation = load(W / 'cache-relocation.json')
old_cache = OLD / 'cache/vcpu-runtime-cache'
new_cache = TOOLS / 'cache/vcpu-runtime-cache'
cache_manifest = load(E / 'cache-identities.json')
parent_cache_manifest = load(E / 'capacity-v2-parent-cache-identities.json')
changes = {item['path']: item for item in relocation['changes']}
require('cache-manifest-only-13-relocations', len(cache_manifest) == len(parent_cache_manifest) == 54019
    and cache_manifest.keys() == parent_cache_manifest.keys()
    and set(k for k in cache_manifest if cache_manifest[k] != parent_cache_manifest[k]) == set(changes)
    and len(changes) == 13)
for rel, item in changes.items():
    old_bytes = (old_cache / rel).read_bytes()
    new_bytes = (new_cache / rel).read_bytes()
    expected = old_bytes
    for old_prefix, new_prefix in relocation['prefix_replacements'].items():
        expected = expected.replace(old_prefix.encode(), new_prefix.encode())
    require('cache-exact-prefix-replacement:' + rel, new_bytes == expected and
        identity(old_cache / rel) == item['old'] == parent_cache_manifest[rel] and
        identity(new_cache / rel) == item['new'] == cache_manifest[rel] and item['old']['mode'] == item['new']['mode'])
for rel, expected in relocation['system_python_links'].items():
    require('preserved-python-link:' + rel, identity(old_cache / rel) == identity(new_cache / rel) == expected)
proof = load(W / 'cache-production-entry-link.json')
probe = load(W / 'cache-python-probe.stdout')
require('probe-equals-proof', proof['probe'] == probe)
require('new-venv-runtime-paths', probe['sys_prefix'] == str(new_cache / 'venv') and
    all(Path(probe[k]).is_relative_to(new_cache) for k in ('sys_executable', 'cmake_module', 'CMAKE_BIN_DIR', 'cmake_binary'))
    and probe['interpreter_realpath'] == str((new_cache / 'venv/bin/python3').resolve()) == '/usr/bin/python3.12')
selected_cache = ['venv/bin/ninja', str(Path(probe['cmake_module']).relative_to(new_cache)),
    str(Path(probe['cmake_binary']).relative_to(new_cache))]
for rel in selected_cache:
    require('cache-selected-unchanged-algorithm-or-ELF:' + rel,
        identity(old_cache / rel) == identity(new_cache / rel) == parent_cache_manifest[rel] == cache_manifest[rel])
require('cmake-sha-and-dispatch', digest(probe['cmake_binary']) == probe['cmake_binary_sha256'] and
    identity(proof['entry']) == proof['entry_identity'] and identity(proof['cmake_module']) == proof['module_identity']
    and Path(proof['entry']).read_text() == proof['entry_text'] and Path(proof['cmake_module']).read_text() == proof['module_text']
    and "os.execl(cmake_exe, cmake_exe, *args)" in proof['module_text'])
require('production-cmake-entry-unchanged', identity(SOURCE / proof['production_prepare']['path']) == proof['production_prepare']['identity'])
require('cargo-cache-manifest-exact-parent', digest(E / 'cargo-cache-identities.json') == digest(E / 'capacity-v2-parent-cargo-cache-identities.json')
    == '75ba73a00cbf7150fa1b0bb1319091e329c470316f9d1eeda63f84d5a18e0d9f')
cache_post = load(W / 'cache-post-validation.json')
require('saved-full-cache-checks', cache_post['cargo_immutable_equal'] is True and cache_post['virq_immutable_equal'] is True
    and cache_post['cargo_immutable_files'] == 108002 and cache_post['virq_members'] == 54019)
require('saved-old-cache-initial-check', load(W / 'old-cache-verification.before.json')['all_immutable_match'] is True)

receipt('cargo-fmt', 0, ['cargo', 'fmt', '-p', 'axvm'], expected_env, SOURCE)
receipt('cargo-xtask-clippy', 0, ['cargo', 'xtask', 'clippy', '--package', 'axvm'], expected_env, SOURCE)
clippy_stdout = (W / 'cargo-xtask-clippy.stdout').read_text()
require('xtask-29-of-29', '[29/29] axvm (feature: host-test)' in clippy_stdout and
    'clippy summary: 1 package(s), 29 check(s), 1 package(s) passed, 0 package(s) failed, 0 package(s) skipped' in clippy_stdout)
python_receipt = receipt('cache-python-probe', 0)
cmake_receipt = receipt('cache-cmake-direct', 0, [str(new_cache / 'venv/bin/cmake'), '--version'])
require('local-probe-environment-no-legacy-injection', '-B' in python_receipt['argv'] and all(
    k not in python_receipt['environment'] and k not in cmake_receipt['environment'] for k in ('PYTHONHOME', 'PYTHONPATH')))
ready = load(W / 'readiness-after-assets-v1/readiness.json')
audit = (W / 'readiness-after-assets-v1/AUDITED_ENTRY.py.txt').read_text()
for stem, wait in (('ready', 0), ('reject-source', 2), ('reject-approval', 2)):
    row = receipt('readiness-after-assets-v1/' + stem, wait)
    require('audited-formal-entry:' + stem, row['argv'][3] == audit and row['argv'][4] == str(TOOLS / 'native_once.py'))
    if stem == 'reject-approval':
        require('negative-approval-passes-exact-freeze', freeze_sha in row['argv'] and inputs['normal702_sha256'] in row['argv'])
require('audit-boundary-preserved', "('socket.','subprocess.')" in audit and "'os.kill','os.killpg'" in audit
    and "OFFLINE_WRITE_FORBIDDEN" in audit and ready['audit_hook']['old_incomplete-primary_assumption_not_reused'] is True)
state_before = load(W / 'readiness-after-assets-v1/readiness-state.before.json')
state_after = load(W / 'readiness-after-assets-v1/readiness-state.after.json')
require('ready-before-after-target-no-case-no-marker', state_before == state_after and not state_after['once'] and
    not any(state_after['case_outputs'].values()) and len(state_after['target_files']) == 21797)
ready_output = (W / 'readiness-after-assets-v1/ready.stdout').read_text()
require('ready-output-exact-saved-result', ready_output.startswith('STRICT_NATIVE_READY ') and
        json.loads(ready_output.split(' ', 1)[1]) == ready['ready'] and ready['passed'] is True
        and ready['ready']['static']['all_match'] is True)
require('ready-cargo-bookkeeping-exact', ready['ready']['static']['cache_runtime_state']['cargo'] == load(W / 'cargo-bookkeeping.after.json'))
delivery = Path(ready['ready']['primary']['path'])
bind(delivery, ready['ready']['primary']['sha256'])
delivery_record = load(delivery)
bind(REPO / delivery_record['seal']['path'], ready['ready']['primary']['seal_sha256'])
require('primary-gate-not-weakened', old_controller.replace(old_output, new_output) == new_controller
    and 'len(planned) != 96 or len(completed) != 96' in new_controller)
receipt('ready', 2)
receipt('stage-readiness', 1)
require('initial-ready-refusal-preserved', "STRICT_NATIVE_NOT_READY: [Errno 2] No such file or directory:" in (W / 'ready.stdout').read_text())
protection = load(W / 'finalization-after-fix-v1/protection-comparison.json')
require('protection-saved-complete', protection['passed'] is True and
    all(protection[k] is True for k in ('old_source_exact', 'old_tools_and_evidence_exact', 'old_virq_cache_exact',
    'old_cargo_immutable_exact', 'old_cargo_runtime_exact_before_after', 'candidate_cache_immutable_exact_post_ready')))
protected_before = load(W / 'protected.before.json')
protected_after = load(W / 'finalization-after-fix-v1/protected.after.json')
require('protected-before-after-exact', protected_before == protected_after and len(protected_before) == 54)
for name in (str(OLD / 'AB1.once'), str(OLD / 'freeze-manifest.json'),
    str(R / 'raw/strict-native-phase-v1/AB1/run-result.json'), str(R / 'raw/strict-native-phase-v1/AB1/capture.json')):
    require('selected-protected-current:' + name, identity(name) == protected_before[name])
require('current-no-new-quota-marker-or-output', not any((TOOLS / (case + '.once')).exists() or
    (R / 'raw/strict-native-phase-v2' / case).exists() for case in ('AB1', 'AB0', '0')))
phases = load(W / 'orchestration-sessions.json')['phases']
require('initial-prepare-guard-preserved', phases[0]['actual_exit'] == 1 and phases[0]['candidate_paths_created'] is False
    and 'fs/ax-fs-ng/src/block/cache/address_space.rs' in phases[0]['stderr'])
incident = report['audit_finalizer_incident']
actual_stop = load(W / 'finalize-slow-toolcompletion-v1.json')
signal = load(W / 'finalize-slow-signal-v1.json')
witness = load(W / 'finalize-slow-host-witness-v1.json')
require('helper-incident-honest-separate-waits', incident['actual_unified_exec_exit'] == 143 == actual_stop['actual_unified_exec_result']['exit_code']
    and actual_stop['custom_Popen_parent_wait_available'] is False and incident['corrected_real_Popen_wait'] == 0
    and incident['Root_host_proc_verification_and_exact_helper_SIGTERM'] is True)
require('helper-exact-signal-evidence', signal['exact_process_before_signal'] == {k:v for k,v in witness['matches'][0].items() if k != 'state'}
    and signal['signal'] == 'SIGTERM' and signal['exact_process_before_signal']['pid'] == 2243671
    and signal['exact_process_before_signal']['starttime'] == '50352998' and signal['signal_to_parent'] is False
    and signal['signal_to_group'] is False and signal['hardware_or_old_process_signal'] is False)
require('slow-script-explicitly-reconstructed', actual_stop['reconstructed_loaded_script'] == 'finalize.slow-v1.py.txt'
    and load(W / 'finalize-corrected-script-identity.json')['first_loaded_slow_script_is_reconstructed'] is True
    and digest(W / 'finalize.slow-v1.py.txt') == witness['slow_original_reconstructed_copy_sha256'])
receipt('finalize-after-fix-v1', 0)
require('report-restricts-offline-conclusion', report['decision'] == 'OFFLINE_PREPARATION_PASS_PENDING_INDEPENDENT_REVIEWS'
    and report['offline_status'] == 'PASS' and all(report[k] is False for k in ('normal_host_validation',
    'trace_capacity_fix_real_board_proven', 'hardware_authorized', 'M2', 'Joint', 'goal',
    'Root_independent_copy_check_complete', 'independent_Spec_complete', 'independent_Quality_complete'))
    and report['hardware_started'] == report['qemu_started'] == 0 and set(report['cases'].values()) == {'NOT_EXECUTED'})
old_AB1 = load(R / 'raw/strict-native-phase-v1/AB1/run-result.json')
require('old-AB1-failure-preserved', old_AB1['full_function_passed'] is False and
    old_AB1['completion_state'] == 'failed-stop-remaining' and old_AB1['release'] == 'unknown')
result = {'schema_version': 1, 'scope': 'Task1 independent Spec identity and semantic review only',
    'passed': all(c['passed'] for c in checks), 'check_count': len(checks),
    'failures': [c for c in checks if not c['passed']], 'checks': checks, 'identities': evidence,
    'limits': {'builds_run': 0, 'qemu_run': 0, 'board_run': 0, 'ready_repeated': 0,
        'proc_read': 0, 'signals_sent': 0, 'full96_rescan': False, 'full_cache_traversal': False,
        'full_ordinary_current_rescan': False, 'full_ordinary_basis': 'frozen manifest comparison plus original ready/finalizer saved full checks',
        'cache_basis': 'frozen manifest comparison, selected actual paths, saved actual full static/protection checks'}}
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
sys.exit(0 if result['passed'] else 1)
