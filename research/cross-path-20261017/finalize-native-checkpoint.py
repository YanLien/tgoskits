#!/usr/bin/env python3
"""Verify native checkpoint records and refresh the archive checksum manifest."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
report = json.loads((archive/'results/native-timechain-audit.json').read_text())
assert len(report['runs']) == 1 and len(report['rejected_runs']) == 4
assert not report['M1_complete'] and not report['M2_complete']
assert json.loads((archive/'results/native-board-reset-triage.json').read_text())['accepted'] is False
production = subprocess.check_output(
    ['git', 'diff', '--name-only', 'HEAD', '--', 'virtualization/axvm/src', 'components/axcpu/src'],
    cwd=repo, text=True)
assert not production.strip(), production
patch = json.loads((archive/'results/native-timechain-patch-audit.json').read_text())
assert patch['isolated_apply_matches_live_sources'] and len(patch['changed']) == 14
for name, change in patch['changed'].items():
    assert hashlib.sha256((repo/name).read_bytes()).hexdigest() == change['after_sha256']
for name in list(report['runs']) + list(report['rejected_runs']):
    config = archive/'configs'/name
    identity = json.loads((config/'provenance.json').read_text())
    assert int((config/'exit-code.txt').read_text()) == identity['exit_code']
    with tarfile.open(archive/identity['source_archive']) as snapshot:
        assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == checksum
                   for p, checksum in identity['source_sha256'].items())
paths = sorted(p for p in archive.rglob('*')
               if p.is_file() and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts)
for path in paths:
    if path.suffix == '.json':
        json.loads(path.read_text())
manifest = archive/'SHA256SUMS'
manifest.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(repo)}\n'
                            for p in paths))
checked = subprocess.run(['sha256sum', '-c', str(manifest)], cwd=repo,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
assert checked.returncode == 0, checked.stdout
print(f'NATIVE_CHECKPOINT_OK manifest_files={len(paths)} production_axvm_axcpu_clean=True')
