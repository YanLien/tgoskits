#!/usr/bin/env python3
"""Make and independently apply the source increment against the frozen baseline."""

import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
baseline = archive/'configs/throughput-before.tar'
suffixes = {'.rs', '.py', '.c', '.h', '.toml', '.txt', '.cmake', '.md'}
with tarfile.open(baseline) as snapshot:
    before = {m.name: snapshot.extractfile(m).read() for m in snapshot
              if m.isfile() and Path(m.name).suffix in suffixes and '__pycache__' not in m.name}
after = {str(p.relative_to(repo)): p.read_bytes()
         for p in (repo/'virtualization/axvm/tests').rglob('*')
         if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts}
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
patch = archive/'patches/linux-fenced-throughput.patch'
patch.write_text(''.join(pieces))
with tempfile.TemporaryDirectory(prefix='throughput-patch-') as directory:
    root = Path(directory)
    with tarfile.open(baseline) as snapshot:
        snapshot.extractall(root, filter='data')
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=root, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=root, check=True)
    assert all((root/p).read_bytes() == content for p, content in after.items())
    assert all(not (root/p).exists() for p in before.keys()-after.keys())
result = dict(baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
              patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
              isolated_apply_matches_live_sources=True,
              changed={p: dict(before_sha256=hashlib.sha256(before[p]).hexdigest() if p in before else None,
                               after_sha256=hashlib.sha256(after[p]).hexdigest() if p in after else None)
                       for p in changed})
(archive/'results/throughput-patch-audit.json').write_text(json.dumps(result, indent=2)+'\n')
print(f'THROUGHPUT_PATCH_OK changed_files={len(changed)}')
