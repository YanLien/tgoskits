#!/usr/bin/env python3
"""Validate matched PL031 probe states without inventing absent entry timestamps."""

import argparse
import csv
import json
from pathlib import Path
import re

from analyze_virq_host import measurement_count, measurement_source
from analyze_virq_physical import RTC_ARM, RTC_CONFIG, RTC_SUMMARY
from analyze_virq_probe import analyze as analyze_probe, STATES
from analyze_virq_runtime import EVENT, parse
from analyze_virq_services import analyze as analyze_services


def analyze(log, profile):
    rows, calibration, report = analyze_probe(log, profile)
    n = measurement_count(log)
    if measurement_source(log) != 'pl031_spi' or 'VIRQ_PHYSICAL_' in log:
        raise ValueError('physical probe needs an unmixed explicit RTC source')
    if 'VIRQ_RTC_CLEANUP_FAILED' in log:
        raise ValueError('RTC cleanup failed')
    if len(parse(log, 'VIRQ_RTC_CONFIG', RTC_CONFIG)) != 2:
        raise ValueError('missing exact inactive RTC configurations')
    summaries = parse(log, 'VIRQ_RTC_SUMMARY', RTC_SUMMARY)
    if (len(summaries) != 2 or {s[0] for s in summaries} != {'fair', 'fifo80'}
            or any(tuple(map(int, s[1:])) != (34, 0, n, 0, 1) for s in summaries)):
        raise ValueError('RTC count, retirement or restoration mismatch')
    placement = analyze_services(log)
    if placement['mode'] != 'cpu0' or not placement['verified']:
        raise ValueError('physical probe lacks common CPU0 service placement')
    if parse(log, 'VIRQ_CONTROLLER', re.compile(r'VIRQ_CONTROLLER cpu=(\d+)')) != [('0',)]:
        raise ValueError('physical probe controller is not CPU0')
    arms = parse(log, 'VIRQ_RTC_ARM', RTC_ARM)
    matched = {}
    for policy in ('fair', 'fifo80'):
        selected = [arm for arm in arms if arm[0] == policy]
        if [int(arm[1]) for arm in selected] != list(range(1, n+1)):
            raise ValueError('RTC arm sequence incomplete or duplicated')
        for _, index, seconds, intid, cpu in selected:
            if (int(intid), int(cpu)) != (34, 0) or not 0 <= int(seconds) < 2**32:
                raise ValueError('RTC source identity or seconds invalid')
            matched[policy, int(index)] = int(seconds)
    entries = [e for e in parse(log, 'VIRQ_RUNTIME ', EVENT) if e[3] == 'HostIrqEntry']
    if profile == 'enabled':
        if len(entries) != n*2 or any((int(e[0]), int(e[4]), int(e[5]), int(e[6])) != (0, 0, 34, 1) for e in entries):
            raise ValueError('wrong physical ingress count, CPU, INTID or context')
    elif entries:
        raise ValueError('inactive capture unexpectedly has physical ingress')
    used = set()
    for row in rows:
        row['rtc_match_seconds'] = matched[row['policy'], row['sample']]
        row['arm_to_c_isr_lower_ns'] = row['isr_lower_ns']
        row['arm_to_c_isr_upper_ns'] = row['isr_upper_ns']
        row['entry_to_c_isr_lower_ns'] = ''
        row['entry_to_c_isr_upper_ns'] = ''
        if profile != 'enabled':
            continue
        candidates = [e for e in entries if row['submit_ticks'] <= int(e[2]) <= row['observed_ticks']]
        if len(candidates) != 1:
            raise ValueError('no unique ingress within the sample window')
        entry = candidates[0]
        identity = entry[0], entry[1]
        if identity in used:
            raise ValueError('physical ingress reused across samples')
        used.add(identity)
        ticks = int(entry[2])
        clock = report['clocks'][row['policy']]
        low = max(ticks, row['guest_ticks']+clock['offset_low_ticks'])
        high = min(row['observed_ticks'], row['guest_ticks']+clock['offset_high_ticks'])
        if low > high:
            raise ValueError('physical ingress and calibrated ISR violate causality')
        hz = row['frequency_hz']
        row['entry_to_c_isr_lower_ns'] = (low-ticks)*1_000_000_000//hz
        row['entry_to_c_isr_upper_ns'] = ((high-ticks)*1_000_000_000+hz-1)//hz
    report.update(source='pl031_spi', service_placement=placement, physical_intid=34,
                  physical_entries=len(entries), controller_cpu=0,
                  source_cpu=0, target_cpu=1,
                  physical_entry_interval_available=profile == 'enabled')
    report['limitations'].append('RTC seconds are not host deadlines; arm-to-ISR is common across states. No absent entry interval is filled with zero.')
    return rows, calibration, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--profile', choices=STATES, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    rows, calibration, report = analyze(args.log.read_text(), args.profile)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for label, records in [('samples', rows), ('calibration', calibration)]:
        with (args.output_dir/(label+'.csv')).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    (args.output_dir/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
