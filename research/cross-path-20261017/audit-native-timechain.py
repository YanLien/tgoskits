#!/usr/bin/env python3
"""Audit completed CNTP dual-VM runs; never infer hardware performance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('names', nargs='+')
parser.add_argument('--failed', nargs='*', default=[])
args = parser.parse_args()
archive = Path(__file__).resolve().parent
repo = archive.parent.parent
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
reports = {}
failures = {}
for name in args.names:
    config = archive/'configs'/name
    output = archive/'results'/name
    identity = json.loads((config/'provenance.json').read_text())
    assert identity['exit_code'] == 0
    log = (archive/'raw'/(name+'.log')).read_bytes().decode('utf-8', errors='replace')
    assert 'AXTEST_SUITE_OK' in log and 'AXTEST_SUITE_FAIL' not in log
    assert 'VIRQ_GUEST_FIRMWARE source=explicit_dtb' in log
    platform = re.findall(r'VIRQ_PLATFORM kind=(\S+) el=(\d+) cpus=(\d+) '
                          r'physical_ppi=(\d+) scheduler_ppi=(\d+) frequency_hz=(\d+)', log)
    assert len(platform) == 1
    kind, el, cpus, source, scheduler, frequency = platform[0]
    assert (el, cpus, source, scheduler) == ('2', '4', '30', '26')
    assert kind == ('qemu_virt' if identity['runtime'] == 'qemu' else 'orangepi5plus_rk3588')
    frequency = int(frequency)
    clocks = re.findall(r'SOFTWARE VIRQ CLOCK timer_hz=(\d+) counter_hz=(\d+)', log)
    assert clocks and all(int(a) == int(b) == frequency for a, b in clocks)
    irq = re.findall(r'VIRQ_PHYSICAL_SUMMARY policy=(\S+) intid=30 cpu=0 handled=32 errors=0 retired=1', log)
    assert sorted(irq) == ['fair', 'fifo80']
    assert digest(archive/identity['source_archive']) == identity['source_archive_sha256']
    with tarfile.open(archive/identity['source_archive']) as snapshot:
        for path, checksum in identity['source_sha256'].items():
            assert hashlib.sha256(snapshot.extractfile(path).read()).hexdigest() == checksum
    if 'host_source_archive' in identity:
        host_archive = archive/identity['host_source_archive']
        assert digest(host_archive) == identity['host_source_archive_sha256']
        with tarfile.open(host_archive) as snapshot:
            for path, checksum in identity['host_source_sha256'].items():
                assert hashlib.sha256(snapshot.extractfile(path).read()).hexdigest() == checksum
        if name.startswith('native-private-ram-'):
            fix = json.loads((archive/'results/private-ram-patch-audit.json').read_text())
            assert identity['host_source_sha256'][fix['source']] == fix['after_sha256']
    input_provenance = output/'analysis-input-provenance.json'
    if input_provenance.is_file():
        decoded = json.loads(input_provenance.read_text())
        assert decoded['measurement_bytes_unchanged'] and decoded['decoding_valid_for_analysis']
        assert decoded['raw_sha256'] == digest(archive/'raw'/(name+'.log'))
        assert decoded['analysis_input_sha256'] == digest(output/'analysis-input.log')
    summaries = {k: json.loads((output/k/'summary.json').read_text())
                 for k in ('physical', 'runtime', 'ready', 'isr', 'load', 'task', 'irq_service',
                           'irq_pressure', 'periodic')}
    runtime = summaries['runtime']
    assert runtime['dropped'] == runtime['incomplete'] == 0
    physical, task = summaries['physical'], summaries['task']
    assert physical['source'] == 'physical_timer_ppi'
    assert task['task_rounds'] == 4096 and task['task_wait_mode'] == 'blocked'
    assert task['task_deadline_origin'] == 'scheduled_release'
    assert summaries['periodic']['period_ns'] == 20000000
    assert summaries['periodic']['jobs'] == 32
    assert task['linux_fences']['mode'] == 'serial'
    policies = {}
    for policy in ('fair', 'fifo80'):
        p, t = physical['policies'][policy], task['policies'][policy]
        assert p['samples'] == t['samples'] == 32
        assert p['clock']['frequency_hz'] == frequency and not p['clock']['trace_loss']
        fence = task['linux_fences']['policies'][policy]
        assert fence['stopped'] and fence['interval_batches'] > 0 and fence['elapsed_ns'] > 0
        policies[policy] = dict(samples=t['samples'], deadline_miss_counts=t['deadline_miss_counts'],
                                clock_offset_width_ns=p['clock']['offset_width_ns'],
                                linux_interval_batches=fence['interval_batches'],
                                linux_elapsed_ns=fence['elapsed_ns'])
    frozen = ['realtime-input.dtb', 'linux-input.dtb']
    if identity['runtime'] == 'board':
        frozen += ['host-input.dtb', 'host-boot.fit']
    artifacts = {p: digest(config/p) for p in frozen}
    assert all(checksum in identity['artifact_sha256'].values() for checksum in artifacts.values())
    reports[name] = dict(runtime=identity['runtime'], platform=kind, frequency_hz=frequency,
                         trace_records=runtime['records'], dropped=0, incomplete=0,
                         policies=policies, frozen_artifacts_sha256=artifacts,
                         provenance_sha256=digest(config/'provenance.json'),
                         source_archive_sha256=identity['source_archive_sha256'],
                         host_source_archive_sha256=identity.get('host_source_archive_sha256'),
                         independent_analysis_passed=True)
for name in args.failed:
    config = archive/'configs'/name
    identity = json.loads((config/'provenance.json').read_text())
    assert identity['exit_code'] != 0
    raw = (archive/'raw'/(name+'.log')).read_bytes()
    log = raw.decode('utf-8', errors='replace')
    assert 'AXTEST_SUITE_OK' not in log
    if 'raw_log_sha256' in identity:
        assert identity['raw_log_sha256'] == hashlib.sha256(raw).hexdigest()
    if 'host_source_archive' in identity:
        host_archive = archive/identity['host_source_archive']
        assert digest(host_archive) == identity['host_source_archive_sha256']
        with tarfile.open(host_archive) as snapshot:
            for path, checksum in identity['host_source_sha256'].items():
                assert hashlib.sha256(snapshot.extractfile(path).read()).hexdigest() == checksum
    assert digest(archive/identity['source_archive']) == identity['source_archive_sha256']
    with tarfile.open(archive/identity['source_archive']) as snapshot:
        for path, checksum in identity['source_sha256'].items():
            assert hashlib.sha256(snapshot.extractfile(path).read()).hexdigest() == checksum
    failures[name] = dict(runtime=identity['runtime'], exit_code=identity['exit_code'], accepted=False,
                         raw_log_sha256=hashlib.sha256(raw).hexdigest(),
                         utf8_replacement_characters=log.count('\ufffd'),
                         source_archive_sha256=identity['source_archive_sha256'],
                         host_source_archive_sha256=identity.get('host_source_archive_sha256'),
                         provenance_sha256=digest(config/'provenance.json'))
report = dict(scope='Functional CNTP dual-VM evidence only; no performance factorial or coupling claim',
              runs=reports, rejected_runs=failures, M1_complete=False, M2_complete=False,
              rejected_diagnostic_suite_passes='results/reset-observations-audit.json',
              limitations=['Host scheduled logical releases are not external hardware arrivals.',
                           'Probe cost, fixed frequency/temperature, PMU attribution and repeated randomized 2x2 remain incomplete.',
                           'Earlier delivery timeout remains unexplained; a successful run is not a repair proof.',
                           'Legacy analyzers retain QEMU wording; actual runtime identity is verified here from platform and frozen artifacts.'])
(archive/'results/native-timechain-audit.json').write_text(json.dumps(report, indent=2)+'\n')
print('NATIVE_TIMECHAIN_AUDIT_OK', ','.join(reports))
