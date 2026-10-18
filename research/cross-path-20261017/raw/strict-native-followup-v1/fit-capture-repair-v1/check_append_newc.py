#!/usr/bin/env python3
"""Check typed append-newc merging with minimal software-only archives, without booting."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tools', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir()
spec = importlib.util.spec_from_file_location('candidate_capture', args.tools / 'capture_native.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def archive(entries):
    data = bytearray()
    for name, mode, payload in [*entries, ('TRAILER!!!', 0, b'')]:
        encoded = name.encode() + b'\0'
        fields = [0, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, 0, len(payload), 0, 0, 0, 0, len(encoded), 0]
        data.extend(b'070701' + ''.join(f'{value:08x}' for value in fields).encode())
        data.extend(encoded)
        data.extend(b'\0' * (-len(data) % 4))
        data.extend(payload)
        data.extend(b'\0' * (-len(data) % 4))
    return bytes(data)


directory = ('.', stat.S_IFDIR | 0o755, b'')
first = archive([directory, ('one', stat.S_IFREG | 0o644, b'first')])
second = archive([directory, ('two', stat.S_IFREG | 0o644, b'second')])
empty_file = archive([('entry', stat.S_IFREG | 0o644, b'')])
as_directory = archive([('entry', stat.S_IFDIR | 0o755, b'')])
cases = [
    ('same_directory_gzip', first + gzip.compress(second, mtime=0), {'.': b'', 'one': b'first', 'two': b'second'}),
    ('same_directory_plain', first + second, {'.': b'', 'one': b'first', 'two': b'second'}),
    ('duplicate_empty_file_gzip', empty_file + gzip.compress(empty_file, mtime=0), None),
    ('file_directory_conflict_nested', as_directory + gzip.compress(gzip.compress(empty_file, mtime=0), mtime=0), None),
    ('directory_permission_conflict', archive([directory]) + gzip.compress(archive([('.', stat.S_IFDIR | 0o700, b'')]), mtime=0), None),
]
results = []
for name, data, expected in cases:
    with (args.out / (name + '.cpio')).open('xb') as stream:
        stream.write(data)
    try:
        actual = capture.newc_members(data)
    except ValueError as error:
        passed = expected is None and str(error) in ('duplicate appended gzip payload', 'duplicate host archive payload')
        row = {'name': name, 'passed': passed, 'rejected': True, 'error': str(error)}
    else:
        passed = expected is not None and actual == expected
        row = {'name': name, 'passed': passed, 'rejected': False, 'payloads_preserved': passed}
    results.append(row)
passed = all(row['passed'] for row in results)
with (args.out / 'result.json').open('x') as stream:
    json.dump({'scope': 'software-only append-newc contract; no boot', 'passed': passed, 'cases': results}, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps({'passed': passed, 'cases': results}, sort_keys=True), flush=True)
assert passed, 'append-newc merging contract failed'
