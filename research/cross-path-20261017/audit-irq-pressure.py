#!/usr/bin/env python3
"""Audit completed SGI-on/off functional cohorts; do not infer coupling."""
import csv
import hashlib
import json
from pathlib import Path
import sys
import tomllib

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
sys.path.insert(0, str(repo/'virtualization/axvm/tests/analysis'))
from analyze_virq_irq_pressure import validate_pressure, verify_window

cohorts, identities = {}, []
for name in sys.argv[1:]:
    config = archive/'configs'/name
    result = archive/'results'/name
    raw = (archive/'raw'/(name+'.log')).read_text()
    identity = json.loads((config/'provenance.json').read_text())
    assert identity['exit_code'] == 0 and 'AXTEST_SUITE_OK' in raw
    pressure = validate_pressure(raw)
    runtime = json.loads((result/'runtime/summary.json').read_text())
    task = json.loads((result/'task/summary.json').read_text())
    assert runtime['dropped'] == runtime['incomplete'] == 0 and task['task_wait_mode'] == 'blocked'
    with (result/'task/samples.csv').open() as stream:
        samples = list(csv.DictReader(stream))
    policies = {}
    for policy in ('fair', 'fifo80'):
        group = [row for row in samples if row['policy'] == policy]
        assert len(group) == 128
        for row in group:
            verify_window(pressure, policy, int(row['submit_ticks']),
                          int(row['host_task_observed_ticks']), int(row['frequency_hz']))
        info = dict(samples=len(group), full_chain_samples=runtime['policies'][policy]['full_chain_samples'],
                    statuses=runtime['policies'][policy]['statuses'],
                    deadline_miss_counts=task['policies'][policy]['deadline_miss_counts'])
        if pressure['mode'] == 'sgi':
            state = pressure['policies'][policy]
            count = state['end_count']-state['start_count']
            overlap = sum(any(max(e['handler_start_ticks'], int(row['submit_ticks']))
                              < min(e['handler_end_ticks'], int(row['host_task_observed_ticks']))
                              for e in state['events']) for row in group)
            info.update(sgi_sent=state['sent'], sgi_handled=state['handled'],
                window_callbacks=count,
                observed_callbacks_per_second=count*pressure['frequency_hz']/(state['window_end_ticks']-state['window_start_ticks']),
                skipped_periods=state['skipped_periods'], positive_callback_overlap_samples=overlap,
                no_positive_callback_overlap_samples=len(group)-overlap,
                joined=state['joined'], retired=state['retired'])
        policies[policy] = info
    cohorts[name] = dict(mode=pressure['mode'], trace_records=runtime['records'], dropped=0,
        incomplete=0, policies=policies, non_target_vcpu_returns=task['non_target_vcpu_returns'],
        provenance_sha256=hashlib.sha256((config/'provenance.json').read_bytes()).hexdigest())
    identities.append(identity)

matching = None
if len(identities) == 2:
    first, second = sys.argv[1:]
    assert identities[0]['source_sha256'] == identities[1]['source_sha256']
    assert identities[0]['cargo_lock_sha256'] == identities[1]['cargo_lock_sha256']
    a, b = archive/'configs'/first, archive/'configs'/second
    left = tomllib.loads((a/'measurement.toml').read_text())
    right = tomllib.loads((b/'measurement.toml').read_text())
    assert left.pop('irq_pressure') != right.pop('irq_pressure') and left == right
    assert (a/'realtime-vm.toml').read_bytes() == (b/'realtime-vm.toml').read_bytes()
    assert (a/'linux-vm.toml').read_bytes() == (b/'linux-vm.toml').read_bytes()
    assert (a/'zephyr.config').read_bytes() == (b/'zephyr.config').read_bytes()
    for path, expected in identities[0]['source_sha256'].items():
        if '/analysis/' not in path:
            assert hashlib.sha256((repo/path).read_bytes()).hexdigest() == expected, path
    matching = dict(captured_source_equal=True, live_compiled_source_matches_capture=True,
        cargo_lock_equal=True, guest_configs_equal=True, measurement_diff_only='irq_pressure',
        performance_comparison_valid=False)
analysis = repo/'virtualization/axvm/tests/analysis'
report = dict(scope='QEMU functional SGI and memory source assembly; not a repeated 2x2 experiment',
    cohorts=cohorts, matching=matching,
    final_analysis_sha256={str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(analysis.glob('*.py'))},
    analysis_archive='configs/irq-pressure-final-analysis.tar.gz',
    M1_complete=False, M2_complete=False, empirical_interaction_measured=False,
    limitations=['SGI is a synthetic physical GIC load, not Linux device/DMA IRQ evidence',
        'Handler body endpoints exclude pre-IAR delivery and post-publication controller completion',
        'Overlap is a temporal observation, not causality; zero overlap does not exclude interference',
        'CPU2 generator activity is part of A; actual rates may differ from the requested rate',
        'Periodic releases/backlog, equal-workload tracing cost and exact ordinary-VM throughput remain incomplete',
        'True-board frequency/temperature/counter audit and repeated randomized four-cell data remain incomplete'])
(archive/'results/irq-pressure-functional-audit.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(dict(cohorts=cohorts, matching=matching), indent=2))
