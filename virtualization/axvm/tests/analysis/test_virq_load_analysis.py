"""Validate workload progress evidence and reject mislabeled measurements."""

import unittest
import re
import importlib.util
import os
from pathlib import Path
import tempfile
import tomllib
from functools import lru_cache
from unittest.mock import patch

from analyze_virq_load import analyze, checksum_after, validate_load
from test_virq_ready_analysis import fixture as ready_fixture


def load_fixture(scenario="cpu_same_core"):
    lines = ["VIRQ_CONTROLLER cpu=0", f"VIRQ_SCENARIO name={scenario}"]
    start = 11 if scenario == "cpu_continuous" else 1
    for thread, policy in enumerate(("fair", "fifo80"), 1):
        for sample in range(1, 301):
            # Include intervals with zero progress; FIFO need not run EEVDF per IRQ.
            before = start + (sample-1)//2
            after = start + sample//2
            lines.append(f"VIRQ_LOAD_SAMPLE policy={policy} sample={sample} before_batches={before} after_batches={after}")
        checksum = checksum_after((start+151)*8192)
        lines.append(f"VIRQ_LOAD_SUMMARY policy={policy} cpu=1 thread={thread} batch_iterations=8192 start_batches={start} end_batches={start+150} final_batches={start+151} wrong_cpu=0 checksum={checksum} joined=1")
        if scenario == "cpu_continuous":
            lines.append(f"VIRQ_LOAD_BOOT_WORK policy={policy} batches=10")
    return "\n".join(lines)+"\n"


def linux_fixture(host_cpu=3, policy_span=1000000, include_isr=True):
    lines = ["VIRQ_CONTROLLER cpu=0", "VIRQ_SCENARIO name=linux_cpu",
             f"VIRQ_LINUX_CONFIG vm=1 vcpu=0 host_cpu={host_cpu} guest_cpu=0 workload=cpu batch_iterations=8192 report_batches=256"]
    sequence = 0
    for thread, policy in enumerate(("fair", "fifo80"), 10):
        origin = (thread - 10) * policy_span
        lines.append("LINUX_LOAD_READY version=1 guest_cpu=0 batch_iterations=8192 report_batches=256")
        for count in (256, 512, 768):
            lines.append(f"LINUX_LOAD_PROGRESS batches={count} checksum={checksum_after(count*8192)} guest_cpu=0")
            if count == 256:
                lines.append(f"VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu={host_cpu} guest_cpu=0 batches=256")
        lines.append(f"VIRQ_LINUX_SUMMARY policy={policy} vm=1 vcpu=0 host_cpu={host_cpu} guest_cpu=0 start_batches=256 end_batches=512 final_batches=768 checksum={checksum_after(768*8192)} reports=3 batch_iterations=8192 report_batches=256 stopped=1")
        for sample in range(1, 301):
            after = 512 if sample == 300 else 256
            lines.append(f"VIRQ_LINUX_SAMPLE policy={policy} sample={sample} before_batches=256 after_batches={after}")
        lines.append("VIRQ_VM_GROUP_RETIRED count=2 empty=1")
        for kind, v0, ticks in (("Running", 0, origin+100), ("Binding", 1, origin+200),
                                ("GuestEntryBoundary", 0, origin+300), ("Stopped", 0, origin+policy_span-1)):
            lines.append(f"VIRQ_RUNTIME cpu={host_cpu} sequence={sequence} ticks={ticks} kind={kind} thread={thread} value0={v0} value1=0")
            sequence += 1
        if include_isr:
            for sample in range(1, 301):
                submitted = origin + policy_span//4 + sample*100
                lines.append(f'VIRQ_ISR_SAMPLE policy={policy} sample={sample} submit_ticks={submitted} guest_ticks={submitted+1} observed_ticks={submitted+2} frequency_hz=1000000000')
    return "\n".join(lines)+"\n"


def pressure_clock_fixture(policy_stride=0, window_duration=2000000):
    lines = ['VIRQ_IRQ_PRESSURE_CONFIG mode=sgi intid=15 sender_cpu=2 target_cpu=0 period_us=100 period_ticks=100000 burst=1 rounds=64 limit=4096 frequency_hz=1000000000']
    for number, policy in enumerate(('fair', 'fifo80')):
        origin = number * policy_stride
        for sequence, due in ((1, 100), (2, 100100)):
            due += origin
            value = sequence
            for _ in range(64):
                value = (value * 6364136223846793005 + 1) % (1 << 64)
            lines.append(f'VIRQ_IRQ_PRESSURE_EVENT policy={policy} sequence={sequence} scheduled_ticks={due} sent_ticks={due+1} handler_start_ticks={due+2} handler_end_ticks={due+3} observed_ticks={due+4} checksum={value} intid=15 sender_cpu=2 target_cpu=0')
        lines.append(f'VIRQ_IRQ_PRESSURE_SUMMARY policy={policy} sent=2 handled=2 errors=0 start_count=1 end_count=2 window_start_ticks={origin+1000} window_end_ticks={origin+window_duration} skipped_periods=0 joined=1 retired=1')
    return '\n'.join(lines) + '\n'


def pressure_measurement(pressure):
    log = ready_fixture()+linux_fixture(include_isr=False)+pressure
    records = sum(line.startswith('VIRQ_RUNTIME ') for line in log.splitlines())
    return re.sub(r'VIRQ_RUNTIME_SUMMARY records=\d+', f'VIRQ_RUNTIME_SUMMARY records={records}', log)


@lru_cache(maxsize=1)
def linux_memory_fixture(policy_span=1000000):
    size, every = 1056768, 3
    values = list(range(size // 8))
    cursor, checksum, accesses = 0, 0, 0
    expected = {}
    for count in (256, 512, 768):
        target = ((count + every - 1) // every) * 8192
        while accesses < target:
            values[cursor] += 1
            checksum = (checksum + values[cursor]) % (1 << 64)
            cursor = (cursor + 1) % len(values)
            accesses += 1
        expected[count] = (accesses // 8192, accesses * 16, checksum)
    lines = []
    for line in linux_fixture(policy_span=policy_span).splitlines():
        line = line.replace('name=linux_cpu', 'name=linux_memory').replace('workload=cpu', 'workload=memory')
        lines.append(line)
        if line.startswith('VIRQ_LINUX_CONFIG '):
            lines.append(f'VIRQ_LINUX_MEMORY_CONFIG working_set_bytes={size} every_batches={every} chunk_words=8192')
        elif line.startswith('LINUX_LOAD_READY '):
            lines.append(f'LINUX_MEMORY_READY version=1 working_set_bytes={size} every_batches={every} chunk_words=8192')
        elif line.startswith('LINUX_LOAD_PROGRESS '):
            count = int(line.split()[1].split('=')[1])
            batches, logical, value = expected[count]
            lines[-1] += f' memory_batches={batches} logical_bytes={logical} memory_checksum={value}'
        elif line.startswith('VIRQ_LINUX_SUMMARY '):
            policy = line.split()[1]
            batches, logical, value = expected[768]
            lines.append(f'VIRQ_LINUX_MEMORY_SUMMARY {policy} working_set_bytes={size} every_batches={every} final_memory_batches={batches} read_bytes={logical//2} write_bytes={logical//2} checksum={value} stopped=1')
    return '\n'.join(lines) + '\n'


class LoadAnalysis(unittest.TestCase):
    def test_linux_topology_preparation_binds_the_host_resource_to_an_admitted_configuration(self):
        path = Path(__file__).resolve().parents[1] / 'guests/virq/prepare.py'
        spec = importlib.util.spec_from_file_location('virq_topology_prepare', path)
        prepare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prepare)
        environment = dict(VIRQ_HOST_LOAD='linux_cpu', VIRQ_SOURCE='physical_timer_ppi',
                           VIRQ_SERVICE_PLACEMENT='cpu0', VIRQ_IRQ_CONTEXT='current_el',
                           VIRQ_TASK='1', VIRQ_TASK_WAIT='blocked', VIRQ_EXPLICIT_DTB='1')
        for host_cpu in (1, 3):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                    **environment, 'VIRQ_LINUX_HOST_CPU': str(host_cpu)}, clear=True):
                fixture = prepare.write_test_resources(Path(directory), 0x40000000, 0x40010000)
                resource = tomllib.loads(fixture.read_text())
                self.assertIn('linux_host_cpu', resource,
                              'the selected Linux Host CPU must be exported to the Host resource')
                self.assertEqual(resource['linux_host_cpu'], host_cpu)
        for changes in ({'VIRQ_LINUX_HOST_CPU': '2'}, {'VIRQ_LINUX_HOST_CPU': '01'},
                        {'VIRQ_LINUX_HOST_CPU': '-1'}, {'VIRQ_LINUX_HOST_CPU': '１'},
                        {'VIRQ_EXPLICIT_DTB': '0'}, {'VIRQ_TASK_WAIT': 'spin'},
                        {'VIRQ_TASK': '0'}, {'VIRQ_HOST_LOAD': 'baseline'}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                with patch.dict(os.environ, {**environment, 'VIRQ_LINUX_HOST_CPU': '1', **changes}, clear=True):
                    with self.assertRaises(ValueError):
                        prepare.write_test_resources(Path(directory), 0x40000000, 0x40010000)

    def test_measured_work_is_joined_to_all_samples_with_zero_progress_windows_retained(self):
        # Independently apply the recurrence to check the fast arithmetic.
        expected = 1
        for _ in range(16384):
            expected = (expected*6364136223846793005+1) % (1 << 64)
        self.assertEqual(checksum_after(16384), expected)
        rows, report = analyze(ready_fixture()+load_fixture())
        self.assertEqual(len(rows), 600)
        self.assertEqual(report["loads"]["fair"]["samples_with_progress"], 150)
        self.assertEqual(rows[0]["load_window_batches"], 0)
        self.assertEqual(rows[1]["load_window_batches"], 1)
        baseline, report = analyze(ready_fixture()+"VIRQ_CONTROLLER cpu=0\nVIRQ_SCENARIO name=baseline\n")
        self.assertEqual(len(baseline), 600)
        self.assertEqual(report["loads"], {})
        _, continuous = analyze(ready_fixture()+load_fixture("cpu_continuous"))
        self.assertEqual(continuous["loads"]["fair"]["pre_vm_batches"], 10)
        scenario, guests, windows = validate_load(linux_fixture())
        self.assertEqual(scenario, "linux_cpu")
        self.assertEqual(guests["fair"]["interval_reported_iterations"], 256*8192)
        self.assertEqual(len(windows), 600)
        self.assertEqual(windows[("fair", 1)]["load_window_batches"], 0)
        for host_cpu in (1, 3):
            try:
                _, guests, windows = validate_load(linux_fixture(host_cpu))
            except ValueError as error:
                self.fail(f"a fully observed Linux topology on CPU{host_cpu} was rejected: {error}")
            self.assertEqual(len(windows), 600)
            self.assertEqual(guests['fair']['host_cpu'], host_cpu)
            self.assertEqual(guests['fifo80']['host_cpu'], host_cpu)
        scenario, guests, windows = validate_load(linux_memory_fixture())
        self.assertEqual(scenario, 'linux_memory')
        self.assertEqual(guests['fair']['interval_logical_read_bytes'], 85 * 65536)
        self.assertEqual(windows[('fair', 300)]['logical_write_bytes'], 85 * 65536)
        self.assertEqual(windows[('fair', 1)]['logical_read_bytes'], 0)
        _, report = analyze(pressure_measurement(pressure_clock_fixture()))
        self.assertEqual(report['irq_pressure']['policies']['fifo80']['handled'], 2)

    def test_missing_wrong_cpu_unjoined_or_inconsistent_work_is_rejected(self):
        wrong_clock = pressure_clock_fixture().replace('period_ticks=100000', 'period_ticks=50000').replace('frequency_hz=1000000000', 'frequency_hz=500000000')
        with self.assertRaises(ValueError):
            analyze(pressure_measurement(wrong_clock))
        valid = load_fixture()
        mutations = [valid.replace("cpu=1", "cpu=0", 1),
                     valid.replace("VIRQ_CONTROLLER cpu=0", "VIRQ_CONTROLLER cpu=1"),
                     valid.replace("wrong_cpu=0", "wrong_cpu=1", 1),
                     valid.replace("joined=1", "joined=0", 1),
                     valid.replace("end_batches=151", "end_batches=1", 1),
                     valid.replace("final_batches=152", "final_batches=153", 1),
                     valid.replace("after_batches=2", "after_batches=0", 1),
                     valid.replace("sample=300", "sample=299", 1),
                     valid.replace("name=cpu_same_core", "name=baseline"),
                     valid+"VIRQ_LOAD_CLEANUP_FAILED error\n",
                     valid+"VIRQ_SCENARIO name=baseline\n"]
        for invalid in mutations:
            with self.subTest(invalid=invalid[-80:]), self.assertRaises(ValueError):
                validate_load(invalid)
        continuous = load_fixture("cpu_continuous")
        for invalid in (continuous.replace("VIRQ_LOAD_BOOT_WORK policy=fair batches=10\n", ""),
                        continuous.replace("batches=10", "batches=12"),
                        continuous.replace("name=cpu_continuous", "name=cpu_same_core")):
            with self.assertRaises(ValueError):
                validate_load(invalid)
        linux = linux_fixture()
        for invalid in (
            linux.replace("batches=512 checksum=", "batches=768 checksum=", 1),
            linux.replace("guest_cpu=0\n", "guest_cpu=1\n", 1),
            linux.replace("reports=3", "reports=4", 1),
            linux.replace("stopped=1", "stopped=0", 1),
            linux.replace("kind=Running", "kind=Stopped", 1),
            linux.replace("cpu=3 sequence=1", "cpu=2 sequence=1", 1),
            linux.replace("count=2 empty=1", "count=2 empty=0", 1),
            linux.replace("VIRQ_VM_GROUP_RETIRED count=2 empty=1\n", "", 1),
            linux.replace("after_batches=256", "after_batches=257", 1),
            linux.replace("name=linux_cpu", "name=baseline"),
            linux+"VIRQ_LOAD_BOOT_WORK policy=fair batches=10\n",
            linux+"VIRQ_IRQ_PRESSURE_CONFIG mode=sgi intid=0\n",
            linux+"LINUX_FENCE_REPLY version=1 phase=begin\n",
        ):
            with self.subTest(linux=invalid[-80:]), self.assertRaises(ValueError):
                validate_load(invalid)
        shared = linux_fixture(1)
        for invalid in (
            shared.replace('VIRQ_LINUX_CONFIG vm=1 vcpu=0 host_cpu=1',
                           'VIRQ_LINUX_CONFIG vm=1 vcpu=0 host_cpu=3', 1),
            shared.replace('VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu=1',
                           'VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu=3', 1),
            shared.replace('policy=fair vm=1 vcpu=0 host_cpu=1',
                           'policy=fair vm=1 vcpu=0 host_cpu=3', 1),
            shared.replace('VIRQ_RUNTIME cpu=1 sequence=1',
                           'VIRQ_RUNTIME cpu=3 sequence=1', 1),
            shared.replace('thread=11', 'thread=10'),
            shared.replace('kind=Binding thread=10 value0=1 value1=0',
                           'kind=Binding thread=10 value0=1 value1=1', 1),
            shared.replace('host_cpu=1', 'host_cpu=2'),
            re.sub(r'(VIRQ_RUNTIME .*?ticks=)(\d+)',
                   lambda match: match[1]+str(int(match[2])+10**15), shared),
            shared.replace('kind=Binding thread=10 value0=1', 'kind=GuestEntryBoundary thread=10 value0=0')
                  .replace('kind=GuestEntryBoundary thread=10 value0=0 value1=0\nVIRQ_RUNTIME cpu=1 sequence=3',
                           'kind=Binding thread=10 value0=1 value1=0\nVIRQ_RUNTIME cpu=1 sequence=3'),
            re.sub(r'^VIRQ_ISR_SAMPLE.*\n', '', shared, flags=re.M),
        ):
            with self.subTest(topology=invalid[-100:]), self.assertRaises(ValueError):
                validate_load(invalid)
        memory = linux_memory_fixture()
        for invalid in (
            memory.replace('LINUX_MEMORY_READY version=1', 'LINUX_MEMORY_READY version=2', 1),
            memory.replace('working_set_bytes=1056768', 'working_set_bytes=1056769', 1),
            memory.replace('every_batches=3', 'every_batches=0', 1),
            memory.replace('memory_batches=86', 'memory_batches=85', 1),
            memory.replace('logical_bytes=11272192', 'logical_bytes=1', 1),
            memory.replace('memory_checksum=', 'memory_checksum=1', 1),
            memory.replace('read_bytes=16777216', 'read_bytes=1', 1),
            memory.replace('VIRQ_LINUX_MEMORY_SUMMARY policy=fair', 'VIRQ_LINUX_MEMORY_SUMMARY policy=fifo80', 1),
            memory.replace('LINUX_MEMORY_READY version=1 working_set_bytes=1056768 every_batches=3 chunk_words=8192\n', '', 1),
            memory.replace('name=linux_memory', 'name=linux_cpu'),
            memory.replace('workload=memory', 'workload=cpu'),
            linux + 'LINUX_MEMORY_READY version=1 working_set_bytes=1056768 every_batches=3 chunk_words=8192\n',
        ):
            self.assertNotEqual(invalid, memory)
            with self.subTest(memory=invalid[-80:]), self.assertRaises(ValueError):
                validate_load(invalid)


if __name__ == "__main__":
    unittest.main()
