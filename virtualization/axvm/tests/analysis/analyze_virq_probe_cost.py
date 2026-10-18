#!/usr/bin/env python3
"""Validate task observations for equal-work recorder on/off comparisons.

Disabled recording provides no runtime completeness or T0/T3/T4 evidence.
This entry never upgrades such a run into a complete-chain measurement.
"""
import argparse
import csv
import json
from pathlib import Path
import re

from analyze_virq_host import measurement_count, measurement_source
from analyze_virq_isr import analyze as analyze_isr
from analyze_virq_physical import ARM, SUMMARY
from analyze_virq_runtime import parse
from analyze_virq_task import analyze as analyze_task, join_completions

MODE = re.compile(r'VIRQ_RECORDING mode=(on|off) scope=(recorder_writes|recorder_operations)(?: version=(\d+))?')
END = re.compile(r'VIRQ_RECORDING_SUMMARY mode=(on|off) records=(\d+) dropped=(\d+) incomplete=(\d+) stage_observations=(available|unavailable)')


def analyze(log):
    modes = parse(log, 'VIRQ_RECORDING ', MODE)
    endings = parse(log, 'VIRQ_RECORDING_SUMMARY ', END)
    if len(modes) != 1 or len(endings) != 1 or modes[0][0] != endings[0][0]:
        raise ValueError('one consistent recorder mode and final summary required')
    mode = modes[0][0]
    _, declared_scope, version = modes[0]
    if (declared_scope, version) not in (('recorder_writes', None), ('recorder_operations', '2')):
        raise ValueError('unsupported recorder scope/version combination')
    _, count, dropped, incomplete, visibility = endings[0]
    if dropped != '0' or incomplete != '0':
        raise ValueError('recorder comparison contains loss or incomplete writes')
    if mode == 'on':
        if visibility != 'available' or int(count) == 0:
            raise ValueError('enabled recorder has no stage observations')
        rows, result = analyze_task(log)
        runtime = re.findall(r'(?m)^VIRQ_RUNTIME_SUMMARY records=(\d+) dropped=0 incomplete=0\s*$', log)
        if runtime != [count]:
            raise ValueError('recorder and runtime summaries disagree')
    else:
        if visibility != 'unavailable' or count != '0':
            raise ValueError('disabled recorder claims stage observations')
        if any(line.startswith(('VIRQ_RUNTIME ', 'VIRQ_RUNTIME_SUMMARY ', 'VIRQ_READY_SUMMARY '))
               for line in log.splitlines()):
            raise ValueError('disabled recorder contains a runtime completeness claim')
        deliveries, _, clocks = analyze_isr(log)
        if any(c['trace_loss'] is not None for c in clocks.values()):
            raise ValueError('disabled recorder must retain unknown runtime completeness')
        rows, result = join_completions(log, deliveries, clocks, {})
        source, jobs = measurement_source(log), measurement_count(log)
        if source == 'physical_timer_ppi':
            arms = parse(log, 'VIRQ_PHYSICAL_ARM', ARM)
            summaries = parse(log, 'VIRQ_PHYSICAL_SUMMARY', SUMMARY)
            expected = [(p, str(n)) for p in ('fair','fifo80') for n in range(1,jobs+1)]
            if [a[:2] for a in arms] != expected:
                raise ValueError('disabled recording has missing or duplicate timer arms')
            if ([s[0] for s in summaries] != ['fair','fifo80']
                    or any(tuple(map(int,s[1:])) != (30,0,jobs,0,1) for s in summaries)):
                raise ValueError('disabled recording has invalid physical retirement counts')
            for arm, delivery in zip(arms, deliveries):
                p, n, due, intid, cpu = arm
                clock = clocks[p]
                if (intid != '30' or cpu != '0' or not
                        delivery['submit_ticks'] < int(due) <= min(delivery['observed_ticks'],
                            delivery['guest_ticks']+clock['offset_high_ticks'])):
                    raise ValueError('timer arm violates the calibrated ISR observation window')
        elif source != 'software':
            raise ValueError('recorder comparison does not support this physical source')
    result.update(recording_mode=mode, recording_declaration_version=2 if version else 1,
                  declared_recording_scope=declared_scope,
                  comparison_scope='recorder_operations' if version else 'legacy_recorder_writes_declaration',
                  runtime_stage_observations=mode == 'on',
                  task_observations_valid=True,
                  complete_chain_accepted=mode == 'on',
                  source=measurement_source(log))
    result['limitations'].extend([
        'Version 2 includes gated internal timestamp reads, IRQ guards, writer accounting, reservations and slot writes; it is not pure memory-write cost.',
        'The legacy recorder_writes label alone does not prove a pure-write comparison.',
        'Independent task/IRQ timestamps, compiled hooks, mailbox polling, Guest timestamps and Linux fences remain; their full cost is not isolated here.',
        'A single on/off pair is not a repeated estimate or a proof that frequency/temperature are fixed.',
        'Disabled recording has no observed IRQ entry or scheduler stages; missing stages remain null.',
    ])
    return rows, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, result = analyze(args.log.read_text())
    except (OSError,ValueError) as error:
        parser.exit(1, f'invalid recorder-cost observations: {error}\n')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    with (args.output_dir/'samples.csv').open('w',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'RECORDER_TASK_OBSERVATIONS_OK mode={result["recording_mode"]} tasks={len(rows)} complete_chain={int(result["complete_chain_accepted"])}')


if __name__ == '__main__':
    main()
