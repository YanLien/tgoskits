#!/usr/bin/env python3
"""Read-only investigation of saved bytes; never runs the normal audit."""
import ast
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zlib

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bound(ref, retain=False):
    path = Path(ref['path'])
    assert path.resolve() == path and path.is_file() and not path.is_symlink()
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1048576),b''):
            digest.update(block)
    after = path.stat()
    assert (before.st_ino,before.st_mtime_ns,before.st_size) == (after.st_ino,after.st_mtime_ns,after.st_size)
    assert after.st_size == ref['bytes'] and digest.hexdigest() == ref['sha256']
    if retain:
        data = path.read_bytes()
        assert len(data) == ref['bytes'] and sha(data) == ref['sha256']
        return data
    return dict(ref,verified=True)


def extract(path, expected, names):
    raw = path.read_bytes()
    assert sha(raw) == expected
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes} == names
    namespace = dict(Path=Path,PurePosixPath=PurePosixPath,stat=stat,
                     hashlib=hashlib,gzip=gzip,zlib=zlib,struct=struct,re=re)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    return namespace,dict(path=str(path),bytes=len(raw),sha256=expected,
        selected={n.name:dict(line=n.lineno,end_line=n.end_lineno) for n in nodes})


def invoke(function,data):
    try:
        result = function(data)
        if isinstance(result,tuple):
            first = result[0]
            return dict(accepted=True,members=len(first),member_names=sorted(first),
                        regular=sorted(result[1]) if isinstance(result[1],set) else None)
        return dict(accepted=True,members=len(result),member_names=sorted(result))
    except (ValueError,RuntimeError,AssertionError) as error:
        return dict(accepted=False,error=type(error).__name__+': '+str(error))


def decompose(data, domain, audit, capture):
    """Locate container boundaries for diagnostics, without accepting new inputs."""
    result, offset = [], 0
    while offset < len(data):
        padding_start = offset
        while offset < len(data) and data[offset] == 0:
            offset += 1
        if offset == len(data):
            result.append(dict(kind='zero-padding',domain=domain,offset=padding_start,bytes=offset-padding_start))
            break
        if data[offset:offset+2] == b'\x1f\x8b':
            inflater = zlib.decompressobj(31)
            raw = inflater.decompress(data[offset:])
            assert inflater.eof
            end = len(data)-len(inflater.unused_data)
            result.append(dict(kind='gzip-member',domain=domain,offset=offset,bytes=end-offset,
                first_bytes_hex=data[offset:offset+32].hex(),sha256=sha(data[offset:end]),
                inflated_bytes=len(raw),inflated_sha256=sha(raw),
                children=decompose(raw,'inflated gzip at '+domain+':'+str(offset),audit,capture)))
            offset = end
            continue
        start = offset
        members = []
        while True:
            header = data[offset:offset+110]
            assert len(header) == 110 and header[:6] == b'070701'
            values = [int(header[6+i:14+i],16) for i in range(0,104,8)]
            size,namesize = values[6],values[11]
            name_raw = data[offset+110:offset+110+namesize]
            assert name_raw.endswith(b'\0')
            payload_start = (offset+110+namesize+3)&~3
            end = (payload_start+size+3)&~3
            name = name_raw[:-1].decode()
            member = dict(name=name,header_offset=offset,mode=values[1],bytes=size,
                          payload_offset=payload_start,end_offset=end)
            members.append(member)
            offset = end
            if name == 'TRAILER!!!':
                break
        chunk = data[start:offset]
        first_nonzero = next((i for i in range(offset,len(data)) if data[i]),None)
        result.append(dict(kind='newc-archive',domain=domain,offset=start,bytes=len(chunk),
            sha256=sha(chunk),members=members,trailer=member,
            trailer_header_ascii=header.decode(),trailer_name_hex=name_raw.hex(),
            bytes_after_archive=len(data)-offset,first_nonzero_after=first_nonzero,
            boundary_hex=data[max(0,offset-32):min(len(data),offset+64)].hex(),
            sealed_auditor_single_archive=invoke(audit['newc'],chunk),
            approved_capture_single_archive=invoke(capture['parse_newc'],chunk)))
    return result


def main():
    handoff_path = R/'raw/strict-native-phase-v3/AB1-root-final-handoff-v1.json'
    handoff_raw = handoff_path.read_bytes()
    assert sha(handoff_raw) == 'cf25d62d4ff106f0e6d3315ce4e0b58ce5f4d78ac2e90b7b79fe814116e9b72f'
    handoff = json.loads(handoff_raw)
    capture = json.loads(bound(handoff['files']['capture'],True))
    artifacts = {name:dict(path=row['saved'],bytes=row['bytes'],sha256=row['sha256'])
                 for name,row in capture['artifacts'].items()}
    verified = {name:bound(ref) for name,ref in artifacts.items()}
    assert len(verified) == 17
    audit, audit_source = extract(R/'raw/strict-native-phase-v3/function-audit-v1/audit.py',
        '6fa57d1bb99a9fbdb49613ffc90cb4b648aa9511465957aec25b9e58e34e76aa',
        {'AuditError','need','newc','fdt'})
    parser, parser_source = extract(Path('/tmp/crosspath-native-cache-v3-tools-jrhcn15t/capture_native.py'),
        '61717a37b528e2e93d8cbcae1c1dafbc6249ac3417fbf0b8011b984a03a4c683',
        {'parse_newc','_newc_entries','newc_members'})
    host = bound(artifacts['host_initramfs'],True)
    fit = bound(artifacts['host_fit'],True)
    props,_,_ = audit['fdt'](fit)
    default = '/configurations/'+props[('/configurations','default')].rstrip(b'\0').decode()
    node = '/images/'+props[(default,'ramdisk')].rstrip(b'\0').decode()
    embedded = props[(node,'data')]
    assert embedded == host
    rootfs = gzip.decompress(bound(artifacts['guest_rootfs'],True))
    analysis = dict(scope='pure format diagnosis only; not a normal audit or target success',
        handoff=dict(path=str(handoff_path),sha256=sha(handoff_raw)),
        sources=dict(sealed_auditor=audit_source,approved_capture=parser_source),
        saved_artifacts=verified,fit_default=default,fit_ramdisk_node=node,
        fit_ramdisk_bytes_equal_saved_host_initramfs=True,
        host=dict(reference=artifacts['host_initramfs'],
            sealed_auditor_whole=invoke(audit['newc'],host),
            approved_capture_whole=invoke(parser['newc_members'],host),
            container_segments=decompose(host,'saved Host initramfs raw bytes',audit,parser)),
        guest_rootfs=dict(reference=artifacts['guest_rootfs'],inflated_bytes=len(rootfs),
            inflated_sha256=sha(rootfs),sealed_auditor=invoke(audit['newc'],rootfs),
            approved_capture=invoke(parser['parse_newc'],rootfs),
            container_segments=decompose(rootfs,'inflated Guest rootfs',audit,parser)),
        normal_end_to_end_GREEN=False,full_function_passed=False)
    (HERE/'format-diagnosis.json').write_text(json.dumps(analysis,indent=2)+'\n')
    print(json.dumps(analysis,indent=2))


if __name__ == '__main__':
    main()
