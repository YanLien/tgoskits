#!/usr/bin/env python3
"""Frozen native artifacts; captures are post-exit and never imply boot-before verification."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import time
import tomllib
import zlib

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
INPUTS = json.loads((HERE / "inputs.json").read_text())
DEBUG = Path(INPUTS["source"])
TARGET = Path(INPUTS["target"])
CHANGED_SOURCE = "virtualization/axvm/tests/guests/linux-load/prepare.py"
WORKER_SHA = "b9db9b8fc7925bf2c18e2d9edfbd3c0ee10a5a0f57985151e2f7b0073122ffc2"
BUSYBOX_SHA = "a93cdb45dd0b1abddf72c5c4d7c269316243e23d5479b9117c5dafc57805f96d"

def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def init_from_source(phase=True, profile="registry-v0.0.14"):
    """Evaluate only the real init expression and its local bindings, without running prepare."""
    raw = (DEBUG / CHANGED_SOURCE).read_text()
    tree = ast.parse(raw)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "write_text" and node.args
             and isinstance(node.func.value, ast.BinOp)
             and isinstance(node.func.value.left, ast.Name) and node.func.value.left.id == "root"
             and isinstance(node.func.value.right, ast.Constant) and node.func.value.right.value == "init"]
    if len(calls) != 1:
        raise RuntimeError("expected one actual root/init write_text expression")
    call = calls[0]
    bindings = {node.targets[0].id: node.value for node in ast.walk(tree)
                if isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"console", "tail"}
                and node.lineno < call.lineno}
    values = {"phase": phase, "profile": profile}

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bool)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in values:
                return values[node.id]
            if node.id in bindings:
                return evaluate(bindings[node.id])
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return evaluate(node.left) + evaluate(node.right)
        if isinstance(node, ast.IfExp):
            return evaluate(node.body if evaluate(node.test) else node.orelse)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
            if isinstance(node.ops[0], ast.Eq):
                return left == right
        raise RuntimeError("unexpected init expression: " + ast.dump(node))

    actual = evaluate(call.args[0]).encode()
    # Approved artifacts provide the oracle, so a candidate cannot redefine its own expected init.
    expected = (EVIDENCE / ("init.expected" if phase else "original-init.expected")).read_bytes()
    if profile == "legacy":
        expected = expected.replace(b"exec </dev/console >/dev/console 2>&1\n", b"")
    if actual != expected:
        raise AssertionError("init compatibility mismatch phase=" + str(phase) + " profile=" + profile
                             + " expected_bytes=" + str(len(expected)) + " actual_bytes=" + str(len(actual)))
    return actual

def parse_newc(data):
    """Reject unsafe paths, links, duplicates, truncation and nonzero trailer data."""
    offset, members, payloads = 0, {}, {}
    while offset < len(data):
        if offset + 110 > len(data) or data[offset:offset + 6] != b"070701":
            raise RuntimeError("invalid/truncated newc header")
        header = data[offset + 6:offset + 110]
        if any(c not in b"0123456789abcdefABCDEF" for c in header):
            raise RuntimeError("invalid newc hexadecimal fields")
        fields = [int(header[i:i + 8], 16) for i in range(0, 104, 8)]
        offset += 110
        mode, nlink, size, namesize = fields[1], fields[4], fields[6], fields[11]
        if namesize < 1 or offset + namesize > len(data):
            raise RuntimeError("invalid/truncated newc name")
        name_raw = data[offset:offset + namesize]
        if name_raw[-1:] != b"\0" or b"\0" in name_raw[:-1]:
            raise RuntimeError("invalid newc name terminator")
        name = name_raw[:-1].decode("utf-8", errors="strict")
        end_name = offset + namesize
        offset = (end_name + 3) & ~3
        if offset > len(data) or any(data[end_name:offset]) or offset + size > len(data):
            raise RuntimeError("invalid newc name padding/payload bounds")
        payload = data[offset:offset + size]
        end_payload = offset + size
        offset = (end_payload + 3) & ~3
        if offset > len(data) or any(data[end_payload:offset]) or fields[12] != 0:
            raise RuntimeError("invalid newc payload padding/check field")
        if name == "TRAILER!!!":
            if size or mode or any(data[offset:]):
                raise RuntimeError("invalid newc trailer or trailing data")
            return members, payloads, len(data) - offset
        relative = PurePosixPath(name)
        if not name or relative.is_absolute() or ".." in relative.parts or str(relative) != name:
            raise RuntimeError("unsafe/noncanonical newc member")
        if name in members:
            raise RuntimeError("duplicate newc member: " + name)
        kind = stat.S_IFMT(mode)
        if kind not in (stat.S_IFDIR, stat.S_IFREG) or mode & 0o7000:
            raise RuntimeError("unexpected newc member type or special permission")
        if (kind == stat.S_IFDIR and size) or (kind == stat.S_IFREG and nlink != 1):
            raise RuntimeError("directory payload or hardlinked newc file")
        members[name] = {"type": "file" if kind == stat.S_IFREG else "directory",
                         "mode": stat.S_IMODE(mode), "bytes": size,
                         "sha256": hashlib.sha256(payload).hexdigest()}
        payloads[name] = payload
    raise RuntimeError("newc archive has no trailer")

def verify_rootfs(path, report_path):
    members, payloads, trailing = parse_newc(gzip.decompress(Path(path).read_bytes()))
    original = json.loads((EVIDENCE / "original-rootfs-members.json").read_text())
    regular = {name for name, row in members.items() if row["type"] == "file"}
    if regular != {"bin/busybox", "bin/ordinary-load", "init"} or set(members) != set(original):
        raise RuntimeError("actual rootfs member set differs")
    for name in members:
        if any(members[name][key] != original[name][key] for key in ["type", "mode"]):
            raise RuntimeError("actual rootfs type/permission differs: " + name)
    for name, expected_sha in [("bin/busybox", BUSYBOX_SHA), ("bin/ordinary-load", WORKER_SHA)]:
        if members[name]["sha256"] != expected_sha or payloads[name] != (EVIDENCE / "comparison" / name).read_bytes():
            raise RuntimeError("actual rootfs original binary differs: " + name)
    if payloads["init"] != init_from_source():
        raise RuntimeError("actual rootfs init differs from actual reviewed init")
    changed = sorted(name for name in members if members[name]["sha256"] != original[name]["sha256"])
    if changed != ["init"]:
        raise RuntimeError("actual rootfs must change only init content")
    report = {"archive_sha256": digest(path), "archive_bytes": Path(path).stat().st_size,
              "members": members, "changed_content": changed, "trailing_zero_bytes": trailing,
              "binary_bytes_equal_original": True, "init_equals_actual_source_expression": True,
              "runtime_PID1_or_drain_proven": False}
    save_json(report_path, report)
    return report


def safe_file(root, relative):
    rel = PurePosixPath(relative)
    if rel.is_absolute() or '..' in rel.parts or str(rel) != relative:
        raise ValueError('unsafe relative path: '+relative)
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('path escapes its root')
    for item in (path, *path.parents):
        if item == root.parent:
            break
        if item.is_symlink():
            raise ValueError('symlink in controlled file path')
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('controlled input is not a regular file')
    return path


def identity(path):
    path = Path(path)
    before = path.stat()
    result = {'sha256': digest(path), 'bytes': before.st_size, 'mode': stat.S_IMODE(before.st_mode)}
    after = path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns) != (after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('file changed while hashing: '+str(path))
    return result


def verify_static():
    expected = json.loads((EVIDENCE/'ordinary-identities.json').read_text())
    actual = {str(p.relative_to(DEBUG)) for p in DEBUG.rglob('*') if p.is_file()}
    if actual != set(expected) or any(p.is_symlink() for p in DEBUG.rglob('*')):
        raise ValueError('ordinary source member set or type differs')
    for relative, row in expected.items():
        if identity(safe_file(DEBUG,relative)) != row:
            raise ValueError('ordinary source identity differs: '+relative)
    normal = json.loads((EVIDENCE/'sources-702.json').read_text())
    if len(normal) != 702 or digest(EVIDENCE/'sources-702.json') != INPUTS['normal702_sha256']:
        raise ValueError('normal702 approved source SHA differs')
    if any(expected[name]['sha256'] != value for name,value in normal.items()):
        raise ValueError('normal702 differs from full ordinary source tree')
    for relative,row in json.loads((EVIDENCE/'control-identities.json').read_text()).items():
        if expected[relative] != row:
            raise ValueError('in-workspace native control identity differs')
    for path,row in INPUTS['external_inputs'].items():
        if identity(Path(path)) != row:
            raise ValueError('fixed external identity differs: '+path)
    for path,row in json.loads((EVIDENCE/'reviewed-identities.json').read_text()).items():
        if identity(Path(path)) != row:
            raise ValueError('reviewed authority or input identity differs: '+path)
    cache_runtime_state = {'cargo':{}}
    for manifest_name,cache_root in [('cache-identities.json',Path(INPUTS['environment']['VIRQ_CACHE_DIR'])),
                                     ('cargo-cache-identities.json',Path(INPUTS['environment']['CARGO_HOME']))]:
        cache = json.loads((EVIDENCE/manifest_name).read_text())
        if cache_root.is_symlink():
            raise ValueError('private cache root became a symlink')
        cargo_cache = manifest_name=='cargo-cache-identities.json'
        runtime_allowed = INPUTS['cache_policy']['cargo_runtime_files'] if cargo_cache else {}
        if cargo_cache:
            for name in INPUTS['cache_policy']['cargo_forbidden_roots']:
                if os.path.lexists(cache_root/name):
                    raise ValueError('forbidden CARGO_HOME input: '+name)
        # Inventory every file and symlink; optional bookkeeping is never an immutable build input.
        actual = set()
        for directory,children,files in os.walk(cache_root,followlinks=False):
            actual.update(str((Path(directory)/name).relative_to(cache_root)) for name in files)
            for child in children:
                path = Path(directory)/child
                if path.is_symlink():
                    relative = str(path.relative_to(cache_root))
                    actual.add(relative)
                    expected_link = cache.get(relative,{})
                    if (expected_link.get('type')!='symlink' or os.readlink(path)!=expected_link.get('target')
                            or not path.resolve().is_relative_to(cache_root)):
                        raise ValueError('private cache contains an unapproved symlink directory')
        missing = set(cache)-actual
        extra = actual-set(cache)
        if missing or extra-set(runtime_allowed):
            raise ValueError('private cache member set differs: missing='+repr(sorted(missing))+' extra='+repr(sorted(extra-set(runtime_allowed))))
        for relative in sorted(extra):
            path = cache_root/relative
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o7000 or path.stat().st_size>runtime_allowed[relative]:
                raise ValueError('invalid bounded Cargo bookkeeping file: '+relative)
            row = identity(path)
            if relative=='.global-cache' and row['bytes']:
                with path.open('rb') as stream:
                    if stream.read(16)!=b'SQLite format 3\0':
                        raise ValueError('Cargo bookkeeping database has no SQLite header')
            cache_runtime_state['cargo'][relative] = row
        for relative,row in cache.items():
            rel = PurePosixPath(relative)
            if rel.is_absolute() or '..' in rel.parts or str(rel)!=relative:
                raise ValueError('unsafe private cache identity path')
            path = cache_root/relative
            if row.get('type') == 'symlink':
                if not path.is_symlink() or os.readlink(path) != row['target']:
                    raise ValueError('private cache symlink differs')
            elif not stat.S_ISREG(path.lstat().st_mode) or identity(path) != row:
                raise ValueError('private build cache input differs: '+relative)
    frozen = json.loads((HERE/'freeze-manifest.json').read_text())
    for relative,row in frozen.items():
        if identity(safe_file(HERE,relative)) != row:
            raise ValueError('frozen tool/input identity differs: '+relative)
    return {'ordinary_count':len(expected),'normal702_count':len(normal),'all_match':True,'cache_runtime_state':cache_runtime_state}


def _newc_entries(data):
    """Retain checked metadata through recursive Host append-newc archives."""
    members, merged = {}, {}

    def merge(child_members, payloads, error):
        for name in set(members)&set(child_members):
            before, after = members[name], child_members[name]
            # Empty files are payloads too; only matching empty directories may repeat.
            if (before['type'] != 'directory' or after['type'] != 'directory'
                    or before['bytes'] or after['bytes'] or before['mode'] != after['mode']):
                raise ValueError(error)
        members.update(child_members)
        merged.update(payloads)

    offset = 0
    while offset < len(data):
        while offset < len(data) and data[offset] == 0:
            offset += 1
        if offset == len(data):
            break
        if data[offset:offset+2] == b'\x1f\x8b':
            inflater = zlib.decompressobj(31)
            raw = inflater.decompress(data[offset:])
            if not inflater.eof:
                raise ValueError('truncated appended gzip member')
            child_members, payloads = _newc_entries(raw)
            merge(child_members,payloads,'duplicate appended gzip payload')
            offset = len(data)-len(inflater.unused_data)
            continue
        start = offset
        while True:
            if data[offset:offset+6] != b'070701' or offset+110 > len(data):
                raise ValueError('invalid host newc member boundary')
            fields = [int(data[offset+6+i:offset+14+i],16) for i in range(0,104,8)]
            size,namesize = fields[6],fields[11]
            name = data[offset+110:offset+110+namesize]
            offset = ((offset+110+namesize+3)&~3)+size
            offset = (offset+3)&~3
            if offset > len(data):
                raise ValueError('truncated host newc')
            if name == b'TRAILER!!!\0':
                break
        child_members,payloads,_ = parse_newc(data[start:offset])
        merge(child_members,payloads,'duplicate host archive payload')
    return members,merged


def newc_members(data):
    """Read Host payloads, preserving symbol sidecars and checked directory reuse."""
    return _newc_entries(data)[1]


def fdt_property(path,node,prop,kind='s'):
    result = subprocess.run(['/usr/bin/fdtget','-t',kind,str(path),node,prop],
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    if result.returncode:
        raise ValueError('FIT/FDT property unavailable: '+node+'/'+prop)
    if kind == 'bx':
        return bytes(int(x,16) for x in result.stdout.split())
    return result.stdout.decode().strip()


def fit_components(path,output):
    """Resolve the actual FIT default and verify every supplied integrity hash."""
    config = '/configurations/'+fdt_property(path,'/configurations','default')
    result = {}
    for key in ('kernel','ramdisk','fdt'):
        name = fdt_property(path,config,key)
        node = '/images/'+name
        payload = fdt_property(path,node,'data','bx')
        children = subprocess.run(['/usr/bin/fdtget','-l',str(path),node],check=True,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5).stdout.decode().split()
        checks = []
        for child in children:
            if child.startswith('hash'):
                algorithm = fdt_property(path,node+'/'+child,'algo')
                expected = fdt_property(path,node+'/'+child,'value','bx')
                if algorithm not in ('sha256','sha1','crc32'):
                    raise ValueError('unrecognized FIT hash algorithm')
                if algorithm == 'crc32':
                    import zlib
                    observed = (zlib.crc32(payload)&0xffffffff).to_bytes(4,'big')
                else:
                    observed = hashlib.new(algorithm,payload).digest()
                if observed != expected:
                    raise ValueError('FIT component hash differs')
                checks.append({'algorithm':algorithm,'value':expected.hex()})
        # An absent built-in hash is not a verified hash. Complete external kernel/
        # initramfs binding and the exact FDT transform remain mandatory in capture_native.
        saved = output/('fit-'+key)
        saved.write_bytes(payload)
        result[key] = {'node':node,'sha256':digest(saved),'bytes':len(payload),'saved':str(saved),
                       'hashes':checks,'integrity_hash_present':bool(checks)}
    return result



def verify_fdt_transform(preset, embedded, output):
    """Compare dtc canonical trees after the exact fixed ostool stale-initrd removal."""
    values = {}
    for prop in ('linux,initrd-start','linux,initrd-end'):
        result = subprocess.run(['/usr/bin/fdtget','-t','bx',str(preset),'/chosen',prop],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        if result.returncode:
            if b'FDT_ERR_NOTFOUND' not in result.stderr:
                raise ValueError('cannot inspect original preset initrd property')
            values[prop] = None
        else:
            values[prop] = bytes(int(x,16) for x in result.stdout.split())
    texts = []
    for label,path in [('preset',preset),('embedded',embedded)]:
        raw = subprocess.run(['/usr/bin/dtc','-I','dtb','-O','dts','-s',str(path)],
                             check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5).stdout
        (output/(label+'-canonical.dts')).write_bytes(raw)
        texts.append(raw.decode())
    original,actual = texts
    original = re.sub(r'^\s*linux,initrd-(?:start|end) = [^;]*;\n','',original,flags=re.M)
    start,end = values['linux,initrd-start'],values['linux,initrd-end']
    if start is not None and end is not None and len(start) in (4,8) and len(end) in (4,8):
        start,end = int.from_bytes(start,'big'),int.from_bytes(end,'big')
        if end >= start:
            def reservation(match):
                address,size = int(match.group(1),16),int(match.group(2),16)
                return '' if (address,size)==(start,end-start) else match.group(0)
            original = re.sub(r'^/memreserve/\s+0x([0-9a-f]+)\s+0x([0-9a-f]+);\n',reservation,original,flags=re.M)
    if original != actual:
        raise ValueError('FIT FDT differs beyond exact stale-initrd properties/reservation removal')
    return {'canonical_tree_matches_fixed_ostool_transform':True,'preset_sha256':digest(preset),
            'embedded_sha256':digest(embedded),'scope':'post-exit saved bytes; distinct original/FIT identities retained'}


def capture_native(output, raw_log, case):
    """Capture the real ktest route; missing use-chain evidence remains incomplete."""
    output = Path(output)
    artifacts = output/'artifacts'
    artifacts.mkdir()
    log = Path(raw_log).read_bytes().decode(errors='replace')
    evidence = {'capture_phase':'post-exit','boot_before_identity_verified':False,'capture_time_ns':time.time_ns(),
                'artifacts':{},'errors':[],'artifact_chain_complete':False,'host_function_passed':False}
    root = TARGET/'axbuild/axvm/vcpu-runtime'
    def one(pattern,label):
        values = list(dict.fromkeys(re.findall(pattern,log,re.M)))
        if len(values) != 1:
            raise ValueError('expected one actual '+label+' path in log')
        path = Path(values[0])
        if not path.is_absolute() or not path.resolve().is_relative_to(TARGET):
            raise ValueError('actual '+label+' is outside independent target')
        return path
    try:
        kernel = one(r'kernel from: (\S+)','kernel')
        fit = one(r'FIT image ok: (\S+)','FIT')
        dtb = one(r'Using DTB from: (\S+)','Host DTB')
        if fit != kernel.parent/'image.fit':
            raise ValueError('FIT not at the actual kernel parent')
        elf = one(r'cargo build elf=(\S+)','Host ELF')
        packaged = list(dict.fromkeys(re.findall(r'^Axvisor host initramfs (\S+) sha256=([0-9a-f]{64})\r?$',log,re.M)))
        if len(packaged)!=1:
            raise ValueError('expected one actual final Axvisor host initramfs path/SHA in log')
        host_initramfs = Path(packaged[0][0])
        if host_initramfs != TARGET/'axbuild/axvisor/host-initramfs/aarch64.cpio':
            raise ValueError('actual final Host initramfs path differs from the ktest bundle output')
        evidence['host_initramfs_boot_input'] = {'path':str(host_initramfs),'logged_sha256':packaged[0][1],
            'producer':'axvisor::bundle::attach_with_external_assets final output; boot.initramfs is assigned this path',
            'scope':'post-exit source/log/FIT binding; not a pre-boot observation'}
        paths = {'host_elf':elf,'host_bin':kernel,'host_fit':fit,'host_preset_dtb':dtb,'host_initramfs':host_initramfs,
                 'rt_elf':root/'guest/zephyr/zephyr.elf','rt_bin':root/'guest/zephyr/zephyr.bin',
                 'rt_dtb':root/'guest/zephyr/zephyr.dtb','guest_dtb':root/'linux/machine.dtb',
                 'linux_kernel':root/'linux/linux.kernel','worker':root/'linux/ordinary-load','guest_rootfs':root/'linux/initramfs.cpio.gz',
                 'linux_build_json':root/'linux/build.json','resources':root/'resources/tests/vcpu-runtime.toml',
                 'linux_vm_config':root/'linux/vm.toml','rt_vm_config':root/'vm.toml','zephyr_config':root/'guest/zephyr/.config'}
        budget = 0
        for label,path in paths.items():
            path = safe_file(TARGET,str(path.relative_to(TARGET)))
            row = identity(path)
            budget += row['bytes']
            if budget > INPUTS['limits']['max_capture_bytes']:
                raise ValueError('artifact capture exceeds fixed byte budget')
            saved = artifacts/row['sha256']
            shutil.copy2(path,saved)
            if identity(path) != row or identity(saved) != row:
                raise ValueError('artifact changed during capture')
            evidence['artifacts'][label] = {'path':str(path),'saved':str(saved),**row}
        if evidence['artifacts']['host_initramfs']['sha256'] != packaged[0][1]:
            raise ValueError('saved final Host initramfs differs from its actual packaging log SHA')
        components = fit_components(artifacts/evidence['artifacts']['host_fit']['sha256'],artifacts)
        evidence['fit_components'] = components
        if components['kernel']['sha256'] != evidence['artifacts']['host_bin']['sha256'] or components['ramdisk']['sha256'] != evidence['artifacts']['host_initramfs']['sha256']:
            raise ValueError('FIT bytes differ from actual kernel/initramfs')
        # ostool drops stale /chosen initrd properties; the preset DTB is saved separately.
        evidence['preset_vs_fit_fdt'] = verify_fdt_transform(artifacts/evidence['artifacts']['host_preset_dtb']['sha256'],Path(components['fdt']['saved']),artifacts)
        host = newc_members(Path(evidence['artifacts']['host_initramfs']['saved']).read_bytes())
        bundled = {}
        for vm_id in (1,2):
            names = [name for name in host if name.endswith('/configs/vm-'+str(vm_id)+'.toml')]
            if len(names) != 1:
                raise ValueError('Host bundled VM configuration missing')
            document = tomllib.loads(host[names[0]].decode())
            if document['base']['id'] != vm_id:
                raise ValueError('Host bundled VM identity differs')
            bundled[vm_id] = document
        for label,vm_id,field in [('rt_bin',2,'kernel_path'),('rt_dtb',2,'dtb_path'),
                                  ('guest_dtb',1,'dtb_path'),('guest_rootfs',1,'ramdisk_path'),('linux_kernel',1,'kernel_path')]:
            member = bundled[vm_id]['kernel'][field].lstrip('/')
            if member not in host or hashlib.sha256(host[member]).hexdigest() != evidence['artifacts'][label]['sha256']:
                raise ValueError('Host initramfs embedded payload differs: '+label)
        resource_names = [name for name in host if name == 'tests/vcpu-runtime.toml']
        if len(resource_names) != 1 or hashlib.sha256(host[resource_names[0]]).hexdigest() != evidence['artifacts']['resources']['sha256']:
            raise ValueError('Host initramfs measurement resource differs')
        if evidence['artifacts']['linux_kernel']['sha256'] != INPUTS['external_inputs'][INPUTS['environment']['VIRQ_LINUX_KERNEL']]['sha256']:
            raise ValueError('native bundled Linux kernel bytes differ')
        verify_rootfs(artifacts/evidence['artifacts']['guest_rootfs']['sha256'],output/'rootfs.json')
        resources = tomllib.loads(Path(evidence['artifacts']['resources']['saved']).read_text())
        case_env = next(row['environment'] for row in INPUTS['cases'] if row['id']==case)
        resource_fixed = {'samples':32,'recording':'on','task_enabled':True,'task_wait':'blocked','task_deadline_ns':10000000,
                          'task_rounds':4096,'period_us':20000,'scenario':'linux_memory','source':'physical_timer_ppi',
                          'linux_memory_bytes':16777216,'linux_memory_every':1,'linux_fences_enabled':True,'linux_phase_enabled':True,
                          'linux_phase_offset':int(case_env['VIRQ_LINUX_PHASE_OFFSET']),'linux_phase_b_enabled':case_env['VIRQ_LINUX_PHASE_B']=='1',
                          'linux_host_cpu':3,'explicit_dtb_enabled':True,'guest_gic_layout':'rk3588','service_placement':'cpu0',
                          'irq_context':'current_el','irq_service':'off','irq_pressure':case_env['VIRQ_IRQ_PRESSURE'],
                          'irq_pressure_period_us':2000,'irq_pressure_burst':2}
        if any(type(resources.get(k)) is not type(v) or resources[k]!=v for k,v in resource_fixed.items()):
            raise ValueError('actual native resources differ from exact approved case')
        build = json.loads(Path(evidence['artifacts']['linux_build_json']['saved']).read_text())
        approved = json.loads((EVIDENCE/'approved-worker-build.json').read_text())
        fixed = ['compiler_version','compiler_path','compiler_sha256','working_set_bytes','memory_every_batches','fences_enabled',
                 'phase_enabled','phase_test_clock','source_sha256','explicit_dtb','host_cpu','base_profile','kernel_sha256',
                 'base_initramfs_sha256','workload_source_sha256','workload_elf_sha256']
        if any(build[k] != approved[k] for k in fixed) or build['guest_gic_layout'] != 'rk3588':
            raise ValueError('native worker approved source/compiler/build identities differ')
        guest = DEBUG/'virtualization/axvm/tests/guests/linux-load'
        expected_command = [INPUTS['environment']['VIRQ_LINUX_CC'],'-O2','-static','-std=c11','-Wall','-Wextra','-Werror',
                            str(guest/'workload.c'),str(guest/'phase.c'),'-o',str(root/'linux/ordinary-load'),
                            '-DLINUX_MEMORY_BYTES=16777216ULL','-DLINUX_MEMORY_EVERY=1','-DLINUX_FENCES=1',
                            '-DLINUX_PHASE=1','-DLINUX_PHASE_TEST_CLOCK=0']
        if (build['command'] != expected_command or build['compiler_sha256'] != digest(build['compiler_path'])
                or build['dtb_sha256'] != evidence['artifacts']['guest_dtb']['sha256']
                or build['initramfs_sha256'] != evidence['artifacts']['guest_rootfs']['sha256']):
            raise ValueError('actual native compile flags/DTB/rootfs identities differ')
        if evidence['artifacts']['worker']['sha256'] != WORKER_SHA:
            raise ValueError('native normal worker bytes differ')
        evidence['artifact_chain_complete'] = True
    except (OSError,ValueError,RuntimeError,KeyError,subprocess.SubprocessError) as error:
        evidence['errors'].append(str(error))
    # The frozen Host owns full DATA/ACCEPT semantics; this capture retains the bytes for independent audit.
    evidence['host_markers'] = [line for line in log.splitlines() if any(x in line for x in ('LINUX_PHASE_DATA','LINUX_PHASE_ACCEPT','VIRQ_LINUX_PHASE_ACCEPT','VIRQ_TRACE_FROZEN','AXTEST_SUITE_'))]
    evidence['normal_function_audit_required'] = True
    evidence['normal_function_audit_scope'] = 'two policies/32 tasks/32 slots/2 snapshots, raw DATA/R/ACCEPT, known answer/counter generation, strict timing, retirement, pressure off-or-cover/skip0, B zero accesses when off, global zero drops and complete suite; no offset/overlap/IAB analysis'
    save_json(output/'capture.json',evidence)
    return evidence
