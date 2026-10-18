#!/usr/bin/env python3
"""Validate A0 worker policy, joined retirement and a finite inversion witness."""

import argparse
import csv
import json
from pathlib import Path
import re

from analyze_virq_physical import analyze as analyze_physical
from analyze_virq_runtime import parse

CONFIG = re.compile(r"VIRQ_IRQ_SERVICE_CONFIG mode=(off|inherit|bounded) limit=(\d+) window_ns=(\d+)")
SERVICE = re.compile(
    r"VIRQ_IRQ_SERVICE vm=(\d+) run=(\d+) thread=(\d+) mode=(off|inherit|bounded) "
    r"target=(fair|fifo) target_priority=(\d+) actual=(fair|fifo) actual_priority=(\d+) "
    r"rounds=(\d+) waits=(\d+) max_rounds=(\d+) limit=(\d+) window_ns=(\d+)"
)
JOIN = re.compile(r"VIRQ_IRQ_SERVICE_JOIN vm=(\d+) run=(\d+) thread=(\d+) joined=1")
WITNESS_CONFIG = re.compile(r"VIRQ_INVERSION_CONFIG cpu=0 priority=60 duration_ms=50 sample=1")
WITNESS = re.compile(
    r"VIRQ_INVERSION_WITNESS policy=(fair|fifo80) sample=1 blocker_cpu=0 blocker_priority=60 "
    r"blocker_thread=(\d+) start_ticks=(\d+) end_ticks=(\d+) due_ticks=(\d+) "
    r"guest_low_ticks=(\d+) guest_high_ticks=(\d+) preempted=([01]) joined=1 wrong_cpu=0"
)


def analyze(log, require_throttle=False):
    rows, physical = analyze_physical(log)
    configs = parse(log, 'VIRQ_IRQ_SERVICE_CONFIG', CONFIG)
    if len(configs) != 1:
        raise ValueError('expected one explicit IRQ service configuration')
    mode, limit, period = configs[0]
    limit, period = int(limit), int(period)
    if not 1 <= limit <= 256 or not 100_000 <= period <= 100_000_000 or period % 1000:
        raise ValueError('invalid IRQ service dispatch limits')
    raw = parse(log, 'VIRQ_IRQ_SERVICE vm=', SERVICE)
    joins = parse(log, 'VIRQ_IRQ_SERVICE_JOIN', JOIN)
    by_thread = {int(t): (int(vm), int(run)) for vm, run, t in joins}
    if len(by_thread) != len(joins) or len(raw) != len(joins):
        raise ValueError('missing, duplicated or orphan IRQ service join')
    records, seen = [], set()
    for vm, run, thread, selected, target, priority, actual, actual_priority, rounds, waits, maximum, actual_limit, actual_period in raw:
        vm, run, thread, priority, actual_priority, rounds, waits, maximum, actual_limit, actual_period = map(
            int, (vm, run, thread, priority, actual_priority, rounds, waits, maximum, actual_limit, actual_period))
        if thread in seen or not thread or by_thread.get(thread) != (vm, run):
            raise ValueError('IRQ service generation was not uniquely joined')
        seen.add(thread)
        if (selected, actual_limit, actual_period) != (mode, limit, period):
            raise ValueError('IRQ service configuration changed within a boot')
        if (target, priority) not in (('fair', 0), ('fifo', 80)):
            raise ValueError('unexpected fixture target policy')
        inherited = mode != 'off' and target == 'fifo'
        if (actual, actual_priority) != (('fifo', priority) if inherited else ('fair', 0)):
            raise ValueError('IRQ service actual base policy did not match its target')
        limited = inherited and mode == 'bounded'
        if limited:
            if not 0 < maximum <= limit or (waits and maximum != limit):
                raise ValueError('IRQ service dispatch cap was violated')
        elif waits or maximum:
            raise ValueError('unlimited service unexpectedly claims throttling')
        records.append(dict(vm=vm, run=run, thread=thread, target=target,
            actual=actual, priority=actual_priority, rounds=rounds, waits=waits,
            maximum_rounds=maximum, joined=True))
    realtime = [r for r in records if r['vm'] == 2]
    if sorted((r['target'], r['run']) for r in realtime) != [
        ('fair', 1), ('fair', 2), ('fifo', 1), ('fifo', 2)
    ]:
        raise ValueError('missing old/new real-time worker generations')
    linux = [r for r in records if r['vm'] == 1]
    expected_linux = physical['load_and_ready']['scenario'] in ('linux_cpu', 'linux_memory')
    if (any(r['vm'] not in (1, 2) for r in records)
            or len(linux) != (2 if expected_linux else 0)
            or any((r['target'], r['run']) != ('fair', 1) for r in linux)):
        raise ValueError('unexpected ordinary-VM worker ownership')
    sample_count = physical['policies']['fair']['samples']
    if any(r['run'] == 2 and r['rounds'] < sample_count for r in realtime):
        raise ValueError('measurement worker has too few dispatch rounds')
    throttled = sum(r['waits'] for r in records)
    if require_throttle and (mode != 'bounded' or throttled == 0):
        raise ValueError('the dispatch limit was not actually exercised')
    throttle_spans = {}
    if require_throttle:
        # Independently constrain elapsed time from Guest timestamps. An
        # incremented waits counter alone would also pass if sleep were removed.
        # The fixture has one outstanding IRQ, with a fresh serial wake/Ready
        # chain per response; no running-vCPU bypass may support this proof.
        group = [r for r in rows if r['policy'] == 'fifo80']
        if physical['execution_context'] != 'current_el' or any(not r['complete'] for r in group):
            raise ValueError('dispatch span proof needs fresh Ready chains for every IRQ')
        frequency = physical['policies']['fifo80']['clock']['frequency_hz']
        span = group[-1]['guest_ticks']-group[0]['guest_ticks']
        # Leave both partial endpoint windows unconstrained. This conservative
        # bound remains valid without knowing the worker window's phase.
        windows = max(0, (len(group)-1+limit-1)//limit-2)
        minimum_ns = windows*period
        if not windows or span*1_000_000_000 < minimum_ns*frequency:
            raise ValueError('Guest response span is too short for the declared dispatch cap')
        throttle_spans['fifo80'] = dict(guest_span_ticks=span,
            minimum_span_ns=minimum_ns, endpoint_windows_unconstrained=2)
    witness_config = parse(log, 'VIRQ_INVERSION_CONFIG', WITNESS_CONFIG)
    witnesses = parse(log, 'VIRQ_INVERSION_WITNESS', WITNESS)
    witness_reports = {}
    if witness_config or witnesses:
        if len(witness_config) != 1 or [w[0] for w in witnesses] != ['fair', 'fifo80']:
            raise ValueError('incomplete or reordered inversion witness')
        for policy, thread, start, end, due, low, high, preempted in witnesses:
            thread, start, end, due, low, high, preempted = map(int, (thread, start, end, due, low, high, preempted))
            row = next(r for r in rows if r['policy'] == policy and r['sample'] == 1)
            clock = physical['policies'][policy]['clock']
            expected = (row['guest_ticks']+clock['offset_low_ticks'], row['guest_ticks']+clock['offset_high_ticks'])
            if not thread or not start < due == row['due_ticks'] <= row['irq_entry_ticks'] < end:
                raise ValueError('the actual physical IRQ did not arrive within the CPU0 blocker')
            if (low, high) != expected or low > high:
                raise ValueError('inversion witness did not use independent calibrated bounds')
            should_preempt = mode != 'off' and policy == 'fifo80'
            if preempted != should_preempt or not (start < low <= high < end if should_preempt else end <= low):
                raise ValueError('guest ISR did not exhibit the declared scheduling order')
            witness_reports[policy] = dict(blocker_start_ticks=start, blocker_end_ticks=end,
                irq_entry_ticks=row['irq_entry_ticks'], guest_low_ticks=low, guest_high_ticks=high,
                guest_preempted_blocker=bool(preempted))
    return rows, dict(mode=mode, dispatch_limit=limit, window_ns=period, workers=records,
        throttle_waits=throttled, throttle_span_proof=throttle_spans,
        inversion_witness=witness_reports, physical=physical,
        limitations=[
            'A0 tests FIFO service-class inheritance and fixed-window dispatch limiting, not Deadline awareness or novelty.',
            'Dispatch rounds are not IRQ counts, CPU execution budgets or arbitrary sliding-window bounds.',
            'The finite FIFO60 blocker is a scheduling-order witness; do not pool it into ordinary performance distributions.',
            'Zero throttle waits do not prove the limiting path. QEMU does not prove hardware performance or hard timing bounds.',
        ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--require-throttle', action='store_true')
    args = parser.parse_args()
    try:
        rows, report = analyze(args.log.read_text(), args.require_throttle)
    except (ValueError, OSError, StopIteration) as error:
        parser.exit(1, f'invalid IRQ service experiment: {error}\n')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir/'samples.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(mode=report['mode'], samples=len(rows), throttle_waits=report['throttle_waits'], witness=report['inversion_witness']), indent=2))


if __name__ == '__main__':
    main()
