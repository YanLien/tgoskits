#!/usr/bin/env python3
"""Validate bracketed PMU snapshots without claiming active-window frequency."""
import argparse
import csv
import json
from pathlib import Path
import re

from analyze_virq_probe_cost import analyze as analyze_tasks
from analyze_virq_runtime import parse

CONFIG = re.compile(r'VIRQ_FREQUENCY_CONFIG enabled=(0|1) scope=policy_before_create_after_retirement method=pmu_cycle_bracket target_us=2000 cpus=(\d+)')
SAMPLE = re.compile(r'VIRQ_FREQUENCY_SAMPLE policy=(fair|fifo80) point=(before_create|after_retirement) cpu=(\d+) midr=(\d+) pmuver=(\d+) t0=(\d+) t1=(\d+) t2=(\d+) t3=(\d+) c0=(\d+) c1=(\d+) counter_hz=(\d+)')


def validate(log, windows):
    configs = parse(log, 'VIRQ_FREQUENCY_CONFIG', CONFIG)
    samples = parse(log, 'VIRQ_FREQUENCY_SAMPLE', SAMPLE)
    if len(configs) != 1:
        raise ValueError('one explicit frequency configuration required')
    enabled, cpus = map(int, configs[0])
    if not 1 <= cpus <= 64:
        raise ValueError('invalid frequency CPU count')
    report = dict(observations_available=bool(enabled), window_frequency_hz=None,
                  continuous_coverage=False, cpu_count=cpus, timestamp_quantum_ticks=1, cycle_quantum=1)
    if not enabled:
        if samples:
            raise ValueError('disabled frequency observation has samples')
        return [], report
    expected = [(p, point, cpu) for p in ('fair', 'fifo80')
                for point in ('before_create', 'after_retirement') for cpu in range(cpus)]
    if [(s[0], s[1], int(s[2])) for s in samples] != expected:
        raise ValueError('missing, reordered or duplicate frequency sample')
    rows, identities = [], {}
    previous = 0
    for policy, point, *values in samples:
        cpu, midr, version, t0, t1, t2, t3, c0, c1, hz = map(int, values)
        window = windows[policy]
        if (not 0 < t0 <= t1 < t2 <= t3 or t0 < previous or hz <= 0
                or hz != window['frequency_hz'] or t2 - t1 < max(2, hz // 500)):
            raise ValueError('invalid or short frequency time bracket')
        if (midr <= 0 or version not in (1, 4, 5, 6) or not 0 <= c0 < c1 < 2**64
                or t3 >= 2**64):
            raise ValueError('invalid PMU identity, version or cycle progression')
        if cpu in identities and identities[cpu] != (midr, version):
            raise ValueError('frequency CPU identity changed')
        identities[cpu] = (midr, version)
        if ((point == 'before_create' and t3 > window['first_submit_ticks'])
                or (point == 'after_retirement' and t0 < window['last_completion_observed_ticks'])):
            raise ValueError('frequency snapshot overlaps the task window')
        previous = t3
        delta = c1 - c0
        rows.append(dict(policy=policy, point=point, cpu=cpu, midr=midr, pmuver=version,
                         t0=t0, t1=t1, t2=t2, t3=t3, c0=c0, c1=c1, counter_hz=hz,
                         cycles=delta, frequency_lower_hz=(delta-1)*hz/(t3-t0+1),
                         frequency_upper_hz=(delta+1)*hz/(t2-t1-1)))
    return rows, report


def analyze(log):
    tasks, task_report = analyze_tasks(log)
    windows = {p: dict(first_submit_ticks=min(r['submit_ticks'] for r in tasks if r['policy'] == p),
                       last_completion_observed_ticks=max(r['host_task_observed_ticks'] for r in tasks if r['policy'] == p),
                       frequency_hz=next(r['frequency_hz'] for r in tasks if r['policy'] == p))
               for p in ('fair', 'fifo80')}
    rows, report = validate(log, windows)
    report.update(task_observations=len(tasks), recording_mode=task_report['recording_mode'],
                  method='exclusive temporary PMU cycle counter, two timestamp brackets',
                  M1=False, M2=False, limitations=[
                      'Busy arithmetic with local IRQs masked perturbs the sampled CPU and may affect firmware frequency policy.',
                      'The bounds concern the two cycle reads, not continuous frequency during any VM window.',
                      'No OPP is requested; these observations do not establish fixed frequency or the maximum CPU capability.',
                      'Bounds include one reference tick and one cycle of quantization at the interval boundaries, assuming the advertised reference frequency.',
                      'Reference-clock calibration error and firmware interruptions are not bounded here.',
                      'QEMU cycle values are functional evidence only, not physical frequency evidence.'])
    return rows, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, report = analyze(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f'invalid frequency observations: {error}\n')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir/'samples.csv').open('w', newline='') as stream:
        fields = list(rows[0]) if rows else ['policy', 'point', 'cpu', 'frequency_lower_hz', 'frequency_upper_hz']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'FREQUENCY_OBSERVATIONS_OK available={int(report["observations_available"])} snapshots={len(rows)} tasks={report["task_observations"]}')


if __name__ == '__main__':
    main()
