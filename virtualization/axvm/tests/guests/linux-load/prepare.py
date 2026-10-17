#!/usr/bin/env python3
"""Build a source-backed Linux CPU worker and its isolated Guest resources."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

KERNEL_SHA = 'c5403e99b9ae7a8c60c393fb2a97e637ded3e049179bb1b2f63cf6b94dd2a61a'
BASE_SHA = 'f71e2d9dd7ef4019de3880347c2896eb8507ceebb3b442b941d909954ccdc6eb'


def checked_file(variable, expected):
    path = Path(os.environ[variable]).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(variable+' checksum mismatch')
    return path


def extract_base(data, root):
    offset = 0
    while offset < len(data):
        if data[offset:offset+6] != b'070701':
            raise ValueError('unexpected base initramfs format')
        h = [int(data[offset+6+i*8:offset+14+i*8], 16) for i in range(13)]
        offset += 110
        if h[11] < 1 or offset+h[11] > len(data) or data[offset+h[11]-1] != 0:
            raise ValueError('invalid archive name')
        name = data[offset:offset+h[11]-1].decode()
        offset = (offset+h[11]+3)&~3
        payload = data[offset:offset+h[6]]
        if len(payload) != h[6]:
            raise ValueError('truncated base initramfs')
        offset = (offset+h[6]+3)&~3
        if name == 'TRAILER!!!':
            if any(data[offset:]):
                raise ValueError('unexpected trailing base archive data')
            return
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe archive path')
        dest = root/relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        kind = stat.S_IFMT(h[1])
        if kind == stat.S_IFDIR:
            dest.mkdir(exist_ok=True)
        elif kind == stat.S_IFREG:
            dest.write_bytes(payload)
            dest.chmod(stat.S_IMODE(h[1]))
        elif kind == stat.S_IFLNK:
            target = payload.decode()
            if Path(target).is_absolute() or '..' in Path(target).parts:
                raise ValueError('unsafe archive symlink')
            dest.symlink_to(target)
        else:
            raise ValueError('unsupported base initramfs entry type')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    kernel = checked_file('VIRQ_LINUX_KERNEL', KERNEL_SHA)
    base = checked_file('VIRQ_LINUX_INITRAMFS_BASE', BASE_SHA)
    output = args.output.resolve()/'linux'
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('workload.c')
    compiler = os.environ['CROSS_COMPILE']+'gcc'
    binary = output/'ordinary-load'
    command = [compiler, '-O2', '-static', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)]
    subprocess.run(command, check=True)
    with tempfile.TemporaryDirectory(prefix='linux-root-', dir=output) as directory:
        root = Path(directory)
        extract_base(gzip.decompress(base.read_bytes()), root)
        shutil.copyfile(binary, root/'bin/ordinary-load')
        (root/'bin/ordinary-load').chmod(0o755)
        (root/'init').write_text('#!/bin/busybox sh\nset -eu\n/bin/busybox mount -t proc proc /proc\n/bin/busybox mount -t sysfs sysfs /sys\n/bin/busybox mount -t devtmpfs devtmpfs /dev\nexec /bin/ordinary-load\n')
        (root/'init').chmod(0o755)
        subprocess.run(['cargo','xtask','image','pack-initramfs',str(root),str(output/'initramfs.cpio.gz'),'--gzip'],check=True)
    shutil.copyfile(kernel, output/'linux.kernel')
    (output/'vm.toml').write_text('''[base]
id = 1
name = "linux-ordinary-cpu"
guest_type = "virtualized"
cpu_num = 1
phys_cpu_ids = [3]
[kernel]
entry_point = 0x80200000
kernel_path = "linux.kernel"
kernel_load_addr = 0x80200000
dtb_load_addr = 0x80000000
ramdisk_path = "initramfs.cpio.gz"
ramdisk_load_addr = 0x84000000
cmdline = "console=ttyAMA0 rdinit=/init devtmpfs.mount=1 quiet loglevel=0"
memory_regions = [[0x80000000, 0x40000000, 0x7, 0]]
[devices]
passthrough = []
disabled = []
''')
    (output/'build.json').write_text(json.dumps(dict(command=command,kernel_sha256=KERNEL_SHA,base_initramfs_sha256=BASE_SHA,
        workload_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        workload_elf_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        initramfs_sha256=hashlib.sha256((output/'initramfs.cpio.gz').read_bytes()).hexdigest()),indent=2)+'\n')


if __name__ == '__main__':
    main()
