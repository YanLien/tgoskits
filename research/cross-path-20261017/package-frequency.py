#!/usr/bin/env python3
"""Verify a research source increment against its actual frozen worktree."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('name')
parser.add_argument('baseline', help='Path relative to this archive')
args = parser.parse_args()
assert re.fullmatch(r'[a-z0-9-]+', args.name)
archive = Path(__file__).resolve().parent
repo = archive.parent.parent
baseline = (archive/args.baseline).resolve()
assert baseline.is_relative_to(archive)
suffixes = {'.rs', '.py', '.c', '.h', '.toml', '.txt', '.cmake', '.md', '.dts', '.overlay'}
with tarfile.open(baseline) as snapshot:
    before = {m.name: snapshot.extractfile(m).read() for m in snapshot
              if m.isfile() and Path(m.name).suffix in suffixes and '__pycache__' not in m.name}
after = {str(p.relative_to(repo)): p.read_bytes()
         for tree in ('virtualization/axvm/tests', 'virtualization/axvm/src', 'components/axcpu', 'test-suit/arceos/cpu/pmu')
         for p in (repo/tree).rglob('*')
         if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts}
for name in before:
    path = (repo/name).resolve()
    assert path.is_relative_to(repo)
    if not name.startswith('virtualization/axvm/tests/') and path.is_file():
        after[name] = path.read_bytes()
changed = [p for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
assert changed
pieces = []
for path in changed:
    pieces.append(f'diff --git a/{path} b/{path}\n')
    if path not in before:
        pieces.append('new file mode 100644\n')
    pieces.extend(difflib.unified_diff(before.get(path, b'').decode().splitlines(keepends=True),
                                     after.get(path, b'').decode().splitlines(keepends=True),
                                     fromfile='a/'+path if path in before else '/dev/null',
                                     tofile='b/'+path if path in after else '/dev/null'))
patch = archive/'patches'/(args.name+'.patch')
patch.write_text(''.join(pieces))
with tempfile.TemporaryDirectory(prefix='research-patch-') as directory:
    root = Path(directory)
    with tarfile.open(baseline) as snapshot:
        snapshot.extractall(root, filter='data')
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=root, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=root, check=True)
    assert all((root/p).read_bytes() == content for p, content in after.items())
    assert all(not (root/p).exists() for p in before.keys()-after.keys())
report = dict(baseline=str(baseline.relative_to(archive)),
              baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
              patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
              isolated_apply_matches_live_sources=True,
              changed={p: dict(before_sha256=hashlib.sha256(before[p]).hexdigest() if p in before else None,
                               after_sha256=hashlib.sha256(after[p]).hexdigest() if p in after else None)
                       for p in changed})
(archive/'results'/(args.name+'-patch-audit.json')).write_text(json.dumps(report, indent=2)+'\n')
print(f'RESEARCH_PATCH_OK name={args.name} changed_files={len(changed)}')
