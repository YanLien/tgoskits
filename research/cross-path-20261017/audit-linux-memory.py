#!/usr/bin/env python3
"""Summarize completed functional cohorts without inferring interference."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib

archive = Path(__file__).resolve().parent
repo = archive.parent.parent
cohorts, provenance = {}, {}
for name in sys.argv[1:]:
    config = archive/'configs'/name
    result = archive/'results'/name
    log = (archive/'raw'/(name+'.log')).read_text()
    identity = json.loads((config/'provenance.json').read_text())
    assert identity['exit_code'] == 0 and 'AXTEST_SUITE_OK' in log
    kernel = re.findall(r'cargo build elf=(\S+)', log)[-1] + '.bin'
    kernel = str(Path(kernel).relative_to(repo))
    initrd = 'target/axbuild/axvisor/host-initramfs/aarch64.cpio'
    assert kernel in identity['artifact_sha256'] and initrd in identity['artifact_sha256']
    runtime = json.loads((result/'runtime/summary.json').read_text())
    load = json.loads((result/'load/summary.json').read_text())
    task = json.loads((result/'task/summary.json').read_text())
    assert runtime['dropped'] == runtime['incomplete'] == 0
    assert task['task_wait_mode'] == 'blocked'
    assert all(row['samples'] == 128 for row in task['policies'].values())
    cohorts[name] = dict(trace_records=runtime['records'], dropped=0, incomplete=0,
        selected_host_kernel=kernel, selected_host_kernel_sha256=identity['artifact_sha256'][kernel],
        selected_host_initrd=initrd, selected_host_initrd_sha256=identity['artifact_sha256'][initrd],
        provenance_sha256=hashlib.sha256((config/'provenance.json').read_bytes()).hexdigest(),
        policies={policy: dict(samples=state['samples'],
            full_chain_samples=runtime['policies'][policy]['full_chain_samples'],
            statuses=runtime['policies'][policy]['statuses'],
            task_deadline_miss_counts=state['deadline_miss_counts'])
            for policy, state in task['policies'].items()},
        non_target_vcpu_returns=task['non_target_vcpu_returns'], loads=load['loads'])
    provenance[name] = identity
matching = None
if len(cohorts) == 2:
    first, second = sys.argv[1:]
    left, right = provenance[first], provenance[second]
    assert left['source_sha256'] == right['source_sha256']
    assert left['cargo_lock_sha256'] == right['cargo_lock_sha256']
    a, b = (archive/'configs'/first), (archive/'configs'/second)
    excluded = {'scenario', 'linux_memory_bytes', 'linux_memory_every'}
    def settings(folder):
        return {key: value for key, value in tomllib.loads((folder/'measurement.toml').read_text()).items()
                if key not in excluded}
    assert settings(a) == settings(b)
    assert (a/'zephyr.config').read_bytes() == (b/'zephyr.config').read_bytes()
    assert (a/'realtime-vm.toml').read_bytes() == (b/'realtime-vm.toml').read_bytes()
    avm = tomllib.loads((a/'linux-vm.toml').read_text())
    bvm = tomllib.loads((b/'linux-vm.toml').read_text())
    avm['base'].pop('name')
    bvm['base'].pop('name')
    assert avm == bvm
    matching = dict(source_equal=True, cargo_lock_equal=True, realtime_guest_config_equal=True,
        measurement_settings_equal_except=sorted(excluded), linux_topology_equal=True,
        performance_comparison_valid=False, reason='One functional run per mode; QEMU only, no independent IRQ pressure, no repeated randomized blocks')
report = dict(scope='QEMU functional workload and trace validation', cohorts=cohorts,
    matching=matching, M1_complete=False, M2_complete=False, empirical_interaction_measured=False,
    remaining=['Periodic release and backlog', 'Production IRQ/timer decomposition',
        'Equal-workload probe overhead', 'Independent noncritical IRQ pressure A',
        'True-board memory pressure, frequency/temperature/counter audit',
        'Repeated randomized 2x2 experiments with ordinary-VM throughput and uncertainty'])
(archive/'results/linux-memory-functional-audit.json').write_text(json.dumps(report, indent=2)+'\n')
print(f'verified {len(cohorts)} completed functional cohorts; M1/M2 remain incomplete')
