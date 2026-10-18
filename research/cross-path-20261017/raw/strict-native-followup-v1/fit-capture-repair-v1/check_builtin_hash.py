#!/usr/bin/env python3
"""Use the real FIT reader to reject one damaged supplied hash in a minimal FIT."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
output = HERE / 'builtin-hash'
output.mkdir()
spec = importlib.util.spec_from_file_location('candidate_capture', HERE / 'repaired/capture_native.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
records = []
for damaged in (False, True):
    label = 'damaged' if damaged else 'valid'
    images = []
    for key in ('kernel', 'ramdisk', 'fdt'):
        payload = ('software-only-' + key).encode()
        value = bytearray(hashlib.sha256(payload).digest())
        if damaged and key == 'kernel':
            value[0] ^= 1
        hexbytes = lambda raw: ' '.join(f'{value:02x}' for value in raw)
        images.append(key + ' { data = [' + hexbytes(payload) + ']; hash-1 { algo = "sha256"; value = [' + hexbytes(value) + ']; }; };')
    dts = '/dts-v1/; / { images { ' + ' '.join(images) + ' }; configurations { default = "software-only"; software-only { kernel = "kernel"; ramdisk = "ramdisk"; fdt = "fdt"; }; }; };\n'
    source, fit = output / (label + '.dts'), output / (label + '.fit')
    with source.open('x') as stream:
        stream.write(dts)
    command = ['/usr/bin/dtc', '-I', 'dts', '-O', 'dtb', '-o', str(fit), str(source)]
    with (output / (label + '.dtc.stdout')).open('xb') as stdout, (output / (label + '.dtc.stderr')).open('xb') as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        actual_wait_exit = process.wait()
    assert actual_wait_exit == 0
    artifacts = output / (label + '-components')
    artifacts.mkdir()
    try:
        components = capture.fit_components(fit, artifacts)
    except ValueError as error:
        assert damaged and str(error) == 'FIT component hash differs', str(error)
        result = {'rejected': True, 'error': str(error)}
    else:
        assert not damaged, 'damaged built-in hash was accepted'
        assert all(row['integrity_hash_present'] is True and len(row['hashes']) == 1 for row in components.values())
        result = {'accepted': True, 'components': components}
    records.append({'fixture': label, 'scope': 'software-only FIT; no boot', 'dtc_argv': command,
                    'actual_dtc_Popen_wait_exit': actual_wait_exit, 'result': result})
with (output / 'result.json').open('x') as stream:
    json.dump({'passed': True, 'cases': records}, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps({'passed': True, 'valid_hashes_accepted': True, 'damaged_hash_rejected': True, 'exact_error': 'FIT component hash differs'}, sort_keys=True))
