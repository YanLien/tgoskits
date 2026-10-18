#!/usr/bin/env python3
"""Freeze the one-file RAM fix and replay it against the recorded original."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
name = 'virtualization/axvm/src/arch/aarch64/vm.rs'
baseline = archive/'configs/reset-cache-experiment-before.tar'
with tarfile.open(baseline) as snapshot:
    before = snapshot.extractfile(name).read()
after = (repo/name).read_bytes()
expected = subprocess.check_output(['git','show','HEAD:'+name], cwd=repo)
assert before == expected, 'baseline differs from HEAD'
assert b'VIRQ_DIAGNOSTIC' not in after and b'VIRQ_RAM_CACHE_DIAGNOSTIC' not in after
patch = archive/'patches/aarch64-private-ram-cold-start.patch'
patch.write_text(f'diff --git a/{name} b/{name}\n'+''.join(difflib.unified_diff(
    before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
    fromfile='a/'+name, tofile='b/'+name)))
with tempfile.TemporaryDirectory(prefix='private-ram-patch-') as directory:
    root = Path(directory)
    original = root/name
    original.parent.mkdir(parents=True)
    original.write_bytes(before)
    subprocess.run(['git','apply','--check',str(patch)],cwd=root,check=True)
    subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
    assert original.read_bytes() == after
changed = subprocess.check_output(['git','diff','--name-only','HEAD','--','virtualization/axvm/src'],cwd=repo,text=True).splitlines()
assert changed == [name], changed
report = dict(baseline=str(baseline.relative_to(archive)),
              baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
              git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
              source=name, before_sha256=hashlib.sha256(before).hexdigest(),
              after_sha256=hashlib.sha256(after).hexdigest(),
              patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
              isolated_apply_matches_live_source=True, temporary_production_probes_removed=True,
              scope='AArch64 allocator-owned RAM before cold vCPU creation; no reserved/shared RAM claim')
(archive/'results/private-ram-patch-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print('PRIVATE_RAM_PATCH_OK files=1 temporary_probes_removed=1')
