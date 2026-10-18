#!/usr/bin/env python3
"""Build an incremental patch against the preserved pre-memory worktree."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

archive = Path('research/cross-path-20261017')
names = ['vcpu_runtime.rs', 'support/linux.rs', 'guests/virq/prepare.py',
         'guests/linux-load/prepare.py', 'guests/linux-load/workload.c',
         'guests/linux-load/README.md', 'analysis/analyze_virq_load.py',
         'analysis/analyze_virq_irq_service.py', 'analysis/test_virq_load_analysis.py']
paths = ['virtualization/axvm/tests/' + name for name in names]
patch = archive/'patches/linux-memory-pressure.patch'
with tarfile.open(archive/'configs/linux-memory-before.tar') as baseline:
    differences = []
    for path in paths:
        before = baseline.extractfile(path).read().decode()
        after = Path(path).read_text()
        differences.extend(difflib.unified_diff(before.splitlines(keepends=True),
            after.splitlines(keepends=True), fromfile='a/'+path, tofile='b/'+path))
    patch.write_text(''.join(differences))
    with tempfile.TemporaryDirectory(prefix='memory-patch-') as temporary:
        root = Path(temporary)
        for path in paths:
            dest = root/path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(baseline.extractfile(path).read())
        subprocess.run(['git', 'apply', '--check', str(patch.resolve())], cwd=root, check=True)
        subprocess.run(['git', 'apply', str(patch.resolve())], cwd=root, check=True)
        assert all((root/path).read_bytes() == Path(path).read_bytes() for path in paths)
report = dict(baseline='configs/linux-memory-before.tar', patch=str(patch.relative_to(archive)),
              patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
              files=paths, apply_check=True, applied_files_equal_current=True)
(archive/'results/linux-memory-patch-verification.json').write_text(json.dumps(report, indent=2)+'\n')
print('incremental memory patch applies and reproduces all changed files')
