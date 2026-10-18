#!/usr/bin/env python3
"""Summarize the preregistered eight pairs only after every run is accepted."""
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics
import tarfile
import tomllib

from recorder_ops_statistics import paired_endpoints

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads((archive/p).read_text())
plan = read('configs/recorder-ops-plan.json')
state = read('results/recorder-ops-status.json')
expected = plan['pilots']+[r for b in plan['blocks'] for r in b['runs']]
assert state['terminal'] and state['success'] and len(state['completed']) == 18
assert [r['name'] for r in state['completed']] == [r['name'] for r in expected]
assert all(digest(repo/p) == h for p, h in plan['source_sha256'].items())
assert all(digest(repo/p) == h for p, h in plan['control_sha256'].items())
assert plan['independent_pairs'] == len(plan['blocks']) == 8
replicates, identities, observations, environment_rows = [], {}, {}, []
native_reference = None
for block in plan['blocks']:
    summaries = {}
    for run in block['runs']:
        name, mode = run['name'], run['mode']
        folder = archive/'configs'/name
        identity = read(f'configs/{name}/provenance.json')
        assert identity['runtime'] == 'board' and identity['exit_code'] == 0
        assert identity['raw_log_sha256'] == digest(archive/'raw'/(name+'.log'))
        driver = read(f'configs/{name}/driver-source-provenance.json')
        cpu = read(f'configs/{name}/cpu-source-provenance.json')
        for key, filename, sha_key, metadata in (
            ('source_sha256', 'sources.tar.gz', 'source_archive_sha256', identity),
            ('host_source_sha256', 'host-sources.tar.gz', 'host_source_archive_sha256', identity),
            ('source_sha256', 'driver-sources.tar.gz', 'archive_sha256', driver),
            ('source_sha256', 'cpu-sources.tar.gz', 'archive_sha256', cpu)):
            assert digest(folder/filename) == metadata[sha_key]
            with tarfile.open(folder/filename) as snapshot:
                assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == h for p, h in metadata[key].items())
            assert all(digest(repo/p) == h for p, h in metadata[key].items())
        fixture = tomllib.loads((folder/'measurement.toml').read_text())
        assert fixture.pop('recording') == mode
        artifacts = {p: digest(folder/p) for p in ('realtime.elf', 'realtime.bin', 'realtime-input.dtb', 'linux-input.dtb',
                      'host-input.dtb', 'zephyr.config', 'linux-build.json', 'realtime-vm.toml', 'linux-vm.toml')}
        fixed = dict(fixture=fixture,
            environment=[s for s in (folder/'environment.txt').read_text().splitlines() if not s.startswith('VIRQ_RECORDING=')],
            artifacts=artifacts, tools=(folder/'tool-versions-before-build.txt').read_text().splitlines()[1:],
            git_commit=identity['git_commit'], tracked_diff_sha256=digest(folder/'tracked-worktree-before.patch'),
            status_sha256=digest(folder/'status-before.txt'), tests=identity['source_sha256'], host=identity['host_source_sha256'],
            driver=driver['source_sha256'], cpu=cpu['source_sha256'])
        if native_reference is None:
            native_reference = fixed
        assert fixed == native_reference, 'fixed native workload/source/tool identity changed'
        linux = read(f'configs/{name}/linux-build.json')
        assert linux['working_set_bytes'] == 0 and linux['fences_enabled']
        assert all(linux[k] in identity['artifact_sha256'].values() for k in ('workload_elf_sha256', 'kernel_sha256', 'initramfs_sha256'))
        decoded = read(f'results/{name}/analysis-input-provenance.json')
        input_path = archive/'results'/name/'analysis-input.log'
        assert decoded['measurement_bytes_unchanged'] and decoded['decoding_valid_for_analysis']
        assert decoded['raw_sha256'] == identity['raw_log_sha256'] and decoded['analysis_input_sha256'] == digest(input_path)
        raw, data = (archive/'raw'/(name+'.log')).read_bytes(), input_path.read_bytes()
        assert raw[raw.index(b'VIRQ_MEASUREMENT '):] == data[data.index(b'VIRQ_MEASUREMENT '):]
        result = read(f'results/{name}/probe_cost/summary.json')
        assert result['recording_mode'] == mode and result['comparison_scope'] == 'recorder_operations'
        assert result['recording_declaration_version'] == 2 and result['task_observations_valid']
        assert result['source'] == 'physical_timer_ppi' and result['task_deadline_origin'] == 'scheduled_release'
        assert result['periodic']['frequency_hz'] == 24000000 and result['periodic']['jobs'] == 32
        assert result['complete_chain_accepted'] == (mode == 'on') and result['linux_fences']['mode'] == 'serial'
        assert all(p['samples'] == 32 for p in result['policies'].values())
        log = input_path.read_text()
        assert re.findall(r'VIRQ_PLATFORM kind=(\S+) el=(\d+) cpus=(\d+) physical_ppi=(\d+) scheduler_ppi=(\d+) frequency_hz=(\d+)', log) == [('orangepi5plus_rk3588', '2', '4', '30', '26', '24000000')]
        envelopes = [tuple(map(int, r)) for r in re.findall(r'VIRQ_TRACE_ENVELOPE sample=(\d+) ticks=(\d+) frequency_hz=(\d+)', log)]
        assert [r[0] for r in envelopes] == list(range(1, 129)) and all(r[2] == 24000000 for r in envelopes)
        result['marker_envelope_mean_ns'] = statistics.mean(t*1e9/hz for _, t, hz in envelopes)
        with (archive/'results'/name/'probe_cost/samples.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 64
        for p in ('fair', 'fifo80'):
            observations.setdefault((mode, p), []).extend(r for r in rows if r['policy'] == p)
        if mode == 'on':
            trace = read(f'results/{name}/runtime/summary.json')
            assert trace['dropped'] == trace['incomplete'] == 0
            stage = read(f'results/{name}/stages/summary.json')
            assert stage['samples'] == 64 and stage['dropped'] == stage['incomplete'] == 0
            trace_records = trace['records']
        else:
            assert all(r['trace_loss'] == '' and r['irq_entry_to_completion_lower_ns'] == '' for r in rows)
            for kind, message in (('task', 'disabled recorder cannot establish a complete runtime chain'),
                                  ('stages', 'disabled recorder has no IRQ stage observations')):
                assert message in (archive/'results'/name/f'complete-{kind}-rejection.log').read_text()
            trace_records = None
        thermal = read(f'results/{name}/thermal/summary.json')
        frequency = read(f'results/{name}/frequency/summary.json')
        counter = read(f'results/{name}/counter/summary.json')
        assert all(r['observations_available'] for r in (thermal, frequency, counter))
        assert all(r['recording_mode'] == mode for r in (thermal, frequency, counter))
        assert frequency['window_frequency_hz'] is None and not frequency['continuous_coverage']
        assert not counter['effective_resolution_verified'] and not counter['physical_frequency_error_bounds_verified']
        assert counter['series'] == 48 and counter['raw_reads'] == 12288
        with (archive/'results'/name/'thermal/samples.csv').open() as stream:
            temperatures = list(csv.DictReader(stream))
        with (archive/'results'/name/'frequency/samples.csv').open() as stream:
            frequencies = list(csv.DictReader(stream))
        assert len(temperatures) == 4 and len(frequencies) == 16
        nominal_hz = [(int(r['c1'])-int(r['c0']))*int(r['counter_hz'])/((int(r['t3'])-int(r['t0'])+int(r['t2'])-int(r['t1']))/2) for r in frequencies]
        environment_rows.append(dict(block=block['block'], name=name, mode=mode,
            soc_snapshot_min_mc=min(int(r['soc_mc']) for r in temperatures), soc_snapshot_max_mc=max(int(r['soc_mc']) for r in temperatures),
            little_snapshot_min_mc=min(int(r['little_mc']) for r in temperatures), little_snapshot_max_mc=max(int(r['little_mc']) for r in temperatures),
            nominal_frequency_snapshot_min_hz=min(nominal_hz), nominal_frequency_snapshot_max_hz=max(nominal_hz),
            physical_observed_gcd_ticks=counter['by_mode']['physical']['gcd_of_positive_differences'],
            snapshot_scope='quiescent only; not window extrema or guaranteed frequency error bounds'))
        summaries[mode] = result
        identities[name] = dict(raw_sha256=identity['raw_log_sha256'], provenance_sha256=digest(folder/'provenance.json'),
                                trace_records=trace_records, complete_chain=mode == 'on', runtime_loss_known=mode == 'on')
    for policy in ('fair', 'fifo80'):
        on, off = (summaries[m]['policies'][policy] for m in ('on', 'off'))
        rate_on, rate_off = (summaries[m]['linux_fences']['policies'][policy]['iterations_per_second'] for m in ('on', 'off'))
        replicates.append(dict(block=block['block'], policy=policy, order='/'.join(block['order']),
            latency_difference_lower_ns=on['release_to_completion_lower_ns']['mean']-off['release_to_completion_upper_ns']['mean'],
            latency_difference_upper_ns=on['release_to_completion_upper_ns']['mean']-off['release_to_completion_lower_ns']['mean'],
            execution_difference_ns=on['task_execution_ns']['mean']-off['task_execution_ns']['mean'],
            linux_rate_change_percent=(rate_on/rate_off-1)*100,
            linux_iterations_per_second_difference=rate_on-rate_off,
            marker_envelope_on_minus_off_mean_ns=summaries['on']['marker_envelope_mean_ns']-summaries['off']['marker_envelope_mean_ns'],
            on_dmr_lower=on['deadline_miss_ratio_lower'], on_dmr_upper=on['deadline_miss_ratio_upper'],
            off_dmr_lower=off['deadline_miss_ratio_lower'], off_dmr_upper=off['deadline_miss_ratio_upper']))


def nearest_rank(values, fraction):
    import math
    return sorted(values)[math.ceil(fraction*len(values))-1]


policies = {}
for policy in ('fair', 'fifo80'):
    rows = [r for r in replicates if r['policy'] == policy]
    assert [r['block'] for r in rows] == list(range(1, 9))
    summary = paired_endpoints(rows, plan['statistics']['bootstrap_seed'], plan['statistics']['resamples'])
    summary.update(task_execution_on_minus_off_mean_ns=statistics.mean(r['execution_difference_ns'] for r in rows),
        linux_rate_change_percent=statistics.mean(r['linux_rate_change_percent'] for r in rows),
        linux_iterations_per_second_on_minus_off_mean=statistics.mean(r['linux_iterations_per_second_difference'] for r in rows),
        marker_envelope_on_minus_off_mean_ns=statistics.mean(r['marker_envelope_on_minus_off_mean_ns'] for r in rows),
        observed_dmr_clock_bounds={m: [statistics.mean(r[f'{m}_dmr_{side}'] for r in rows) for side in ('lower', 'upper')] for m in ('on', 'off')})
    summary['descriptive_tails'] = {}
    for mode in ('on', 'off'):
        group = observations[mode, policy]
        assert len(group) == 256
        lower = [float(r['release_to_completion_lower_ns']) for r in group]
        upper = [float(r['release_to_completion_upper_ns']) for r in group]
        summary['descriptive_tails'][mode] = dict(tasks=256,
            p99_nominal_ns=[nearest_rank(lower, .99), nearest_rank(upper, .99)],
            p999_nominal_ns=[nearest_rank(lower, .999), nearest_rank(upper, .999)],
            maximum_observed_nominal_ns=[max(lower), max(upper)], p999_is_maximum_order_statistic=True)
    policies[policy] = summary
report = dict(scope='Current recorder operations on-minus-off; nominal counter scale and retained offset bounds',
    independent_pairs=8, native_boots=16, task_observations=1024, recorded_task_observations=512, task_only_observations=512,
    seed=plan['seed'], statistics=plan['statistics'], primary_metric=plan['primary_metric'],
    policies=policies, replicates=replicates, environment=environment_rows, identities=identities,
    fixed_inputs=native_reference, summary_script_sha256=digest(Path(__file__)), statistics_script_sha256=digest(archive/'recorder_ops_statistics.py'),
    M1=False, M2=False, limitations=plan['limitations']+[
        'Fixed Fair-then-FIFO order: separate recorder comparisons, not a randomized policy comparison.',
        'The empirical percentile envelope retains offset endpoints but does not certify counter update, calibration error or bootstrap coverage.',
        'P99.9 at 256 tasks per policy/mode is the maximum observed order statistic, not a precise extreme-tail estimate or WCET.',
        'Off mode has no observed T0 or scheduler stages; trace_loss remains unknown.',
        'Remaining independent timestamps, admission checks, mailbox/fence observation and compiled hooks are not wholly isolated.',
        'Marker envelopes are auxiliary observations with timing and possible preemption, not pure instruction costs.',
        'Balanced order mitigates some trends but does not eliminate unmeasured environmental or carryover effects.',
        'A negative contrast is retained; no positive overhead, coupling or optimization benefit is presumed.'])
(archive/'results/recorder-ops-paired-summary.json').write_text(json.dumps(report, indent=2)+'\n')
for filename, rows in (('recorder-ops-paired-replicates.csv', replicates), ('recorder-ops-environment.csv', environment_rows)):
    with (archive/'results'/filename).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
print(json.dumps(dict(independent_pairs=8, native_boots=16, tasks=1024, policies=policies, M1=False, M2=False), indent=2))
