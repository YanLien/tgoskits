#!/usr/bin/env python3
"""Check the final reset-fix checkpoint and refresh all evidence checksums."""
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
audit = json.loads((archive/'results/native-timechain-audit.json').read_text())
accepted = {'native-private-ram-board-cpu-32','native-private-ram-qemu-cpu-32'}
assert set(audit['runs']) == accepted and len(audit['rejected_runs']) == 9
assert not audit['M1_complete'] and not audit['M2_complete']
for name in accepted | {'native-private-ram-board-memory-sgi-32'}:
    identity = json.loads((archive/'configs'/name/'provenance.json').read_text())
    assert all(digest(repo/p) == h for p,h in identity['source_sha256'].items())
    assert all(digest(repo/p) == h for p,h in identity['host_source_sha256'].items())
    environment = (archive/'configs'/name/'environment.txt').read_text()
    assert 'VIRQ_DIAGNOSTIC_' not in environment and 'VIRQ_BOOT_FAILURE_MEMORY=' not in environment
    assert '[[boot_failure_regions]]' not in (archive/'configs'/name/'measurement.toml').read_text()
for name in accepted:
    assert sum(p['samples'] for p in audit['runs'][name]['policies'].values()) == 64
    assert audit['runs'][name]['dropped'] == audit['runs'][name]['incomplete'] == 0
rejected = json.loads((archive/'results/native-pressure-rejection.json').read_text())
assert rejected['accepted_tasks'] == 0 and not rejected['measurement_accepted']
fix = json.loads((archive/'results/private-ram-patch-audit.json').read_text())
assert fix['isolated_apply_matches_live_source'] and fix['temporary_production_probes_removed']
assert digest(repo/fix['source']) == fix['after_sha256']
test_patch = json.loads((archive/'results/reset-diagnostics-patch-audit.json').read_text())
assert test_patch['isolated_apply_matches_live_sources'] and len(test_patch['changed']) == 5
assert all(digest(repo/p) == h['after_sha256'] for p,h in test_patch['changed'].items())
clippy = (archive/'raw/private-ram-final-clippy.log').read_text()
assert 'passed checks: 21, failed checks: 0, skipped checks: 0' in clippy
for name in ('board','qemu'):
    output = (archive/f'raw/native-private-{name}-analysis.log').read_text()
    assert 'verified periodic-aware analyses:' in output and 'LINUX_FENCE_ANALYSIS_OK policies=2' in output
paths = sorted(p for p in archive.rglob('*') if p.is_file()
               and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix == '.json':
        json.loads(path.read_text())
manifest = archive/'SHA256SUMS'
manifest.write_text(''.join(f'{digest(p)}  {p.relative_to(repo)}\n' for p in paths))
verified = subprocess.run(['sha256sum','-c',str(manifest)],cwd=repo,
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
assert verified.returncode == 0, verified.stdout
print(f'RESET_CHECKPOINT_OK manifest_files={len(paths)} accepted_tasks=128 rejected_pressure_tasks=64 M1=0 M2=0')
