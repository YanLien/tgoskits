#!/usr/bin/env python3
"""Audit fixed workload identities and summarize independent paired board boots."""
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
import tarfile
import tomllib

archive = Path(__file__).resolve().parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads((archive/p).read_text())
plan = read('configs/recorder-cost-pair-plan.json')
state = read('results/recorder-cost-pair-status.json')
assert state['terminal'] and state['success'] and len(state['completed']) == 8
assert [r['name'] for r in state['completed']] == [r['name'] for b in plan['blocks'] for r in b['runs']]
replicates, identities = [], {}
reference_config = reference_environment = reference_artifacts = reference_tools = reference_commit = None
for block in plan['blocks']:
    summaries = {}
    for run in block['runs']:
        name, mode = run['name'], run['mode']
        config = archive/'configs'/name
        identity = read(f'configs/{name}/provenance.json')
        assert identity['runtime'] == 'board' and identity['exit_code'] == 0
        assert all(identity[k] == plan[k] for k in ('source_sha256','host_source_sha256','cargo_lock_sha256'))
        assert identity['raw_log_sha256'] == digest(archive/'raw'/(name+'.log'))
        for kind in ('source','host_source'):
            source_archive = archive/identity[kind+'_archive']
            assert digest(source_archive) == identity[kind+'_archive_sha256']
            with tarfile.open(source_archive) as snapshot:
                assert all(hashlib.sha256(snapshot.extractfile(p).read()).hexdigest() == h
                           for p,h in identity[kind+'_sha256'].items())
        fixture = tomllib.loads((config/'measurement.toml').read_text())
        assert fixture.pop('recording') == mode
        environment = [s for s in (config/'environment.txt').read_text().splitlines()
                       if not s.startswith('VIRQ_RECORDING=')]
        artifacts = {p:digest(config/p) for p in ('realtime.elf','realtime.bin','realtime-input.dtb',
            'linux-input.dtb','host-input.dtb','zephyr.config','linux-build.json','realtime-vm.toml','linux-vm.toml')}
        tools = (config/'tool-versions-before-build.txt').read_text().splitlines()[1:]
        if reference_config is None:
            reference_config, reference_environment, reference_artifacts = fixture, environment, artifacts
            reference_tools, reference_commit = tools, identity['git_commit']
        assert fixture == reference_config and environment == reference_environment
        assert artifacts == reference_artifacts, 'a supposedly fixed input changed'
        assert tools == reference_tools and identity['git_commit'] == reference_commit
        linux_build = read(f'configs/{name}/linux-build.json')
        assert linux_build['working_set_bytes'] == 0 and linux_build['fences_enabled']
        assert all(linux_build[k] in identity['artifact_sha256'].values()
                   for k in ('workload_elf_sha256','kernel_sha256','initramfs_sha256'))
        decoded = read(f'results/{name}/analysis-input-provenance.json')
        assert decoded['measurement_bytes_unchanged'] and decoded['decoding_valid_for_analysis']
        assert decoded['raw_sha256'] == identity['raw_log_sha256']
        assert decoded['analysis_input_sha256'] == digest(archive/'results'/name/'analysis-input.log')
        result = read(f'results/{name}/probe_cost/summary.json')
        assert result['recording_mode'] == mode and result['task_observations_valid']
        assert result['source'] == fixture['source'] == 'physical_timer_ppi'
        assert result['periodic']['frequency_hz'] == 24000000
        assert result['complete_chain_accepted'] == (mode == 'on')
        assert result['linux_fences']['mode'] == 'serial'
        assert all(s['samples'] == 32 for s in result['policies'].values())
        log = (archive/'results'/name/'analysis-input.log').read_text()
        platforms = re.findall(r'VIRQ_PLATFORM kind=(\S+) el=(\d+) cpus=(\d+) physical_ppi=(\d+) scheduler_ppi=(\d+) frequency_hz=(\d+)',log)
        assert platforms == [('orangepi5plus_rk3588','2','4','30','26','24000000')]
        envelopes = [tuple(map(int,r)) for r in re.findall(r'VIRQ_TRACE_ENVELOPE sample=(\d+) ticks=(\d+) frequency_hz=(\d+)',log)]
        assert [n for n,_,_ in envelopes] == list(range(1,129))
        assert all(hz == result['periodic']['frequency_hz'] for _,_,hz in envelopes)
        result['marker_envelope_mean_ns'] = statistics.mean(t*1e9/hz for _,t,hz in envelopes)
        if mode == 'on':
            trace = read(f'results/{name}/runtime/summary.json')
            assert trace['dropped'] == trace['incomplete'] == 0
        summaries[mode] = result
        identities[name] = dict(provenance_sha256=digest(config/'provenance.json'),
                                raw_log_sha256=identity['raw_log_sha256'],
                                trace_records=trace['records'] if mode == 'on' else None,
                                full_chain_available=mode == 'on')
    for policy in ('fair','fifo80'):
        on, off = (summaries[m]['policies'][policy] for m in ('on','off'))
        low = on['release_to_completion_lower_ns']['mean']-off['release_to_completion_upper_ns']['mean']
        high = on['release_to_completion_upper_ns']['mean']-off['release_to_completion_lower_ns']['mean']
        execution = on['task_execution_ns']['mean']-off['task_execution_ns']['mean']
        rate_on, rate_off = (summaries[m]['linux_fences']['policies'][policy]['iterations_per_second']
                            for m in ('on','off'))
        replicates.append(dict(block=block['block'],policy=policy,order='/'.join(block['order']),
            latency_difference_lower_ns=low,latency_difference_upper_ns=high,
            execution_difference_ns=execution,linux_iterations_per_second_difference=rate_on-rate_off,
            linux_rate_change_percent=(rate_on/rate_off-1)*100,
            marker_envelope_on_minus_off_mean_ns=summaries['on']['marker_envelope_mean_ns']-summaries['off']['marker_envelope_mean_ns'],
            on_dmr_lower=on['deadline_miss_ratio_lower'],on_dmr_upper=on['deadline_miss_ratio_upper'],
            off_dmr_lower=off['deadline_miss_ratio_lower'],off_dmr_upper=off['deadline_miss_ratio_upper']))

policies = {}
for policy in ('fair','fifo80'):
    rows = [r for r in replicates if r['policy'] == policy]
    rng = random.Random(plan['seed']+1)
    draws = [[rows[rng.randrange(len(rows))] for _ in rows] for _ in range(10000)]
    low_draws = sorted(statistics.mean(r['latency_difference_lower_ns'] for r in draw) for draw in draws)
    high_draws = sorted(statistics.mean(r['latency_difference_upper_ns'] for r in draw) for draw in draws)
    policies[policy] = dict(independent_pairs=len(rows),
        latency_on_minus_off_mean_lower_ns=statistics.mean(r['latency_difference_lower_ns'] for r in rows),
        latency_on_minus_off_mean_upper_ns=statistics.mean(r['latency_difference_upper_ns'] for r in rows),
        exploratory_paired_bootstrap_95_lower_ns=low_draws[math.ceil(.025*len(draws))-1],
        exploratory_paired_bootstrap_95_upper_ns=high_draws[math.ceil(.975*len(draws))-1],
        task_execution_on_minus_off_mean_ns=statistics.mean(r['execution_difference_ns'] for r in rows),
        marker_envelope_on_minus_off_mean_ns=statistics.mean(r['marker_envelope_on_minus_off_mean_ns'] for r in rows),
        linux_rate_change_percent=statistics.mean(r['linux_rate_change_percent'] for r in rows),
        observed_dmr_clock_bounds={m:[statistics.mean(r[f'{m}_dmr_{side}'] for r in rows)
                                     for side in ('lower','upper')] for m in ('on','off')},
        linux_iterations_per_second_on_minus_off_mean=statistics.mean(r['linux_iterations_per_second_difference'] for r in rows))
report = dict(scope='Exploratory board recorder-enabled-path increment; not all probe costs or a causal estimate',
    summary_script_sha256=digest(Path(__file__)),
    independent_pairs=4,task_observations=512,full_chain_tasks=256,task_only_observations=256,
    seed=plan['seed'],bootstrap_seed=plan['seed']+1,paired_bootstrap_resamples=10000,
    fixed_fixture=reference_config,fixed_artifact_sha256=reference_artifacts,
    fixed_tool_versions=reference_tools,fixed_git_commit=reference_commit,
    identities=identities,replicates=replicates,policies=policies,M1_complete=False,M2_complete=False,
    limitations=['CPU frequency and temperature were not measured or fixed during these windows.',
        'Per-boot U-Boot/BL31 banners are absent from the standard logs; fixed input DTB/FIT hashes do not prove immutable board firmware.',
        'Balanced randomized order does not eliminate unmeasured frequency/thermal confounding.',
        'Four independent pairs give a limited exploratory bootstrap; coverage is not established.',
        'Fair and FIFO run in a fixed within-boot order; these are separate recorder comparisons, not a randomized policy comparison.',
        'The uncertainty envelope resamples whole pairs and retains counter-offset bounds, not individual events.',
        'Disabled recording supplies no observed Host IRQ entry, vCPU residency, or scheduler-stage trace.',
        'Residual compiled hooks, clock reads, mailbox polling, Guest timestamps and Linux fences remain in both modes.',
        'Marker envelopes include timestamp reads and may include preemption; they are auxiliary component observations, not pure instruction costs.',
        'Differences may be negative; no positive recorder cost or optimization benefit is presumed.'])
(archive/'results/recorder-cost-paired-summary.json').write_text(json.dumps(report,indent=2)+'\n')
with (archive/'results/recorder-cost-paired-replicates.csv').open('w',newline='') as stream:
    writer = csv.DictWriter(stream,fieldnames=list(replicates[0]))
    writer.writeheader()
    writer.writerows(replicates)
print(json.dumps(dict(independent_pairs=4,task_observations=512,policies=policies,M1_complete=False),indent=2))
