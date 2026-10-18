#!/usr/bin/env python3
"""Build a source-backed Linux CPU or memory worker and isolated Guest resources."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from guest_firmware import explicit_enabled, gic_layout, linux_host_cpu

KERNEL_SHA = 'c5403e99b9ae7a8c60c393fb2a97e637ded3e049179bb1b2f63cf6b94dd2a61a'
BASE_SHA = 'f71e2d9dd7ef4019de3880347c2896eb8507ceebb3b442b941d909954ccdc6eb'
BASE_PROFILES = {
    'legacy': BASE_SHA,
    'registry-v0.0.14': 'a6fe2ed7dace805e29b65c5dbee766e1c13449b162664faaf65f1775c630aa5b',
}


def fences_enabled():
    value = os.environ.get('VIRQ_LINUX_FENCES', '0')
    if value not in ('0', '1'):
        raise ValueError('VIRQ_LINUX_FENCES must be 0 or 1')
    return value == '1'


def memory_settings():
    scenario = os.environ.get('VIRQ_HOST_LOAD', 'linux_cpu')
    if scenario not in ('linux_cpu', 'linux_memory'):
        raise ValueError('Linux load requires linux_cpu or linux_memory')
    if scenario == 'linux_cpu':
        return 0, 1
    size = os.environ.get('VIRQ_LINUX_MEMORY_BYTES', '16777216')
    every = os.environ.get('VIRQ_LINUX_MEMORY_EVERY', '1')
    if not size.isascii() or not size.isdecimal() or not 1048576 <= int(size) <= 67108864 or int(size) % 8192:
        raise ValueError('VIRQ_LINUX_MEMORY_BYTES must be 1..64 MiB and 8192-byte aligned')
    if not every.isascii() or not every.isdecimal() or not 1 <= int(every) <= 1024:
        raise ValueError('VIRQ_LINUX_MEMORY_EVERY must be between 1 and 1024')
    return int(size), int(every)


def checked_file(variable, expected):
    path = Path(os.environ[variable]).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(variable+' checksum mismatch')
    return path


def extract_base(data, root, *, only_busybox=False):
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
            if only_busybox and not (root/'bin/busybox').is_file():
                raise ValueError('fixed registry base does not contain bin/busybox')
            return
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe archive path')
        # The registry profile supplies one static executable, not its device
        # nodes or unrelated guest images. The full archive SHA is checked first.
        if only_busybox and relative != Path('bin/busybox'):
            continue
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
    raise ValueError('base initramfs has no trailer')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    host_cpu = linux_host_cpu()
    memory_bytes, memory_every = memory_settings()
    fences = fences_enabled()
    explicit = explicit_enabled()
    kernel = checked_file('VIRQ_LINUX_KERNEL', KERNEL_SHA)
    profile = os.environ.get('VIRQ_LINUX_BASE_PROFILE', 'legacy')
    if profile not in BASE_PROFILES:
        raise ValueError('unsupported VIRQ_LINUX_BASE_PROFILE: '+profile)
    base_sha = BASE_PROFILES[profile]
    base = checked_file('VIRQ_LINUX_INITRAMFS_BASE', base_sha)
    output = args.output.resolve()/'linux'
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('workload.c')
    compiler = os.environ.get('VIRQ_LINUX_CC')
    if compiler is None:
        prefix = os.environ.get('CROSS_COMPILE')
        if prefix is None:
            raise ValueError('set VIRQ_LINUX_CC or CROSS_COMPILE for the Linux userspace worker')
        compiler = prefix+'gcc'
    if not Path(compiler).is_absolute() or not Path(compiler).is_file():
        raise ValueError('Linux compiler must be an existing absolute executable path')
    compiler_version = subprocess.run([compiler, '--version'], check=True, capture_output=True, text=True).stdout.splitlines()[0]
    binary = output/'ordinary-load'
    command = [compiler, '-O2', '-static', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)]
    command += [f'-DLINUX_MEMORY_BYTES={memory_bytes}ULL', f'-DLINUX_MEMORY_EVERY={memory_every}']
    command += [f'-DLINUX_FENCES={int(fences)}']
    subprocess.run(command, check=True)
    with tempfile.TemporaryDirectory(prefix='linux-root-', dir=output) as directory:
        root = Path(directory)
        extract_base(gzip.decompress(base.read_bytes()), root, only_busybox=profile != 'legacy')
        if profile != 'legacy':
            for name in ('dev', 'proc', 'sys', 'tmp'):
                (root/name).mkdir(exist_ok=True)
        shutil.copyfile(binary, root/'bin/ordinary-load')
        (root/'bin/ordinary-load').chmod(0o755)
        console = 'exec </dev/console >/dev/console 2>&1\n' if profile != 'legacy' else ''
        (root/'init').write_text('#!/bin/busybox sh\nset -eu\n/bin/busybox mount -t proc proc /proc\n/bin/busybox mount -t sysfs sysfs /sys\n/bin/busybox mount -t devtmpfs devtmpfs /dev\n'+console+'exec /bin/ordinary-load\n')
        (root/'init').chmod(0o755)
        subprocess.run(['cargo','xtask','image','pack-initramfs',str(root),str(output/'initramfs.cpio.gz'),'--gzip'],check=True)
    shutil.copyfile(kernel, output/'linux.kernel')
    firmware = ''
    affinity = f'phys_cpu_ids = [{host_cpu}]'
    if explicit:
        subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(output/'machine.dtb'),
                        str(Path(__file__).with_name('machine-rk3588.dts' if gic_layout() == 'rk3588'
                                                    else 'machine.dts'))], check=True)
        firmware = 'dtb_path = "machine.dtb"\n'
        affinity = f'phys_cpu_ids = [0]\nphys_cpu_sets = [{1 << host_cpu}]'
    (output/'vm.toml').write_text(f'''[base]
id = 1
name = "linux-ordinary-{'memory' if memory_bytes else 'cpu'}"
guest_type = "virtualized"
cpu_num = 1
{affinity}
[kernel]
entry_point = 0x80200000
kernel_path = "linux.kernel"
kernel_load_addr = 0x80200000
dtb_load_addr = 0x80000000
{firmware}\
ramdisk_path = "initramfs.cpio.gz"
ramdisk_load_addr = 0x84000000
cmdline = "console=ttyAMA0 rdinit=/init devtmpfs.mount=1 quiet loglevel=0"
memory_regions = [[0x80000000, 0x40000000, 0x7, 0]]
[devices]
passthrough = []
disabled = []
''')
    (output/'build.json').write_text(json.dumps(dict(command=command,compiler_version=compiler_version,
        working_set_bytes=memory_bytes,memory_every_batches=memory_every,fences_enabled=fences,
        explicit_dtb=explicit,host_cpu=host_cpu,
        guest_gic_layout=gic_layout(),
        dtb_sha256=hashlib.sha256((output/'machine.dtb').read_bytes()).hexdigest() if explicit else None,
        kernel_sha256=KERNEL_SHA,base_profile=profile,base_initramfs_sha256=base_sha,
        workload_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        workload_elf_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        initramfs_sha256=hashlib.sha256((output/'initramfs.cpio.gz').read_bytes()).hexdigest()),indent=2)+'\n')


if __name__ == '__main__':
    main()
