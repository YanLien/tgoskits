#!/usr/bin/env python3
"""Freeze concrete build artifacts before a subsequent cohort can replace them."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

archive = Path('research/cross-path-20261017')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('name')
parser.add_argument('--runtime', choices=('qemu', 'board'), default='qemu')
args = parser.parse_args()
name = args.name
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
raw_log = (archive/'raw'/(name+'.log')).read_bytes()
log = raw_log.decode('utf-8', errors='replace')
host_dtbs = [Path(p) for p in re.findall(r'Using DTB from: (\S+)', log)]
host_fits = [Path(p) for p in re.findall(r'FIT image ok: (\S+)', log)]
paths += host_dtbs + host_fits
for source, dest in [(root/'guest/zephyr/zephyr.dtb', 'realtime-input.dtb'),
                     (root/'linux/machine.dtb', 'linux-input.dtb'),
                     (root/'guest/zephyr/zephyr.elf', 'realtime.elf'),
                     (root/'guest/zephyr/zephyr.bin', 'realtime.bin'),
                     (root/'guest/zephyr/zephyr.map', 'realtime.map')]:
    if source.is_file():
        shutil.copyfile(source, output/dest)
if args.runtime == 'board':
    for candidates, dest in ((host_dtbs, 'host-input.dtb'), (host_fits, 'host-boot.fit')):
        if candidates and candidates[-1].is_file():
            shutil.copyfile(candidates[-1], output/dest)
paths += [Path(p) for p in re.findall(r'^host initramfs: (.+)$', log, re.M)]
paths += [Path(p) for p in re.findall(r'cargo build elf=(\S+)', log)]
hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
          if p.is_file() and (p.suffix in ('.bin', '.elf', '.cpio', '.gz', '.kernel', '.dtb', '.fit', '.itb')
                             or p.name == 'ordinary-load' or p.suffix == '')}
sources = [p for p in Path('virtualization/axvm/tests').rglob('*')
           if p.is_file() and p.suffix in ('.py', '.rs', '.c', '.h', '.toml', '.txt', '.dts', '.overlay')]
metadata = dict(scope=('QEMU functional evidence; no hardware performance conclusion' if args.runtime == 'qemu'
                       else 'Board functional evidence; no interference or optimization conclusion'),
    runtime=args.runtime,
    capture_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    raw_log_sha256=hashlib.sha256(raw_log).hexdigest(),
    log_decode='UTF-8 with replacement for parsing; original bytes preserved',
    utf8_replacement_characters=log.count('\ufffd'),
    observed_platforms=sorted(set(re.findall(r'VIRQ_PLATFORM kind=(\S+)', log))),
    artifact_scope='Observed files after exit; failures can retain earlier build products, not all are proof of use',
    git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), dirty=True,
    source_archive=f'configs/{name}/sources.tar.gz',
    source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    artifact_sha256=hashes,
    cargo_lock_sha256=hashlib.sha256(Path('Cargo.lock').read_bytes()).hexdigest(),
    exit_code=int((output/'exit-code.txt').read_text()))
metadata['suite_passed'] = metadata['exit_code'] == 0
metadata['measurement_accepted'] = None
metadata['acceptance_scope'] = 'Runner exit only; independent offline validation is required'
with tarfile.open(archive/metadata['source_archive']) as snapshot:
    assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == digest
               for p, digest in metadata['source_sha256'].items()), 'source changed during cohort'
metadata['source_archive_sha256'] = hashlib.sha256((archive/metadata['source_archive']).read_bytes()).hexdigest()
host_archive = output/'host-sources.tar.gz'
if host_archive.is_file():
    host_sources = [p for p in Path('virtualization/axvm/src').rglob('*') if p.is_file()]
    metadata['host_source_archive'] = str(host_archive.relative_to(archive))
    metadata['host_source_archive_sha256'] = hashlib.sha256(host_archive.read_bytes()).hexdigest()
    metadata['host_source_sha256'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in host_sources}
    with tarfile.open(host_archive) as snapshot:
        assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == checksum
                   for p, checksum in metadata['host_source_sha256'].items()), 'Host source changed during cohort'
assert any('host-initramfs/' in p and p.endswith('.cpio') for p in hashes), 'missing Host initramfs identity'
if args.runtime == 'board' and metadata['exit_code'] == 0:
    assert metadata['observed_platforms'] == ['orangepi5plus_rk3588']
    assert (output/'host-input.dtb').is_file() and (output/'host-boot.fit').is_file()
(output/'provenance.json').write_text(json.dumps(metadata, indent=2)+'\n')
print(f'captured {name}: {len(hashes)} artifact hashes, exit={metadata["exit_code"]}')
