#!/usr/bin/env python3
"""Freeze concrete build artifacts before a subsequent cohort can replace them."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

archive = Path('research/cross-path-20261017')
name = sys.argv[1]
output = archive / 'configs' / name
root = Path('target/axbuild/axvm/vcpu-runtime')
for source, dest in [(root/'resources/tests/vcpu-runtime.toml', 'measurement.toml'),
                     (root/'vm.toml', 'realtime-vm.toml'),
                     (root/'guest/zephyr/.config', 'zephyr.config'),
                     (root/'linux/vm.toml', 'linux-vm.toml'),
                     (root/'linux/build.json', 'linux-build.json')]:
    if source.is_file():
        shutil.copyfile(source, output/dest)
paths = list(root.rglob('*'))
paths += list(Path('target/aarch64-unknown-linux-musl/release/build/axvm').glob('*/out/*'))
paths += list(Path('target/axbuild/axvm').glob('*initramfs*'))
paths.append(Path('target/axbuild/axvisor/host-initramfs/aarch64.cpio'))
log = (archive/'raw'/(name+'.log')).read_text()
paths += [Path(p) for p in re.findall(r'^host initramfs: (.+)$', log, re.M)]
paths += [Path(p) for p in re.findall(r'cargo build elf=(\S+)', log)]
hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
          if p.is_file() and (p.suffix in ('.bin', '.elf', '.cpio', '.gz', '.kernel')
                             or p.name == 'ordinary-load' or p.suffix == '')}
sources = [p for p in Path('virtualization/axvm/tests').rglob('*')
           if p.is_file() and p.suffix in ('.py', '.rs', '.c', '.h', '.toml', '.txt')]
metadata = dict(scope='QEMU functional evidence; no hardware performance conclusion',
    git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), dirty=True,
    source_archive='configs/linux-memory-sources.tar.gz',
    source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    artifact_sha256=hashes,
    cargo_lock_sha256=hashlib.sha256(Path('Cargo.lock').read_bytes()).hexdigest(),
    exit_code=int((output/'exit-code.txt').read_text()))
with tarfile.open(archive/metadata['source_archive']) as snapshot:
    assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == digest
               for p, digest in metadata['source_sha256'].items()), 'source changed during cohort'
metadata['source_archive_sha256'] = hashlib.sha256((archive/metadata['source_archive']).read_bytes()).hexdigest()
assert any('host-initramfs/' in p and p.endswith('.cpio') for p in hashes), 'missing Host initramfs identity'
(output/'provenance.json').write_text(json.dumps(metadata, indent=2)+'\n')
print(f'captured {name}: {len(hashes)} artifact hashes, exit={metadata["exit_code"]}')
