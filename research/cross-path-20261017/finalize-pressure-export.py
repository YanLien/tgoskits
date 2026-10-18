#!/usr/bin/env python3
"""Verify the frozen pressure-export checkpoint and refresh its manifest."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads((archive/p).read_text())
names = ['pressure-export-board-memory-sgi-32','pressure-export-qemu-memory-sgi-32']
audit = read('results/native-timechain-audit.json')
assert not audit['M1_complete'] and not audit['M2_complete']
identities = []
for name in names:
    identity = read(f'configs/{name}/provenance.json')
    identities.append(identity)
    assert identity['exit_code'] == 0
    assert all(digest(repo/p) == h for p,h in identity['source_sha256'].items())
    assert all(digest(repo/p) == h for p,h in identity['host_source_sha256'].items())
    result = audit['runs'][name]
    assert result['independent_analysis_passed']
    assert result['dropped'] == result['incomplete'] == 0
    assert sum(p['samples'] for p in result['policies'].values()) == 64
    export = read(f'results/{name}-export-audit.json')
    assert export['frozen_before_export'] and export['vm_groups_retired_before_export']
    assert export['dropped'] == export['incomplete'] == 0
    assert export['raw_log_sha256'] == digest(archive/'raw'/(name+'.log'))
    assert export['raw_log_sha256'] == identity['raw_log_sha256']
    assert export['trace_records'] == result['trace_records']
    assert 'VIRQ_DIAGNOSTIC_' not in (archive/'configs'/name/'environment.txt').read_text()
for key in ('source_sha256','host_source_sha256','cargo_lock_sha256'):
    assert identities[0][key] == identities[1][key]
patch = read('results/pressure-export-patch-audit.json')
assert patch['isolated_apply_matches_live_sources'] and len(patch['changed']) == 2
assert all(digest(repo/p) == h['after_sha256'] for p,h in patch['changed'].items())
fix = read('results/private-ram-patch-audit.json')
assert digest(repo/fix['source']) == fix['after_sha256']
assert 'bulk pressure export preceded VM retirement' in (archive/'raw/pressure-export-order-red.log').read_text()
assert 'passed checks: 21, failed checks: 0, skipped checks: 0' in (archive/'raw/pressure-export-clippy.log').read_text()
for kind in ('board','qemu'):
    output = (archive/f'raw/pressure-export-{kind}-analysis.log').read_text()
    assert 'verified periodic-aware analyses:' in output and 'LINUX_FENCE_ANALYSIS_OK policies=2' in output
paths = sorted(p for p in archive.rglob('*') if p.is_file()
               and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix == '.json':
        json.loads(path.read_text())
manifest = archive/'SHA256SUMS'
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(repo)}\n' for p in paths))
result = subprocess.run(['sha256sum','-c',str(manifest)],cwd=repo,
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
assert result.returncode == 0, result.stdout
print(f'PRESSURE_EXPORT_CHECKPOINT_OK files={len(paths)} new_accepted_tasks=128 M1=0 M2=0')
