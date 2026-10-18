#!/usr/bin/env python3
"""Validate causal Linux work snapshots and quantify their whole-window rates."""

import argparse
import json
from pathlib import Path
import re

from analyze_virq_irq_pressure import validate_pressure, verify_window
from analyze_virq_runtime import parse
from virq_work_counters import LINUX_PROGRESS, checksum_after, linux_memory_expected

CONFIG = re.compile(r'VIRQ_LINUX_FENCE_CONFIG version=1 mode=(off|serial) clock=monotonic_raw')
READY = re.compile(r'LINUX_FENCE_READY version=1 clock=monotonic_raw resolution_ns=(\d+) working_set_bytes=(\d+) every_batches=(\d+)')
REPLY = re.compile(r'LINUX_FENCE_REPLY version=1 phase=(begin|end) batches=(\d+) checksum=(\d+) time_ns=(\d+) guest_cpu=0(?: memory_batches=(\d+) logical_bytes=(\d+) memory_checksum=(\d+))?')
SUMMARY = re.compile(r'VIRQ_LINUX_FENCE_SUMMARY policy=(fair|fifo80) begin_batches=(\d+) end_batches=(\d+) begin_ns=(\d+) end_ns=(\d+) begin_request_ticks=(\d+) begin_observed_ticks=(\d+) end_request_ticks=(\d+) end_observed_ticks=(\d+) frequency_hz=(\d+) stopped=1')
MEMORY = re.compile(r'VIRQ_LINUX_MEMORY_CONFIG working_set_bytes=(\d+) every_batches=(\d+) chunk_words=8192')


def check_work(count, checksum, memory_fields, size, every):
    if not 0 < count <= ((1 << 64) - 1) // 8192 or checksum != checksum_after(count * 8192):
        raise ValueError('Linux fence workload checksum or counter overflow')
    if size:
        if memory_fields[0] is None or tuple(map(int, memory_fields)) != linux_memory_expected(count, size, every):
            raise ValueError('Linux fence memory counters or checksum mismatch')
    elif memory_fields[0] is not None:
        raise ValueError('CPU fence has memory fields')


def summarize(fields, snapshots, resolution, size, every):
    policy = fields[0]
    start, end, begin_ns, end_ns, request, observed, end_request, end_observed, hz = map(int, fields[1:])
    if (start, begin_ns, end, end_ns) != (*snapshots[0], *snapshots[1]):
        raise ValueError('Host fence summary differs from actual Guest replies')
    if not (0 < start < end and 0 < begin_ns < end_ns
            and 0 < request <= observed < end_request <= end_observed and hz > 0):
        raise ValueError('Linux fenced work or causal clock order is invalid')
    ns, scale = end_ns - begin_ns, 1_000_000_000
    lower = (end_request - observed) * scale // hz
    upper = ((end_observed - request) * scale + hz - 1) // hz
    tolerance = 2 * ((scale + hz - 1) // hz + resolution)
    if ns + tolerance < lower or ns > upper + tolerance:
        raise ValueError('Linux Guest elapsed violates Host causal bounds')
    iterations = (end - start) * 8192
    result = dict(policy=policy, begin_batches=start, end_batches=end, interval_batches=end-start,
                  begin_ns=begin_ns, end_ns=end_ns, elapsed_ns=ns, clock='monotonic_raw',
                  clock_resolution_ns=resolution, begin_request_ticks=request, begin_observed_ticks=observed,
                  end_request_ticks=end_request, end_observed_ticks=end_observed, frequency_hz=hz,
                  host_elapsed_lower_ns=lower, host_elapsed_upper_ns=upper, clock_tolerance_ns=tolerance,
                  begin_handshake_ns=(observed-request)*scale/hz,
                  end_handshake_ns=(end_observed-end_request)*scale/hz,
                  interval_iterations=iterations, iterations_per_second=iterations*scale/ns,
                  iterations_per_second_causal_lower=iterations*scale/(upper+tolerance),
                  iterations_per_second_causal_upper=(iterations*scale/(lower-tolerance)
                                                     if lower > tolerance else None), stopped=True)
    if size:
        before = linux_memory_expected(start, size, every)
        after = linux_memory_expected(end, size, every)
        reads = (after[1]-before[1]) // 2
        result.update(working_set_bytes=size, every_batches=every,
                      interval_memory_batches=after[0]-before[0], logical_read_bytes=reads,
                      logical_write_bytes=reads, logical_read_bytes_per_second=reads*scale/ns,
                      logical_write_bytes_per_second=reads*scale/ns)
    return result


def validate_fences(log):
    """Fail closed on orphan/malformed records; legacy streams have no rates."""
    configs = parse(log, 'VIRQ_LINUX_FENCE_CONFIG', CONFIG)
    records = [line.strip() for line in log.splitlines() if 'LINUX_FENCE_' in line
               and 'VIRQ_LINUX_FENCE_CONFIG' not in line]
    if not configs:
        if records:
            raise ValueError('Linux fence evidence without configuration')
        return dict(mode='off_legacy', policies={})
    if len(configs) != 1:
        raise ValueError('Linux fences need exactly one configuration')
    mode = configs[0][0]
    if mode == 'off':
        if records or 'LINUX_LOAD_READY version=2' in log:
            raise ValueError('Disabled Linux fences contain active evidence')
        return dict(mode=mode, policies={})
    memory = parse(log, 'VIRQ_LINUX_MEMORY_CONFIG', MEMORY)
    size, every = (0, 1) if not memory else tuple(map(int, memory[0]))
    if len(memory) > 1 or (memory and (not 1048576 <= size <= 67108864 or size % 8192 or not 1 <= every <= 1024)):
        raise ValueError('Invalid Linux fence memory configuration')
    active, retired, report, resolution, snapshots, summary_policy = False, True, 0, None, [], None
    policies = {}
    config_seen = False
    for raw in log.splitlines():
        line = raw.strip()
        if 'VIRQ_LINUX_FENCE_CONFIG' in line:
            config_seen = True
        elif 'LINUX_LOAD_FAILED' in line:
            raise ValueError('Linux fence workload failed')
        elif 'LINUX_LOAD_READY' in line:
            if (not config_seen or active or not retired
                    or line != 'LINUX_LOAD_READY version=2 guest_cpu=0 batch_iterations=8192 report_batches=256'):
                raise ValueError('Linux fence readiness version or lifecycle mismatch')
            active, retired, report, resolution, snapshots, summary_policy = True, False, 0, None, [], None
        elif 'LINUX_FENCE_READY' in line:
            match = READY.fullmatch(line)
            if (not active or resolution is not None or report or match is None
                    or tuple(map(int, match.groups()[1:])) != (size, every)
                    or not 1 <= int(match[1]) <= 1000000):
                raise ValueError('Linux fence clock/workload declaration mismatch')
            resolution = int(match[1])
        elif 'LINUX_LOAD_PROGRESS' in line:
            match = LINUX_PROGRESS.fullmatch(line)
            if not active or resolution is None or match is None:
                raise ValueError('Linux report before fence readiness or after stop')
            count, checksum = map(int, match.groups()[:2])
            check_work(count, checksum, match.groups()[2:], size, every)
            if count != report + 256 or (snapshots and count < snapshots[-1][0]):
                raise ValueError('Linux report regressed across a fence snapshot')
            report = count
        elif 'LINUX_FENCE_REPLY' in line:
            match = REPLY.fullmatch(line)
            if not active or resolution is None or match is None or len(snapshots) >= 2 or summary_policy:
                raise ValueError('Linux fence reply outside its active phase')
            phase, count, checksum, ns, *work = match.groups()
            count, checksum, ns = map(int, (count, checksum, ns))
            check_work(count, checksum, work, size, every)
            if phase != ('begin' if not snapshots else 'end') or not report <= count <= report + 256 or ns <= 0:
                raise ValueError('Linux fence phase or adjacent report bounds mismatch')
            snapshots.append((count, ns))
        elif 'VIRQ_LINUX_FENCE_SUMMARY' in line:
            match = SUMMARY.fullmatch(line)
            if (not active or summary_policy or len(snapshots) != 2 or match is None
                    or match[1] != ('fair' if not policies else 'fifo80') or match[1] in policies):
                raise ValueError('Linux fence summary missing, duplicated or reordered')
            summary_policy = match[1]
            policies[summary_policy] = summarize(match.groups(), snapshots, resolution, size, every)
        elif 'LINUX_FENCE_' in line:
            raise ValueError('Unknown Linux fence record')
        elif 'VIRQ_LINUX_SUMMARY' in line:
            if not active or not summary_policy or f'policy={summary_policy} ' not in line:
                raise ValueError('Linux stopped before its fence proof completed')
            active = False
        elif 'VIRQ_VM_GROUP_RETIRED' in line:
            if active or retired or not summary_policy:
                raise ValueError('Linux fence group retirement out of order')
            retired = True
    if active or not retired or list(policies) != ['fair', 'fifo80']:
        raise ValueError('Incomplete Linux fenced streams')
    pressure = validate_pressure(log)
    for policy, state in policies.items():
        verify_window(pressure, policy, state['begin_request_ticks'], state['end_observed_ticks'], state['frequency_hz'])
    return dict(mode=mode, policies=policies)


def verify_fence_window(fences, policy, start, end, frequency):
    """Require the complete critical plan/observation inside causal fences."""
    if fences['mode'] != 'serial':
        return
    state = fences['policies'][policy]
    if frequency != state['frequency_hz']:
        raise ValueError('Linux fences and critical chain use different clocks')
    if not state['begin_observed_ticks'] <= start <= end <= state['end_request_ticks']:
        raise ValueError('Linux fenced interval does not cover the critical window')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    log = args.log.read_text()
    from analyze_virq_load import validate_load
    from analyze_virq_task import analyze as analyze_task
    validate_load(log)
    _, tasks = analyze_task(log)
    result = validate_fences(log)
    if result['mode'] != 'serial':
        raise ValueError('No enabled Linux throughput fence evidence')
    result.update(task_deadline_origin=tasks['task_deadline_origin'], limitations=[
        'Causal time bounds express clock quantization and handshake uncertainty, not a statistical confidence interval.',
        'Whole-window completed user work includes signal checks and handshake/logging costs; not per-ISR throughput or DRAM traffic.',
        'Work after the End snapshot, including unreported tail batches before VM stop, is not credited.',
        'QEMU validates protocol and lifecycle only; real hardware interference and probe overhead remain unproven.'])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'linux-fence-summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(f"LINUX_FENCE_ANALYSIS_OK policies={len(result['policies'])}")


if __name__ == '__main__':
    main()
