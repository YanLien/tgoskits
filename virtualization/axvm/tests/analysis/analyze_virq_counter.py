#!/usr/bin/env python3
"""Observe counter increments without promoting a sample GCD to a hardware bound."""
import argparse
from collections import Counter
import csv
from functools import reduce
import json
from math import gcd
from pathlib import Path
import re

from analyze_virq_frequency import validate as validate_frequency
from analyze_virq_probe_cost import analyze as analyze_tasks
from analyze_virq_runtime import parse

CONFIG = re.compile(r'VIRQ_COUNTER_CONFIG enabled=(0|1) version=1 reads=256 modes=physical_virtual_raw scope=before_frequency_cycles exception_level=2')
SERIES = re.compile(r'VIRQ_COUNTER_SERIES policy=(fair|fifo80) point=(before_create|after_retirement) cpu=(\d+) mode=(physical|virtual|physical_raw) begin_ticks=(\d+) end_ticks=(\d+) counter_hz=(\d+) values=(\[.*\])')
MODES = ('physical', 'virtual', 'physical_raw')


def validate(log, windows):
    frequency_rows, frequency = validate_frequency(log, windows)
    configs = parse(log, 'VIRQ_COUNTER_CONFIG', CONFIG)
    series = parse(log, 'VIRQ_COUNTER_SERIES', SERIES)
    if len(configs) != 1 or bool(int(configs[0][0])) != frequency['observations_available']:
        raise ValueError('counter configuration missing or inconsistent with frequency')
    report = dict(observations_available=frequency['observations_available'],
                  effective_resolution_verified=False, physical_frequency_error_bounds_verified=False,
                  window_frequency_hz=None, exception_level=2)
    if not frequency['observations_available']:
        if series:
            raise ValueError('disabled counter observation has raw series')
        return [], [], report
    expected = [(r['policy'], r['point'], r['cpu'], mode) for r in frequency_rows for mode in MODES]
    if [(s[0], s[1], int(s[2]), s[3]) for s in series] != expected:
        raise ValueError('missing, duplicate or reordered counter series')
    lookup = {(r['policy'], r['point'], r['cpu']): r for r in frequency_rows}
    rows, sensitivity = [], []
    previous_end = 0
    for policy, point, cpu, mode, begin, end, hz, encoded in series:
        cpu, begin, end, hz = map(int, (cpu, begin, end, hz))
        f = lookup[policy, point, cpu]
        values = json.loads(encoded)
        if not isinstance(values, list) or len(values) != 256 or any(type(v) is not int or not 0 <= v < 2**64 for v in values):
            raise ValueError('counter series requires exactly 256 u64 values')
        if not 0 < begin <= end <= f['t0'] or begin < previous_end or hz != f['counter_hz']:
            raise ValueError('counter series clock envelope is invalid')
        window = windows[policy]
        if ((point == 'before_create' and end > window['first_submit_ticks'])
                or (point == 'after_retirement' and begin < window['last_completion_observed_ticks'])):
            raise ValueError('counter series overlaps the task window')
        previous_end = end
        differences = [b-a for a, b in zip(values, values[1:])]
        positive = [d for d in differences if d > 0]
        backwards = sum(d < 0 for d in differences)
        if mode != 'physical_raw' and (backwards or not positive):
            raise ValueError('serialized counter reversed or did not progress')
        if mode != 'virtual' and any(not begin <= v <= end for v in values):
            raise ValueError('physical values escape the serialized envelope')
        common = reduce(gcd, positive, 0)
        row = dict(policy=policy, point=point, cpu=cpu, mode=mode,
                   begin_ticks=begin, end_ticks=end, counter_hz=hz,
                   envelope_ns=(end-begin)*1e9/hz, reads=len(values), zero_differences=differences.count(0),
                   backwards_differences=backwards, positive_differences=len(positive),
                   minimum_positive_ticks=min(positive) if positive else None,
                   maximum_positive_ticks=max(positive) if positive else None, observed_gcd_ticks=common,
                   positive_histogram=json.dumps(dict(sorted(Counter(positive).items()))), values=encoded)
        rows.append(row)
        if mode == 'physical':
            for q in sorted({1, common or 1}):
                numerator = (f['c1']-f['c0'])
                denominator = f['t2']-f['t1']-q
                sensitivity.append(dict(policy=policy, point=point, cpu=cpu, assumed_quantum_ticks=q,
                    lower_hz=max(0, numerator-1)*hz/(f['t3']-f['t0']+q),
                    upper_hz=(numerator+1)*hz/denominator if denominator > 0 else None,
                    interpretation='sensitivity under an assumption; not a verified hardware error bound'))
    report['series'] = len(rows)
    report['raw_reads'] = sum(r['reads'] for r in rows)
    report['by_mode'] = {mode: dict(
        series=sum(r['mode'] == mode for r in rows),
        zero_differences=sum(r['zero_differences'] for r in rows if r['mode'] == mode),
        backwards_differences=sum(r['backwards_differences'] for r in rows if r['mode'] == mode),
        observed_positive_ticks=sorted({int(k) for r in rows if r['mode'] == mode for k in json.loads(r['positive_histogram'])}),
        gcd_of_positive_differences=reduce(gcd, (r['observed_gcd_ticks'] for r in rows if r['mode'] == mode), 0)) for mode in MODES}
    return rows, sensitivity, report


def analyze(log):
    tasks, task_report = analyze_tasks(log)
    windows = {p: dict(first_submit_ticks=min(r['submit_ticks'] for r in tasks if r['policy'] == p),
                       last_completion_observed_ticks=max(r['host_task_observed_ticks'] for r in tasks if r['policy'] == p),
                       frequency_hz=next(r['frequency_hz'] for r in tasks if r['policy'] == p))
               for p in ('fair', 'fifo80')}
    rows, sensitivity, report = validate(log, windows)
    report.update(task_observations=len(tasks), recording_mode=task_report['recording_mode'], M1=False, M2=False,
        limitations=['Observed increments and their GCD are sampling statistics, not a certified maximum counter update step.',
                     'Only nominal CNTFRQ is available; no independent oscillator calibration or firmware counter-mode identity.',
                     'Raw reads have no per-read ISB and are diagnostic, not causal timestamps.',
                     'Capture precedes each frequency measurement and may warm the CPU; it is outside all VM task windows.'])
    return rows, sensitivity, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, sensitivity, report = analyze(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f'invalid counter observations: {error}\n')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, data, empty_fields in (('series.csv', rows, ['policy', 'point', 'cpu', 'mode']),
                                     ('frequency-sensitivity.csv', sensitivity, ['policy', 'point', 'cpu', 'assumed_quantum_ticks'])):
        with (args.output_dir/name).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]) if data else empty_fields)
            writer.writeheader()
            writer.writerows(data)
    (args.output_dir/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'COUNTER_OBSERVATIONS_OK available={int(report["observations_available"])} series={len(rows)} reads={report.get("raw_reads", 0)} tasks={report["task_observations"]}')


if __name__ == '__main__':
    main()
