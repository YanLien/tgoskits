#!/usr/bin/env python3
"""Read-only focused quality evidence checks; never imports or runs candidate tools.

These are review assertions over source/evidence, not recorder behavior tests.
No directory traversal, proc access, network, signals, cargo or readiness calls.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

REPO = Path('/home/yanlien/Program/hypervisor/tgoskits')
R = REPO / 'research/cross-path-20261017'
W = R / 'raw/strict-native-phase-v2/task1'
TOOLS = Path('/tmp/crosspath-native-capacity-v2-tools-ksjtks3x')
SOURCE = Path('/tmp/crosspath-native-capacity-v2-src-z2au9vz8')
OLD_TOOLS = Path('/tmp/strict-native-phase-tools-kevemo32')
OLD_SOURCE = Path('/tmp/crosspath-strict-native-src-ii_h4jde')
checks = []
observed = {}


def digest(path):
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    observed[str(path)] = value
    return value


def identity(path):
    attrs = path.lstat()
    if stat.S_ISLNK(attrs.st_mode):
        return {'type': 'symlink', 'target': os.readlink(path)}
    if not stat.S_ISREG(attrs.st_mode):
        raise ValueError('not an ordinary file: ' + str(path))
    return {'sha256': digest(path), 'bytes': attrs.st_size,
            'mode': stat.S_IMODE(attrs.st_mode)}


def load(path):
    digest(path)
    return json.loads(path.read_text())


def check(name, condition, detail=None):
    checks.append({'name': name, 'passed': bool(condition), 'detail': detail})


def receipt(base, expected_wait):
    record = load(base.with_suffix('.receipt.json'))
    check(str(base.relative_to(W)) + ' wait/output identity',
          record['actual_Popen_wait'] == expected_wait
          and identity(base.with_suffix('.stdout')) == record['stdout']
          and identity(base.with_suffix('.stderr')) == record['stderr']
          and record['end_unix_ns'] > record['start_unix_ns'],
          {'wait': record['actual_Popen_wait'], 'argv': record['argv']})
    return record


def main():
    exact = {
        R/'design/phase2-native-trace-capacity-v2-design.md': '5dbf286e5275dde7f8553de3785835b246f8df6ef7ad2b2e010bbe9357bb3ccd',
        R/'design/phase2-native-trace-capacity-v2-plan-v2.md': '54a43488604d56ea9bf02b5cdf06d1ab9b6d8bceb4248f91504c00e491534e27',
        R/'results/strict-native-trace-capacity-v2-task1.json': '74eace0f3fd2a8611fcb49fe981a754bb722104dc89efd737acddf81a5087429',
        R/'results/strict-native-trace-capacity-v2-task1-spec-review-v1.json': '4b3c61913884343e5207fc62b7533d7a38ebe00d9076d1c998f586018785d0d0',
        TOOLS/'freeze-manifest.json': '6d830c616cf8a3e0a958369b1719ed0e5d91800076afb78c38d46cc6d28280d9',
        TOOLS/'evidence/sources-702.json': '0f46afeee8f3dfb28408072480969a0791051e3546671ea29da42925318064eb',
        TOOLS/'capture_native.py': 'e1e573ed9ecd8a1dd77c80d6a06fff3739e4fa8114815cc2b6b5c826206a14b2',
    }
    for path, expected in exact.items():
        check('exact authority/candidate SHA ' + str(path), digest(path) == expected)
    report = load(R/'results/strict-native-trace-capacity-v2-task1.json')
    spec = load(R/'results/strict-native-trace-capacity-v2-task1-spec-review-v1.json')
    check('Spec precedes Quality with matching implementation',
          spec['decision'] == 'PASS' and spec['blockers'] == []
          and spec['reviewed_implementation_sha256'] == exact[R/'results/strict-native-trace-capacity-v2-task1.json'])
    frozen = load(TOOLS/'freeze-manifest.json')
    selected = ['native_once.py', 'capture_native.py', 'inputs.json',
                'evidence/sources-702.json', 'evidence/ordinary-identities.json',
                'evidence/control-identities.json',
                'evidence/capacity-v2-parent-sources-702.json',
                'evidence/capacity-v2-parent-inputs.json',
                'evidence/capacity-v2-authority-provenance.json',
                'evidence/authorities/strict-native-fit-capture-repair-spec-review-v1.json',
                'evidence/authorities/strict-native-fit-capture-repair-quality-review-v1.json',
                'evidence/authorities/strict-native-fit-capture-repair-root-acceptance-v1.json']
    for name in selected:
        check('selected frozen execution/archive ' + name,
              identity(TOOLS/name) == frozen[name]
              and identity(W/'frozen-tools'/name) == frozen[name])
    for kind in ['spec-review', 'quality-review', 'root-acceptance']:
        authority = load(TOOLS/'evidence/authorities'/('strict-native-fit-capture-repair-'+kind+'-v1.json'))
        if kind == 'root-acceptance':
            accepted = (authority['accepted'] is True and authority['Spec_decision'] == 'PASS'
                        and authority['Quality_decision'] == 'PASS'
                        and authority['final_tool_sha256'] == exact[TOOLS/'capture_native.py'])
        else:
            accepted = authority['decision'] == 'PASS' and authority['blockers'] == []
        check('capture inherited actual acceptance ' + kind, accepted)

    source_manifest = load(TOOLS/'evidence/sources-702.json')
    parent_manifest = load(TOOLS/'evidence/capacity-v2-parent-sources-702.json')
    path = 'virtualization/axvm/src/diagnostics.rs'
    check('702 manifest delta only diagnostics',
          source_manifest.keys() == parent_manifest.keys() and len(source_manifest) == 702
          and [p for p in source_manifest if source_manifest[p] != parent_manifest[p]] == [path])
    before = (OLD_SOURCE/path).read_bytes()
    after = (SOURCE/path).read_bytes()
    old = b'const CAPACITY: usize = 16_384;'
    new = (b'// Measurement capacity uses 10 MiB of slots across four CPUs.\n'
           b'// Its memory cost requires new matched recording-on/off measurements.\n'
           b'const CAPACITY: usize = 65_536;')
    check('whole recorder equals parent except documented capacity delta',
          before.count(old) == 1 and before.replace(old, new) == after
          and digest(OLD_SOURCE/path) == parent_manifest[path]
          and digest(SOURCE/path) == source_manifest[path])
    ordinary = load(TOOLS/'evidence/ordinary-identities.json')
    for name in [path, 'Cargo.lock', 'virtualization/axvm/tests/vcpu_runtime.rs',
                 'virtualization/axvm/tests/guests/virq/prepare.py']:
        check('current semantic anchor ' + name, identity(SOURCE/name) == ordinary[name])
        if name != path:
            check('parent semantic anchor unchanged ' + name, digest(SOURCE/name) == digest(OLD_SOURCE/name))
    for name, expected in load(TOOLS/'evidence/control-identities.json').items():
        check('control unchanged ' + name, identity(SOURCE/name) == expected
              and identity(OLD_SOURCE/name) == expected)
    old_controller = (OLD_TOOLS/'native_once.py').read_text()
    new_controller = (TOOLS/'native_once.py').read_text()
    mapped = old_controller.replace("ARCHIVE/'raw/strict-native-phase-v1'/args.run",
                                    "ARCHIVE/'raw/strict-native-phase-v2'/args.run")
    check('whole controller only output root delta', mapped == new_controller
          and old_controller != mapped
          and ast.dump(ast.parse(mapped)) == ast.dump(ast.parse(new_controller)))
    approved = R/'raw/strict-native-followup-v1/fit-capture-repair-v1/repaired/capture_native.py'
    check('capture same accepted executable bytes', digest(approved) == digest(TOOLS/'capture_native.py'))

    inputs = load(TOOLS/'inputs.json')
    parent_inputs = load(TOOLS/'evidence/capacity-v2-parent-inputs.json')
    mutable_keys = {'source', 'target', 'execution_tools_root', 'environment', 'normal702_sha256'}
    check('non-path inputs and all limits preserved',
          inputs.keys() == parent_inputs.keys()
          and all(inputs[k] == parent_inputs[k] for k in inputs if k not in mutable_keys))
    replacements = {str(OLD_TOOLS): str(TOOLS), parent_inputs['target']: inputs['target']}
    mapped_env = {k: v for k, v in parent_inputs['environment'].items()}
    for k, value in mapped_env.items():
        for old_prefix, new_prefix in replacements.items():
            value = value.replace(old_prefix, new_prefix)
        mapped_env[k] = value
    check('environment only approved prefix changes', mapped_env == inputs['environment'])

    relocation = load(W/'cache-relocation.json')
    old_cache = OLD_TOOLS/'cache/vcpu-runtime-cache'
    cache = TOOLS/'cache/vcpu-runtime-cache'
    for row in relocation['changes']:
        name = row['path']
        old_bytes = (old_cache/name).read_bytes()
        mapped_bytes = old_bytes
        for old_prefix, new_prefix in relocation['prefix_replacements'].items():
            mapped_bytes = mapped_bytes.replace(old_prefix.encode(), new_prefix.encode())
        check('actual relocated entry minimal delta ' + name,
              (name.startswith('venv/bin/') or name == 'venv/pyvenv.cfg')
              and not old_bytes.startswith(b'\x7fELF')
              and mapped_bytes == (cache/name).read_bytes()
              and identity(old_cache/name) == row['old']
              and identity(cache/name) == row['new']
              and row['old']['mode'] == row['new']['mode'])
    check('relocation complete approved local set', len(relocation['changes']) == 13
          and relocation['changed_count'] == 13 and relocation['all_other_cache_members_unchanged'])
    for name, expected in relocation['system_python_links'].items():
        check('preserved system interpreter symlink ' + name,
              identity(cache/name) == expected and identity(old_cache/name) == expected)
    link = load(W/'cache-production-entry-link.json')
    probe = json.loads((W/'cache-python-probe.stdout').read_text())
    check('production Python/CMake resolution proof', link['probe'] == probe
          and identity(Path(link['entry'])) == link['entry_identity']
          and identity(Path(link['cmake_module'])) == link['module_identity']
          and Path(link['entry']).read_text() == link['entry_text']
          and Path(link['cmake_module']).read_text() == link['module_text']
          and all(Path(probe[k]).is_relative_to(cache) for k in
                  ['sys_prefix', 'sys_executable', 'cmake_module', 'CMAKE_BIN_DIR', 'cmake_binary'])
          and probe['interpreter_realpath'] == str((cache/'venv/bin/python3').resolve())
          and link['actual_entry_wait'] == 0)
    fmt = receipt(W/'cargo-fmt', 0)
    clippy = receipt(W/'cargo-xtask-clippy', 0)
    check('stable cargo entries and exclusive target actual receipts',
          fmt['argv'] == ['cargo', 'fmt', '-p', 'axvm']
          and clippy['argv'] == ['cargo', 'xtask', 'clippy', '--package', 'axvm']
          and fmt['cwd'] == clippy['cwd'] == str(SOURCE)
          and all(x['environment']['CARGO_TARGET_DIR'] == inputs['target']
                  and x['environment']['AXBUILD_TARGET_DIR'] == inputs['target'] for x in [fmt, clippy]))
    output = (W/'cargo-xtask-clippy.stdout').read_text()
    check('Clippy selected 29 actual successful checks',
          output.count('\nok: axvm (') == 29
          and 'passed checks: 29, failed checks: 0, skipped checks: 0' in output)
    for name in ['cache-python-probe', 'cache-cmake-direct']:
        record = receipt(W/name, 0)
        check(name+' isolated Python environment',
              'PYTHONPATH' not in record['environment'] and 'PYTHONHOME' not in record['environment'])
    first = receipt(W/'ready', 2)
    ready = receipt(W/'readiness-after-assets-v1/ready', 0)
    receipt(W/'readiness-after-assets-v1/reject-source', 2)
    receipt(W/'readiness-after-assets-v1/reject-approval', 2)
    state = load(W/'readiness-after-assets-v1/readiness.json')
    check('actual unchanged formal gates with side-effect blocker',
          state['passed'] and state['before_after_same']
          and state['new_once_markers'] == state['case_outputs_created'] == state['hardware_started'] == 0
          and state['target_existed_before_for_private_clippy']
          and first['argv'] == ready['argv']
          and 'OFFLINE_SIDE_EFFECT_FORBIDDEN' in ready['argv'][3])
    restored = load(R/'raw/strict-native-phase-v2/base-input-restoration-v1.json')
    check('exact fixed assets restoration keeps failure history',
          not restored['prior_original_AB1_capture_or_release_backfilled']
          and restored['candidate_freeze_sha256'] == exact[TOOLS/'freeze-manifest.json']
          and restored['historical_failures_and_initial_ready_rejection_preserved'])
    slow = load(W/'finalize-slow-toolcompletion-v1.json')
    incident = report['audit_finalizer_incident']
    check('actual helper incident unmasked',
          slow['actual_unified_exec_result']['exit_code'] == 143
          and slow['custom_Popen_parent_wait_available'] is False
          and incident['Root_host_proc_verification_and_exact_helper_SIGTERM'] is True
          and incident['custom_Popen_wait_not_available_for_old_session'] is True)
    receipt(W/'finalize-after-fix-v1', 0)
    spec_first = load(W/'spec-review-v1/receipt.json')
    spec_after = load(W/'spec-review-v1/receipt-after-gcc-link-v1.json')
    check('Spec checker failure/correction preserved',
          spec_first['actual_Popen_wait'] == 1 and spec_after['actual_Popen_wait'] == 0
          and spec['reviewer_checker_correction']['production_gate_changed'] is False)
    for key in ['normal_host_validation', 'trace_capacity_fix_real_board_proven', 'M2', 'Joint', 'goal', 'hardware_authorized']:
        check('bounded implementation claim ' + key, report[key] is False)
    check('hardware and cases remain unexecuted', report['hardware_started'] == report['qemu_started'] == 0
          and set(report['cases'].values()) == {'NOT_EXECUTED'}
          and not any((TOOLS/(case+'.once')).exists() or (R/'raw/strict-native-phase-v2'/case).exists()
                      for case in ['AB1', 'AB0', '0']))
    check('target used by Clippy is documented, not empty',
          report['materials']['exclusive_target_temporary']['logical_bytes'] > 10_000_000_000
          and report['candidate']['paths']['target_initial_members'] == [])
    check('historical review pending fields retained as historical',
          report['independent_Spec_complete'] is False and report['independent_Quality_complete'] is False
          and report['Root_independent_copy_check_complete'] is False)


try:
    main()
except Exception as exc:
    checks.append({'name': 'unexpected checker exception', 'passed': False,
                   'detail': type(exc).__name__ + ': ' + str(exc)})
passed = all(item['passed'] for item in checks)
print(json.dumps({'schema_version': 1, 'scope': 'focused read-only Quality review; not production runtime tests',
                  'passed': passed, 'check_count': len(checks), 'checks': checks,
                  'observed_sha256': observed}, indent=2, ensure_ascii=False, sort_keys=True))
sys.exit(0 if passed else 1)
