#!/usr/bin/env python3
"""Exercise the actual C worker with Linux PTY/SIGIO, not a model of the UART."""

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import tempfile
import time


def checksum(iterations):
    mask = (1 << 64) - 1
    a, b, value = 6364136223846793005, 1, 1
    while iterations:
        if iterations & 1:
            value = (a * value + b) & mask
        a, b = a * a & mask, (a * b + b) & mask
        iterations >>= 1
    return value


def verify_work(line, size, every):
    fields = dict(token.split('=', 1) for token in line.split()[1:])
    count = int(fields['batches'])
    assert int(fields['checksum']) == checksum(count * 8192), line
    assert fields['guest_cpu'] == '0', line
    if size:
        batches = (count + every - 1) // every
        accesses = batches * 8192
        words = size // 8
        q, r = divmod(accesses, words)
        total = q * words * (words + 1) // 2 + words * q * (q - 1) // 2 + r * (r + 1) // 2 + r * q
        assert int(fields['memory_batches']) == batches, line
        assert int(fields['logical_bytes']) == accesses * 16, line
        assert int(fields['memory_checksum']) == total % (1 << 64), line
    else:
        assert 'memory_batches' not in fields, line
    return count, fields


def exercise(binary, output, name, size, every, enabled, commands):
    master, slave = pty.openpty()
    process = subprocess.Popen([str(binary)], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    transcript, pending, records = [], b'', []
    begin, last = None, 0
    deadline = time.monotonic() + 15
    try:
        with (output / (name + '.log')).open('w') as log:
            def until(predicate):
                nonlocal pending, last
                while True:
                    if b'\n' not in pending:
                        remaining = deadline - time.monotonic()
                        assert remaining > 0 and select.select([master], [], [], remaining)[0], 'PTY timeout'
                        try:
                            data = os.read(master, 65536)
                        except OSError as error:
                            if error.errno == errno.EIO:
                                data = b''
                            else:
                                raise
                        assert data, f'worker exited unexpectedly: {process.poll()}'
                        pending += data
                        continue
                    raw, pending = pending.split(b'\n', 1)
                    line = raw.decode().rstrip('\r')
                    transcript.append(line)
                    log.write(line + '\n')
                    log.flush()
                    if line.startswith(('LINUX_LOAD_PROGRESS', 'LINUX_FENCE_REPLY')):
                        count, _ = verify_work(line, size, every)
                        if line.startswith('LINUX_LOAD_PROGRESS'):
                            assert count == last + 256, line
                            last = count
                    if predicate(line):
                        return line
                    assert 'LINUX_LOAD_FAILED' not in line, line

            ready = until(lambda line: line.startswith('LINUX_LOAD_READY'))
            assert f'version={2 if enabled else 1} ' in ready
            if enabled:
                line = until(lambda line: line.startswith('LINUX_FENCE_READY'))
                assert 'clock=monotonic_raw' in line and re.search(r'resolution_ns=[1-9][0-9]* ', line), line
            until(lambda line: line.startswith('LINUX_LOAD_PROGRESS'))
            if not enabled:
                until(lambda line: line.startswith('LINUX_LOAD_PROGRESS'))
                assert not any('LINUX_FENCE_' in line for line in transcript)
            for index, command in enumerate(commands):
                before = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
                assert os.write(master, command.encode()) == 1
                invalid = command != ('B' if index == 0 else 'E') or index >= 2
                if invalid:
                    line = until(lambda line: 'LINUX_LOAD_FAILED' in line)
                    assert line == 'LINUX_LOAD_FAILED operation=fence_phase', line
                    assert process.wait(timeout=3) == 1
                    records.append(dict(command=command, rejected=True))
                    break
                line = until(lambda line: line.startswith('LINUX_FENCE_REPLY'))
                after = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
                count, fields = verify_work(line, size, every)
                stamp = int(fields['time_ns'])
                assert before <= stamp <= after, (before, stamp, after)
                assert fields['phase'] == ('begin' if index == 0 else 'end'), line
                if begin is not None:
                    assert count > begin[0] and stamp > begin[1]
                else:
                    begin = count, stamp
                records.append(dict(command=command, batches=count, time_ns=stamp,
                                    request_before_ns=before, reply_observed_ns=after))
                if index == 0:
                    until(lambda line: line.startswith('LINUX_LOAD_PROGRESS') and last >= count + 256)
            assert process.poll() is None or any(r.get('rejected') for r in records)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
        os.close(master)
    return dict(name=name, working_set_bytes=size, every_batches=every, fences=enabled,
                records=records, binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    assert 0 in os.sched_getaffinity(0), 'CPU0 required by the unchanged worker affinity contract'
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name('workload.c').resolve()
    cases = []
    with tempfile.TemporaryDirectory(prefix='linux-fences-') as directory:
        for size, every, name in ((0, 1, 'cpu'), (1056768, 3, 'memory')):
            for enabled in (False, True):
                binary = Path(directory) / f'{name}-{int(enabled)}'
                command = ['gcc', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source),
                           '-o', str(binary), f'-DLINUX_MEMORY_BYTES={size}ULL',
                           f'-DLINUX_MEMORY_EVERY={every}', f'-DLINUX_FENCES={int(enabled)}']
                subprocess.run(command, check=True)
                case = exercise(binary, args.output_dir, binary.name, size, every, enabled,
                                ['B', 'E'] if enabled else [])
                case['build_command'] = command
                cases.append(case)
                if enabled and not size:
                    for label, commands in (('duplicate', ['B', 'B']), ('end-first', ['E'])):
                        cases.append(exercise(binary, args.output_dir, label, size, every, enabled, commands))
    result = dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  compiler=subprocess.check_output(['gcc', '--version'], text=True).splitlines()[0],
                  scope='Native Linux PTY/SIGIO only; virtual UART and Host integration remain separate', cases=cases)
    (args.output_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'LINUX_NATIVE_FENCES_OK cases={len(cases)}')


if __name__ == '__main__':
    main()
