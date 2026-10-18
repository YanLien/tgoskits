#!/usr/bin/env python3
"""Validate fixed logical arrivals, immutable drain and measured outstanding jobs."""
import argparse
import json
from pathlib import Path
import re

from analyze_virq_runtime import parse

CONFIG = re.compile(r'VIRQ_PERIODIC_CONFIG version=1 period_ns=(\d+) period_ticks=(\d+) rounds=(\d+) jobs=(\d+) frequency_hz=(\d+) deadline_origin=scheduled_release')
RELEASE = re.compile(r'VIRQ_PERIODIC_RELEASE policy=(fair|fifo80) sample=(\d+) scheduled_ticks=(\d+) submitted_ticks=(\d+) host_due_backlog=(\d+)')
BACKLOG = re.compile(r'VIRQ_PERIODIC_BACKLOG policy=(fair|fifo80) sample=(\d+) isr_outstanding=(\d+) task_outstanding=(\d+)')
DRAIN = re.compile(r'VIRQ_PERIODIC_DRAIN policy=(fair|fifo80) jobs=(\d+) completed=(\d+) observed_ticks=(\d+) ready=1')


def workload_checksum(rounds):
    value, multiplier, increment = 0x12345678, 1664525, 1013904223
    while rounds:
        if rounds & 1:
            value = (value * multiplier + increment) % (1 << 32)
        increment = increment * (multiplier + 1) % (1 << 32)
        multiplier = multiplier * multiplier % (1 << 32)
        rounds >>= 1
    return value


def protocol(log):
    config = parse(log, 'VIRQ_PERIODIC_CONFIG', CONFIG)
    releases = parse(log, 'VIRQ_PERIODIC_RELEASE', RELEASE)
    backlog = parse(log, 'VIRQ_PERIODIC_BACKLOG', BACKLOG)
    drains = parse(log, 'VIRQ_PERIODIC_DRAIN', DRAIN)
    if not config:
        if 'VIRQ_PERIODIC_' in log:
            raise ValueError('Periodic records have no configuration')
        return None
    if len(config) != 1:
        raise ValueError('Periodic configuration must be unique')
    period, ticks, rounds, jobs, frequency = map(int, config[0])
    if not (100000 <= period <= 1000000000 and period % 1000 == 0 and ticks > 0
            and ticks == period * frequency // 1000000000 and 4096 <= rounds <= 1048576
            and 1 <= jobs <= 1000 and frequency > 0):
        raise ValueError('Invalid periodic period, work or clock')
    expected_ids = [(policy, str(i)) for policy in ('fair', 'fifo80') for i in range(1, jobs+1)]
    if ([row[:2] for row in releases] != expected_ids or [row[:2] for row in backlog] != expected_ids
            or [row[0] for row in drains] != ['fair', 'fifo80']):
        raise ValueError('Periodic release, backlog or drain stream incomplete')
    result = dict(period_ns=period, period_ticks=ticks, rounds=rounds, jobs=jobs,
                  frequency_hz=frequency, policies={})
    for policy, count, completed, observed in drains:
        if int(count) != jobs or int(completed) != jobs:
            raise ValueError('Periodic drain count mismatch')
        selected = [tuple(map(int, row[1:])) for row in releases if row[0] == policy]
        depth = [tuple(map(int, row[1:])) for row in backlog if row[0] == policy]
        epoch, previous = selected[0][1], 0
        for number, due, submitted, pending in selected:
            arrived = min(jobs, (submitted-epoch)//ticks+1)
            if not (due == epoch+(number-1)*ticks and due <= submitted and previous <= submitted
                    and submitted <= int(observed) and pending == arrived-number):
                raise ValueError('Periodic grid, lateness or Host due backlog mismatch')
            previous = submitted
        if any(not 1 <= item <= jobs for _, a, b in depth for item in (a, b)):
            raise ValueError('Guest outstanding count out of range')
        result['policies'][policy] = dict(releases=selected, backlog=depth, drain_observed_ticks=int(observed))
    return result


def annotate(log, rows, clocks, deadline_ns, rounds):
    report = protocol(log)
    if report is None:
        if rounds != 4096:
            raise ValueError('Non-periodic workload must retain 4096 rounds')
        return None
    if rounds != report['rounds']:
        raise ValueError('Periodic and task workloads disagree')
    expected_ids = [(p, i) for p in ('fair', 'fifo80') for i in range(1, report['jobs']+1)]
    if [(row['policy'], row['sample']) for row in rows] != expected_ids:
        raise ValueError('Periodic jobs do not match task/ISR IDs')
    for policy, state in report['policies'].items():
        selected = [r for r in rows if r['policy'] == policy]
        clock = clocks[policy]
        hz = clock['frequency_hz']
        if hz != report['frequency_hz']:
            raise ValueError('Periodic and critical clocks disagree')
        previous_end, previous_isr_observation = 0, 0
        for row, release, backlog in zip(selected, state['releases'], state['backlog']):
            number, due, submitted, host_pending = release
            _, isr_pending, task_pending = backlog
            observed = state['drain_observed_ticks']
            if (row['submit_ticks'] != submitted or row['host_task_observed_ticks'] != observed
                    or row['task_start_ticks'] < previous_end or submitted < previous_isr_observation):
                raise ValueError('Periodic task order or bulk observation mismatch')
            previous_end = row['task_end_ticks']
            previous_isr_observation = row['host_isr_observed_ticks']
            isr = row['guest_isr_ticks']
            start = row['task_start_ticks']
            # Equality of counter ticks admits either order; do not invent one.
            before = sum(r['task_end_ticks'] < isr for r in selected)
            by = sum(r['task_end_ticks'] <= isr for r in selected)
            arrived_before = sum(r['guest_isr_ticks'] < start for r in selected)
            arrived_by = sum(r['guest_isr_ticks'] <= start for r in selected)
            if not (number-by <= isr_pending <= number-before
                    and arrived_before-number+1 <= task_pending <= arrived_by-number+1):
                raise ValueError('Guest outstanding count contradicts its timestamps')
            low = max(submitted, row['task_end_ticks']+clock['offset_low_ticks'])
            high = min(observed, row['task_end_ticks']+clock['offset_high_ticks'])
            lower, upper = (low-due)*1000000000, (high-due)*1000000000
            row.update(scheduled_release_ticks=due, host_due_backlog=host_pending,
                release_lateness_ns=(submitted-due)*1000000000/hz,
                isr_outstanding=isr_pending, task_outstanding=task_pending,
                release_to_completion_lower_ns=lower//hz,
                release_to_completion_upper_ns=(upper+hz-1)//hz,
                task_deadline_miss='true' if lower > deadline_ns*hz else
                    'false' if upper <= deadline_ns*hz else 'unknown')
        state.update(max_isr_outstanding=max(r['isr_outstanding'] for r in selected),
            max_task_outstanding=max(r['task_outstanding'] for r in selected),
            jobs_with_guest_backlog=sum(r['isr_outstanding'] > 1 for r in selected),
            max_host_due_backlog=max(r['host_due_backlog'] for r in selected))
    return report


def main():
    from analyze_virq_task import analyze
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        _, summary = analyze(args.log.read_text())
        report = summary['periodic']
        if report is None:
            raise ValueError('No periodic cohort')
    except (ValueError, OSError) as error:
        parser.exit(1, f'invalid periodic measurement: {error}\n')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({p: {k:v for k,v in s.items() if k not in ('releases','backlog')}
                      for p,s in report['policies'].items()}))


if __name__ == '__main__':
    main()
