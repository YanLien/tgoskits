#!/usr/bin/env python3
"""Audit frozen inputs and causal throughput evidence, never infer hardware effects."""

import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import tomllib

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
cohorts, failures, source_sets, heads, locks = {}, {}, [], set(), set()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


for name in sys.argv[1:]:
    config, output = archive/'configs'/name, archive/'results'/name
    identity = json.loads((config/'provenance.json').read_text())
    raw = archive/'raw'/(name+'.log')
    assert digest(archive/identity['source_archive']) == identity['source_archive_sha256']
    with tarfile.open(archive/identity['source_archive']) as snapshot:
        assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == value
                   for p, value in identity['source_sha256'].items())
    heads.add(identity['git_commit'])
    locks.add(identity['cargo_lock_sha256'])
    source_sets.append(identity['source_sha256'])
    if identity['exit_code']:
        state = re.search(r'timed out: \[([^]]+)\]', raw.read_text())
        failures[name] = dict(exit_code=identity['exit_code'], accepted=False,
                              log_sha256=digest(raw), source_archive=identity['source_archive'],
                              provenance_sha256=digest(config/'provenance.json'),
                              timeout_mailbox=state[1] if state else None,
                              pressure_capacity_exhausted='SGI pressure capacity exhausted' in raw.read_text(),
                              attribution='Unresolved: Host RTC counts were not captured on failure')
        continue
    assert 'AXTEST_SUITE_OK' in raw.read_text()
    resource = tomllib.loads((config/'measurement.toml').read_text())
    build = json.loads((config/'linux-build.json').read_text())
    runtime = json.loads((output/'runtime/summary.json').read_text())
    tasks = json.loads((output/'task/summary.json').read_text())
    loads = json.loads((output/'load/summary.json').read_text())
    assert runtime['dropped'] == runtime['incomplete'] == 0
    enabled = resource['linux_fences_enabled']
    assert build['fences_enabled'] == enabled
    assert tasks['linux_fences']['mode'] == ('serial' if enabled else 'off')
    states = {}
    if enabled:
        fence = json.loads((output/'linux_fence/linux-fence-summary.json').read_text())
        assert fence['policies'] == tasks['linux_fences']['policies']
    for policy in ('fair', 'fifo80'):
        task, load = tasks['policies'][policy], loads['loads'][policy]
        assert task['samples'] == resource['samples']
        assert sum(task['deadline_miss_counts'].values()) == resource['samples']
        assert task['samples'] == sum(runtime['policies'][policy]['statuses'].values())
        state = dict(samples=task['samples'], deadline_miss_counts=task['deadline_miss_counts'],
                     statuses=runtime['policies'][policy]['statuses'],
                     start_report_batches=load['start_batches'], end_report_batches=load['end_batches'],
                     final_reported_batches=load['final_reported_batches'])
        if enabled:
            proof = fence['policies'][policy]
            assert proof == load['fenced_throughput']
            assert proof['interval_batches'] > 0 and proof['elapsed_ns'] > 0
            state['fenced_throughput'] = proof
        else:
            assert load['start_batches'] < load['end_batches']
            assert 'fenced_throughput' not in load
        states[policy] = state
    cohorts[name] = dict(fences=enabled, period_us=resource['period_us'], rounds=resource['task_rounds'],
                         irq_pressure=resource['irq_pressure'], trace_records=runtime['records'],
                         dropped=0, incomplete=0, policies=states,
                         raw_log_sha256=digest(raw), provenance_sha256=digest(config/'provenance.json'),
                         source_archive=identity['source_archive'])

assert cohorts and len(heads) == len(locks) == 1
assert all(sources == source_sets[0] for sources in source_sets)
assert all(digest(repo/p) == value for p, value in source_sets[0].items())
assert digest(repo/'Cargo.lock') in locks
native = json.loads((archive/'results/throughput-native-v1/result.json').read_text())
assert native['source_sha256'] == source_sets[0]['virtualization/axvm/tests/guests/linux-load/workload.c']
assert len(native['cases']) == 6
assert all(any(record.get('rejected') for record in case['records'])
           for case in native['cases'] if case['name'] in ('duplicate', 'end-first'))
final_analysis = archive/'configs/throughput-final-analysis.tar.gz'
analysis_hashes = {str(p.relative_to(repo)): digest(p)
                   for p in sorted((repo/'virtualization/axvm/tests/analysis').glob('*.py'))}
with tarfile.open(final_analysis) as snapshot:
    assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == value
               for p, value in analysis_hashes.items())
legacy = {}
for name in ('periodic-backlog-32', 'periodic-normal-32', 'periodic-disabled-128', 'periodic-ab-backlog-32'):
    output = archive/'results'/name
    task = json.loads((output/'task/summary.json').read_text())
    runtime = json.loads((output/'runtime/summary.json').read_text())
    assert task['linux_fences']['mode'] == 'off_legacy'
    assert runtime['dropped'] == runtime['incomplete'] == 0
    legacy[name] = dict(raw_log_sha256=digest(archive/'raw'/(name+'.log')),
                       task_summary_sha256=digest(output/'task/summary.json'),
                       trace_records=runtime['records'],
                       samples={p: v['samples'] for p, v in task['policies'].items()})
report = dict(scope='QEMU functional causal Linux throughput; no hardware performance conclusion',
              cohorts=cohorts, failed_attempts=failures, captured_sources_equal=True,
              live_source_matches_captures=True, common_git_commit=next(iter(heads)),
              common_cargo_lock_sha256=next(iter(locks)), M1_complete=False, M2_complete=False,
              native_source_matches_captures=True,
              final_analysis_archive='configs/throughput-final-analysis.tar.gz',
              final_analysis_archive_sha256=digest(final_analysis),
              final_analysis_sha256=analysis_hashes, legacy_periodic_replay=legacy,
              empirical_interaction_measured=False,
              remaining=['Externally timed arrivals and production path decomposition',
                         'Diagnose critical IRQ timeout in the fenced A+B backlog attempt',
                         'Equal-workload probe and handshake overhead',
                         'True-board IRQ/memory/frequency/temperature/counter validation',
                         'Repeated randomized four-cell experiments with interaction uncertainty'])
(archive/'results/throughput-functional-audit.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(dict(cohorts=list(cohorts), failed_attempts=failures), indent=2))
