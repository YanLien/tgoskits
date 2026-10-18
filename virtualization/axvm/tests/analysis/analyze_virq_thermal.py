#!/usr/bin/env python3
"""Validate quiescent thermal observations without implying a window maximum."""
import argparse
import csv
import json
from pathlib import Path
import re

from analyze_virq_probe_cost import analyze as analyze_tasks
from analyze_virq_runtime import parse

CONFIG=re.compile(r'VIRQ_THERMAL_CONFIG enabled=(0|1) scope=policy_before_create_after_retirement sensors=soc0_little3')
SAMPLE=re.compile(r'VIRQ_THERMAL_SAMPLE policy=(fair|fifo80) point=(before_create|after_retirement) begin_ticks=(\d+) end_ticks=(\d+) frequency_hz=(\d+) soc_mc=(-?\d+) little_mc=(-?\d+)')


def validate(log, windows):
    configs=parse(log,'VIRQ_THERMAL_CONFIG',CONFIG)
    samples=parse(log,'VIRQ_THERMAL_SAMPLE',SAMPLE)
    if len(configs)!=1:
        raise ValueError('one explicit thermal configuration required')
    if configs[0][0]=='0':
        if samples:
            raise ValueError('disabled thermal observation has samples')
        return [],dict(observations_available=False,temperature_mc=None,window_maximum_mc=None)
    expected=[(p,point) for p in ('fair','fifo80') for point in ('before_create','after_retirement')]
    if [s[:2] for s in samples]!=expected:
        raise ValueError('missing, reordered or duplicate thermal sample')
    rows=[]
    previous=0
    for policy,point,*values in samples:
        begin,end,hz,soc,little=map(int,values)
        window=windows[policy]
        if not 0<begin<=end or begin<previous or hz!=window['frequency_hz'] or hz<=0:
            raise ValueError('thermal observation has an invalid clock or ordering')
        if not all(-40_000<=value<=125_000 for value in (soc,little)):
            raise ValueError('thermal observation is outside characterized range')
        if ((point=='before_create' and end>window['first_submit_ticks'])
                or (point=='after_retirement' and begin<window['last_completion_observed_ticks'])):
            raise ValueError('thermal observation overlaps the validated task window')
        previous=end
        rows.append(dict(policy=policy,point=point,begin_ticks=begin,end_ticks=end,
                         frequency_hz=hz,soc_mc=soc,little_mc=little,
                         query_pair_envelope_ns=(end-begin)*1e9/hz))
    return rows,dict(observations_available=True,window_maximum_mc=None,
        sensors=dict(soc='RK3588 TSADC channel0 top',little='RK3588 TSADC channel3 A55 cluster'),
        policies={p:{r['point']:dict(soc_mc=r['soc_mc'],little_mc=r['little_mc'],
                                    query_pair_envelope_ns=r['query_pair_envelope_ns'])
                     for r in rows if r['policy']==p} for p in ('fair','fifo80')})


def analyze(log):
    tasks,task_report=analyze_tasks(log)
    windows={p:dict(first_submit_ticks=min(r['submit_ticks'] for r in tasks if r['policy']==p),
                    last_completion_observed_ticks=max(r['host_task_observed_ticks'] for r in tasks if r['policy']==p),
                    frequency_hz=next(r['frequency_hz'] for r in tasks if r['policy']==p))
             for p in ('fair','fifo80')}
    rows,report=validate(log,windows)
    report.update(task_observations=len(tasks),recording_mode=task_report['recording_mode'],
                  sampling_scope='before each VM group creation and after its retirement',
                  cpu_frequency_hz=None,M1=False,M2=False,
                  limitations=['Four snapshot points do not establish the maximum or constant temperature during a VM window.',
                    'The query-pair envelope includes timestamp reads and possible preemption; not pure probe cost.',
                    'Thermal protection initialization changes the baseline; older cohorts cannot be backfilled.',
                    'No PMU-derived CPU frequency or OPP claim; counter frequency is only the timestamp scale.'])
    return rows,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    try:
        rows,report=analyze(args.log.read_text())
    except (ValueError,OSError) as error:
        parser.exit(1,f'invalid thermal observations: {error}\n')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    with (args.output_dir/'samples.csv').open('w',newline='') as stream:
        fields=list(rows[0]) if rows else ['policy','point','begin_ticks','end_ticks','frequency_hz','soc_mc','little_mc','query_pair_envelope_ns']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'THERMAL_OBSERVATIONS_OK available={int(report["observations_available"])} snapshots={len(rows)} tasks={report["task_observations"]}')


if __name__=='__main__':
    main()
