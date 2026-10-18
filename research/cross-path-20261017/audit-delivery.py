#!/usr/bin/env python3
"""Keep matched delivery controls and actual failure snapshots distinct from effects."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tomllib

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
cohorts, sources, settings, heads, locks = {}, [], [], set(), set()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique(log, marker, pattern):
    lines = [line.strip() for line in log.splitlines() if line.startswith(marker)]
    if not lines:
        return None
    assert len(lines) == 1, (marker, len(lines))
    match = re.fullmatch(pattern, lines[0])
    assert match, lines[0]
    return match.groups()


for name in sys.argv[1:]:
    config, output = archive/'configs'/name, archive/'results'/name
    identity = json.loads((config/'provenance.json').read_text())
    snapshot = archive/identity['source_archive']
    assert digest(snapshot) == identity['source_archive_sha256']
    with tarfile.open(snapshot) as frozen:
        assert all(hashlib.sha256(frozen.extractfile(p).read()).hexdigest() == value
                   for p, value in identity['source_sha256'].items())
    sources.append(identity['source_sha256'])
    heads.add(identity['git_commit'])
    locks.add(identity['cargo_lock_sha256'])
    resource = tomllib.loads((config/'measurement.toml').read_text())
    assert resource['period_us'] == 250 and resource['task_rounds'] == 1048576 and resource['samples'] == 32
    assert resource['linux_memory_bytes'] == 16777216 and resource['linux_memory_every'] == 1
    assert resource['irq_pressure_period_us'] == 2000 and resource['irq_pressure_burst'] == 2
    settings.append({k: v for k, v in resource.items() if k not in ('irq_pressure', 'linux_fences_enabled')})
    linux = json.loads((config/'linux-build.json').read_text())
    assert linux['fences_enabled'] == resource['linux_fences_enabled']
    assert linux['working_set_bytes'] == 16777216 and linux['memory_every_batches'] == 1
    raw = archive/'raw'/(name+'.log')
    log = raw.read_text()
    info = dict(exit_code=identity['exit_code'], irq_pressure=resource['irq_pressure'],
                fences=resource['linux_fences_enabled'], raw_sha256=digest(raw),
                provenance_sha256=digest(config/'provenance.json'),
                source_archive=identity['source_archive'], accepted=identity['exit_code'] == 0)
    failure = unique(log, 'VIRQ_DELIVERY_FAILURE ',
        r'VIRQ_DELIVERY_FAILURE policy=(fair|fifo80) expected_sample=(\d+) submitted_ticks=(\d+) failed_ticks=(\d+) frequency_hz=(\d+) guest_header=Ok\(\[(\d+), (\d+), (\d+), (\d+), (\d+)\]\) guest_task_publication=Some\(Ok\((\d+)\)\) vm_state=Running running_vcpus=(\d+)')
    if failure:
        policy, *numbers = failure
        expected, submitted, failed, hz, ready0, ready1, received, returns, error, task, running = map(int, numbers)
        assert 1 <= expected <= 32 and 0 < submitted < failed and hz > 0
        counts = unique(log, 'VIRQ_RTC_FAILURE_COUNTS ',
            r'VIRQ_RTC_FAILURE_COUNTS handled=(\d+) errors=(\d+) wrong_cpu=(\d+) invalid_alarm=(\d+) pulse_failed=(\d+)')
        device = unique(log, 'VIRQ_RTC_FAILURE_DEVICE ',
            r'VIRQ_RTC_FAILURE_DEVICE present=(1) dr=(\d+) mr=(\d+) imsc=([01]) ris=([01]) mis=([01])')
        framework = unique(log, 'VIRQ_RTC_FAILURE_FRAMEWORK ',
            r'VIRQ_RTC_FAILURE_FRAMEWORK action_enabled=([01]) framework_line_enabled=([01]) in_flight=(\d+) action_running=([01]) hardware_pending=(unknown) hardware_active=(unknown)')
        assert counts and device and framework
        handled, errors, wrong_cpu, invalid_alarm, pulse_failed = map(int, counts)
        info['failure_snapshot'] = dict(policy=policy, expected_sample=expected,
            submitted_ticks=submitted, failed_ticks=failed, frequency_hz=hz,
            guest_header=[ready0, ready1, received, returns, error], guest_task_completed=task & 0xffffffff,
            guest_task_protocol=task >> 32, running_vcpus=running, rtc_handled=handled,
            rtc_errors=errors, wrong_cpu=wrong_cpu, invalid_alarm=invalid_alarm, pulse_failed=pulse_failed,
            classified_counts_match_total=errors == wrong_cpu + invalid_alarm + pulse_failed,
            rtc_device=dict(zip(('present', 'dr', 'mr', 'imsc', 'ris', 'mis'), map(int, device))),
            framework=dict(zip(('action_enabled', 'framework_line_enabled', 'in_flight', 'action_running'), map(int, framework[:4]))),
            hardware_pending=None, hardware_active=None,
            received_relation_to_expected='equal' if received == expected else ('ahead' if received > expected else 'behind'))
    if info['accepted']:
        assert 'AXTEST_SUITE_OK' in log and failure is None and 'VIRQ_RTC_FAILURE_' not in log
        runtime = json.loads((output/'runtime/summary.json').read_text())
        tasks = json.loads((output/'task/summary.json').read_text())
        assert runtime['dropped'] == runtime['incomplete'] == 0
        assert tasks['task_deadline_origin'] == 'scheduled_release'
        assert tasks['linux_fences']['mode'] == ('serial' if info['fences'] else 'off')
        assert tasks['periodic']['jobs'] == 32 and tasks['periodic']['rounds'] == 1048576
        info.update(trace_records=runtime['records'], dropped=0, incomplete=0,
                    policies={p: dict(samples=v['samples'], deadline_miss_counts=v['deadline_miss_counts'],
                                      statuses=runtime['policies'][p]['statuses'],
                                      max_isr_outstanding=tasks['periodic']['policies'][p]['max_isr_outstanding'])
                              for p, v in tasks['policies'].items()})
        assert all(state['samples'] == 32 for state in info['policies'].values())
        assert all(sum(state['statuses'].values()) == 32 for state in info['policies'].values())
    else:
        assert 'AXVM_TEST_FAILED' in log and 'AXTEST_SUITE_OK' not in log
        info['scope'] = 'Rejected attempt; no partial valid-task count or effect estimate'
    cohorts[name] = info

assert cohorts and len(heads) == len(locks) == 1
assert all(item == sources[0] for item in sources)
assert all(item == settings[0] for item in settings)
assert all(digest(repo/p) == value for p, value in sources[0].items())
assert digest(repo/'Cargo.lock') in locks
production_dirty = [p for p in subprocess.check_output(['git', 'diff', '--name-only', 'HEAD'], cwd=repo, text=True).splitlines()
                    if not p.startswith(('research/', 'virtualization/axvm/tests/'))]
untracked_source = [p for p in subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=repo, text=True).splitlines()
                    if not p.startswith(('research/', 'virtualization/axvm/tests/')) and Path(p).suffix in ('.rs', '.c', '.h', '.S', '.toml', '.py', '.sh')]
assert not production_dirty and not untracked_source
report = dict(scope='Matched QEMU functional controls; no hardware or causal performance inference',
              observed_at_utc=datetime.now(timezone.utc).isoformat(),
              cohorts=cohorts, captured_sources_equal=True, live_source_matches_captures=True,
              common_git_commit=next(iter(heads)), common_cargo_lock_sha256=next(iter(locks)),
              settings_equal_except_irq_pressure_and_fences=True,
              production_sources_match_HEAD_at_post_run_audit=True,
              production_audit_scope='After-run check; not falsely described as a before-each-build capture',
              original_failure='throughput-ab-backlog-32', root_cause_identified=False,
              natural_failure_snapshot_observed=any('failure_snapshot' in item for item in cohorts.values()),
              M1_complete=False, M2_complete=False, empirical_interaction_measured=False,
              limitations=['A later successful run does not repair or explain the original failure.',
                           'No hardware pending/active state is inferred from framework fallback values.',
                           'Finite functional controls are not repeated randomized four-cell experiments.'])
(archive/'results/delivery-controls-audit.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
