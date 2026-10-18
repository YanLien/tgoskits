#!/usr/bin/env python3
"""Exercise the complete saved-AB1 capture contract, with failures reaching the caller."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--fixture', type=Path)
    args = parser.parse_args()
    if args.fixture:
        args.fixture = args.fixture.resolve()
    args.out.mkdir()
    refs = json.loads((HERE / 'input-refs.json').read_text())
    for label, row in refs.items():
        if label == 'copied_dependencies':
            continue
        path = Path(row['path'])
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], label
    original = json.loads(Path(refs['original_capture']['path']).read_text())
    assert original['artifact_chain_complete'] is False
    assert original['errors'] == ['FIT component has no integrity hash']
    inputs = json.loads((args.tools / 'inputs.json').read_text())
    assert sha(args.tools / 'inputs.json') == refs['original_inputs']['sha256']
    for relative, row in refs['copied_dependencies'].items():
        if relative == 'capture_native.py':
            continue
        copied = args.tools / relative
        assert copied.is_file() and not copied.is_symlink()
        assert copied.stat().st_size == row['bytes'] and sha(copied) == row['sha256'], relative
    rows = {}
    for label, row in original['artifacts'].items():
        paths = {'saved': Path(row['saved']), 'live': Path(row['path'])}
        observed = {}
        for kind, path in paths.items():
            assert not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), str(path)
            observed[kind] = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
            assert observed[kind]['bytes'] == row['bytes'] and observed[kind]['sha256'] == row['sha256'], label + '/' + kind
        rows[label] = {'expected_bytes': row['bytes'], 'expected_sha256': row['sha256'], **observed}
    assert len(rows) == 17 and sum(row['expected_bytes'] for row in rows.values()) == 110032235
    write_new(args.out / 'pre-capture-17-identities.json', {'all_match': True, 'count': 17, 'artifacts': rows})
    spec = importlib.util.spec_from_file_location('candidate_capture', args.tools / 'capture_native.py')
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    log = Path(refs['original_log']['path'])
    if args.fixture:
        fixture = json.loads((args.fixture / 'fixture.json').read_text())
        assert fixture['scope'] == 'synthetic software-only relocation; no boot or Guest runtime data'
        assert fixture['changed_payload_bytes'] == 1 and fixture['changed_artifact_labels'] == ['host_fit']
        # Relocate only input paths; every binding and validation function remains real.
        capture.TARGET = args.fixture / 'target'
        log = args.fixture / 'synthetic-relocation.log'
    evidence = capture.capture_native(args.out, log, 'AB1')
    print(json.dumps({'artifact_chain_complete': evidence['artifact_chain_complete'], 'errors': evidence['errors']}, sort_keys=True), flush=True)
    assert evidence['artifact_chain_complete'] is True, 'complete capture rejected: ' + repr(evidence['errors'])
    assert evidence['errors'] == []
    assert evidence['capture_phase'] == 'post-exit' and evidence['boot_before_identity_verified'] is False
    assert evidence['host_function_passed'] is False
    assert set(evidence['artifacts']) == set(original['artifacts'])
    for label, row in original['artifacts'].items():
        assert evidence['artifacts'][label]['sha256'] == row['sha256']
        assert evidence['artifacts'][label]['bytes'] == row['bytes']
    for name in ('kernel', 'ramdisk', 'fdt'):
        component = evidence['fit_components'][name]
        assert component['hashes'] == [] and component['integrity_hash_present'] is False
    assert evidence['preset_vs_fit_fdt']['canonical_tree_matches_fixed_ostool_transform'] is True
    rootfs = json.loads((args.out / 'rootfs.json').read_text())
    assert {name for name, row in rootfs['members'].items() if row['type'] == 'file'} == {'init', 'bin/busybox', 'bin/ordinary-load'}
    assert rootfs['changed_content'] == ['init']
    assert rootfs['binary_bytes_equal_original'] is True and rootfs['init_equals_actual_source_expression'] is True
    write_new(args.out / 'contract.json', {'passed': True, 'scope': 'post-exit complete original capture pipeline; no runtime function proof'})
    print('PASS: complete post-exit capture contract', flush=True)


if __name__ == '__main__':
    main()
