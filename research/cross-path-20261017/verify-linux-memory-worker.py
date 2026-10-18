#!/usr/bin/env python3
"""Exercise the actual Linux C worker; native evidence only, not VM evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import tempfile
import time

MASK = (1 << 64) - 1
READY = 'LINUX_LOAD_READY version=1 guest_cpu=0 batch_iterations=8192 report_batches=256'
PROGRESS = re.compile(r'LINUX_LOAD_PROGRESS batches=(\d+) checksum=(\d+) guest_cpu=0(?: memory_batches=(\d+) logical_bytes=(\d+) memory_checksum=(\d+))?')


def lcg(steps):
    value, multiplier, increment = 1, 6364136223846793005, 1
    while steps:
        if steps & 1:
            value = (value * multiplier + increment) & MASK
        increment = (increment * (multiplier + 1)) & MASK
        multiplier = multiplier * multiplier & MASK
        steps >>= 1
    return value


def observe(binary, destination, size, every, fault=False):
    process = subprocess.Popen([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output, pending = bytearray(), bytearray()
    count, previous = 0, 0
    ready, memory_ready = False, False
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            events = selector.select(max(0, deadline - time.monotonic()))
            if not events:
                raise AssertionError('worker did not reach required reports within 30 seconds')
            data = os.read(process.stdout.fileno(), 65536)
            if not data:
                break
            output.extend(data)
            pending.extend(data)
            while b'\n' in pending:
                raw, _, rest = pending.partition(b'\n')
                pending = bytearray(rest)
                line = raw.decode()
                if fault:
                    continue
                if line == READY:
                    assert not ready and count == 0 and not memory_ready
                    ready = True
                    continue
                if line.startswith('LINUX_MEMORY_READY '):
                    assert ready and size and not memory_ready
                    assert line == f'LINUX_MEMORY_READY version=1 working_set_bytes={size} every_batches={every} chunk_words=8192'
                    memory_ready = True
                    continue
                match = PROGRESS.fullmatch(line)
                assert ready and match, line
                batches, checksum = map(int, match.groups()[:2])
                assert batches == previous + 256 and checksum == lcg(batches * 8192)
                previous = batches
                if size:
                    assert memory_ready and match[3] is not None
                    memory_batches, logical_bytes, actual = map(int, match.groups()[2:])
                    expected_batches = (batches + every - 1) // every
                    accesses, words = expected_batches * 8192, size // 8
                    # Independent closed-form sum of sequentially written words.
                    full, partial = divmod(accesses, words)
                    expected = (full * words * (words + full) // 2
                                + partial * (partial + 1) // 2 + partial * full) & MASK
                    assert memory_batches == expected_batches
                    assert logical_bytes == accesses * 16 and actual == expected
                else:
                    assert match[3] is None
                count += 1
            if not fault and count >= 3:
                break
        if fault:
            code = process.wait(timeout=5)
            assert code == 1 and b'LINUX_LOAD_FAILED operation=memory_verify index=0\n' in output
            assert b'LINUX_LOAD_PROGRESS' not in output
        else:
            assert count >= 3
            assert process.poll() is None
            process.terminate()
            process.wait(timeout=5)
            if size:
                accesses = ((previous + every - 1) // every) * 8192
                assert accesses > size // 8
                if size % 65536:
                    assert accesses % (size // 8) != 0
        return dict(reports=count, final_batches=previous, working_set_bytes=size,
                    every_batches=every, fault_rejected=fault)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        selector.close()
        process.stdout.close()
        destination.write_bytes(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='memory-worker-') as temporary:
        root = Path(temporary)
        for name, size, every, fault in [('cpu', 0, 1, False),
                                         ('partial-duty', 1056768, 3, False),
                                         ('default', 16777216, 1, False),
                                         ('corrupted', 1056768, 3, True)]:
            source = args.source
            if fault:
                source = root / 'corrupted.c'
                original = args.source.read_text()
                assert original.count('    size_t cursor = 0;') == 1
                source.write_text(original.replace('    size_t cursor = 0;',
                                                    '    memory[0] = 9999;\n    size_t cursor = 0;'))
            binary = root / name
            command = ['cc', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror',
                       f'-DLINUX_MEMORY_BYTES={size}ULL', f'-DLINUX_MEMORY_EVERY={every}',
                       str(source), '-o', str(binary)]
            subprocess.run(command, check=True)
            result = observe(binary, args.output / (name + '.log'), size, every, fault)
            result.update(name=name, command=command, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
            results.append(result)
    metadata = dict(scope='native Linux user-process correctness; no VM or DRAM conclusions',
                    source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                    compiler=subprocess.run(['cc', '--version'], check=True, capture_output=True, text=True).stdout.splitlines()[0],
                    results=results)
    (args.output / 'verification.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
