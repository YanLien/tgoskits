#!/usr/bin/env python3
"""Build an incremental patch against the preserved pre-periodic worktree."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

archive = Path('research/cross-path-20261017')
names = ['vcpu_runtime.rs', 'support/task_completion.rs', 'support/periodic.rs',
         'guests/virq/prepare.py', 'guests/virq/src/main.c', 'guests/virq/CMakeLists.txt',
         'analysis/analyze_virq_task.py', 'analysis/analyze_virq_periodic.py',
         'analysis/test_virq_task_analysis.py', 'analysis/test_virq_periodic_analysis.py',
         'analysis/analyze_virq_runtime.py',
         'guests/linux-load/README.md']
paths = ['virtualization/axvm/tests/' + name for name in names]
patch = archive/'patches/periodic-release.patch'
with tarfile.open(archive/'configs/periodic-before.tar') as baseline:
    differences = []
    for path in paths:
        old = baseline.extractfile(path) if path in baseline.getnames() else None
        before = old.read().decode() if old is not None else ''
        after = Path(path).read_text()
        differences.extend(difflib.unified_diff(before.splitlines(keepends=True),
            after.splitlines(keepends=True), fromfile='a/'+path if old is not None else '/dev/null', tofile='b/'+path))
    patch.write_text(''.join(differences))
    with tempfile.TemporaryDirectory(prefix='periodic-patch-') as temporary:
        root = Path(temporary)
        for path in paths:
            dest = root/path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path in baseline.getnames():
                dest.write_bytes(baseline.extractfile(path).read())
        subprocess.run(['git', 'apply', '--check', str(patch.resolve())], cwd=root, check=True)
        subprocess.run(['git', 'apply', str(patch.resolve())], cwd=root, check=True)
        assert all((root/path).read_bytes() == Path(path).read_bytes() for path in paths)
report = dict(baseline='configs/periodic-before.tar', patch=str(patch.relative_to(archive)),
              patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
              files=paths, apply_check=True, applied_files_equal_current=True)
(archive/'results/periodic-patch-verification.json').write_text(json.dumps(report, indent=2)+'\n')
print('incremental periodic patch applies and reproduces all changed files')
