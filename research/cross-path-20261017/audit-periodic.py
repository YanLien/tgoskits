#!/usr/bin/env python3
"""Summarize complete periodic cohorts and preserve rejected attempts explicitly."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib

archive=Path(__file__).resolve().parent
repo=archive.parent.parent
cohorts, compiled, heads, locks = {}, [], set(), set()
for name in sys.argv[1:]:
    config=archive/'configs'/name
    out=archive/'results'/name
    identity=json.loads((config/'provenance.json').read_text())
    heads.add(identity['git_commit'])
    locks.add(identity['cargo_lock_sha256'])
    snapshot=archive/identity['source_archive']
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest()==identity['source_archive_sha256']
    assert identity['exit_code']==0
    assert 'AXTEST_SUITE_OK' in (archive/'raw'/(name+'.log')).read_text()
    resource=tomllib.loads((config/'measurement.toml').read_text())
    runtime=json.loads((out/'runtime/summary.json').read_text())
    task=json.loads((out/'task/summary.json').read_text())
    assert runtime['dropped']==runtime['incomplete']==0
    count=resource['samples']
    periodic=task['periodic']
    if periodic:
        assert periodic['jobs']==count and periodic['period_ns']==resource['period_us']*1000
        assert periodic['rounds']==resource['task_rounds']
        assert task['task_deadline_origin']=='scheduled_release'
    else:
        assert resource['period_us']==0 and task['task_deadline_origin']=='host_submit'
    policies={}
    for policy in ('fair','fifo80'):
        data=task['policies'][policy]
        assert data['samples']==count and sum(data['deadline_miss_counts'].values())==count
        info=dict(samples=count, statuses=runtime['policies'][policy]['statuses'],
                  deadline_miss_counts=data['deadline_miss_counts'])
        if periodic:
            info.update({k:v for k,v in periodic['policies'][policy].items() if k not in ('releases','backlog')})
        policies[policy]=info
    cohorts[name]=dict(trace_records=runtime['records'], dropped=0, incomplete=0,
        period_us=resource['period_us'], rounds=resource['task_rounds'],
        irq_pressure=resource['irq_pressure'], deadline_origin=task['task_deadline_origin'], policies=policies,
        source_archive=identity['source_archive'], source_archive_sha256=identity['source_archive_sha256'],
        provenance_sha256=hashlib.sha256((config/'provenance.json').read_bytes()).hexdigest())
    compiled.append({p:h for p,h in identity['source_sha256'].items() if '/analysis/' not in p})
assert all(item==compiled[0] for item in compiled)
assert len(heads)==len(locks)==1
assert hashlib.sha256((repo/'Cargo.lock').read_bytes()).hexdigest() in locks
assert all(hashlib.sha256((repo/p).read_bytes()).hexdigest()==h for p,h in compiled[0].items())
assert all(s['max_isr_outstanding']>1 for s in cohorts['periodic-backlog-32']['policies'].values())
failed=archive/'configs/periodic-disabled-32/provenance.json'
failures={}
if failed.exists():
    data=json.loads(failed.read_text())
    raw=archive/'raw/periodic-disabled-32.log'
    assert data['exit_code']==1 and 'produced no observed progress across the sampling window' in raw.read_text()
    failures['periodic-disabled-32']=dict(exit_code=1,
        reason='No new complete Linux report across the 32-job sampling window',
        accepted=False, log_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
analysis=repo/'virtualization/axvm/tests/analysis'
report=dict(scope='QEMU functional fixed-plan arrivals and Guest backlog; no hardware interference conclusion',
    cohorts=cohorts, failed_attempts=failures, captured_compiled_sources_equal=True,
    common_git_commit=next(iter(heads)), common_cargo_lock_sha256=next(iter(locks)),
    live_compiled_source_matches_captures=True,
    final_analysis_sha256={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(analysis.glob('*.py'))},
    M1_complete=False, M2_complete=False, empirical_interaction_measured=False,
    remaining=['Externally timed periodic hardware arrivals and production path decomposition',
        'Equal-workload probe overhead', 'Exact ordinary-VM throughput',
        'True-board frequency/temperature/counter and A/B validation',
        'Repeated randomized four-cell experiments and interaction uncertainty'])
(archive/'results/periodic-functional-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(cohorts=cohorts,failed_attempts=failures),indent=2))
