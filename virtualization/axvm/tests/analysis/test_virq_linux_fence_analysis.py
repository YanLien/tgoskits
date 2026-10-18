"""Prove completed work, causal coverage and fail-closed fence lifecycle."""

import re
import unittest

from analyze_virq_linux_fence import validate_fences, verify_fence_window
from analyze_virq_load import validate_load
from test_virq_load_analysis import linux_fixture, linux_memory_fixture, pressure_clock_fixture
from virq_work_counters import checksum_after, linux_memory_expected


def fixture(memory=False, coarse_zero=False):
    size, every = (1056768, 3) if memory else (0, 1)
    source = linux_memory_fixture(policy_span=4000000) if memory else linux_fixture(policy_span=4000000)
    source = source.replace('LINUX_LOAD_READY version=1', 'LINUX_LOAD_READY version=2')
    if coarse_zero:
        source = source.replace('end_batches=512', 'end_batches=256').replace('after_batches=512', 'after_batches=256')
    lines = ['VIRQ_LINUX_FENCE_CONFIG version=1 mode=serial clock=monotonic_raw']
    policy = 'fair'

    def reply(phase, count, ns):
        line = (f'LINUX_FENCE_REPLY version=1 phase={phase} batches={count} '
                f'checksum={checksum_after(count*8192)} time_ns={ns} guest_cpu=0')
        if memory:
            batches, logical, checksum = linux_memory_expected(count, size, every)
            line += f' memory_batches={batches} logical_bytes={logical} memory_checksum={checksum}'
        return line

    end_count = 300 if coarse_zero else 533
    for line in source.splitlines():
        if line.startswith('VIRQ_LINUX_SUMMARY'):
            policy = re.search(r'policy=(\w+)', line)[1]
            offset = 0 if policy == 'fair' else 4000000
            lines.append(f'VIRQ_LINUX_FENCE_SUMMARY policy={policy} begin_batches=281 end_batches={end_count} begin_ns=1000000 end_ns=3000000 begin_request_ticks={offset+999900} begin_observed_ticks={offset+1000100} end_request_ticks={offset+2999900} end_observed_ticks={offset+3000100} frequency_hz=1000000000 stopped=1')
        lines.append(line)
        if line.startswith('LINUX_MEMORY_READY') or (not memory and line.startswith('LINUX_LOAD_READY')):
            lines.append(f'LINUX_FENCE_READY version=1 clock=monotonic_raw resolution_ns=1 working_set_bytes={size} every_batches={every}')
        elif line.startswith('VIRQ_LINUX_BOOT'):
            lines.append(reply('begin', 281, 1000000))
            if coarse_zero:
                lines.append(reply('end', end_count, 3000000))
        elif line.startswith('LINUX_LOAD_PROGRESS batches=512 ') and not coarse_zero:
            lines.append(reply('end', end_count, 3000000))
    return '\n'.join(lines) + '\n'


class LinuxFenceAnalysis(unittest.TestCase):
    def test_arbitrary_batch_work_has_causal_rates_even_without_new_coarse_report(self):
        for memory in (False, True):
            for zero in (False, True):
                with self.subTest(memory=memory, coarse_zero=zero):
                    log = fixture(memory, zero)
                    _, loads, _ = validate_load(log)
                    report = validate_fences(log)
                    for policy, state in report['policies'].items():
                        batches = 19 if zero else 252
                        self.assertEqual(state['interval_iterations'], batches * 8192)
                        self.assertEqual(state['iterations_per_second'], batches * 8192 * 500)
                        self.assertEqual(loads[policy]['fenced_throughput']['elapsed_ns'], 2000000)
                        self.assertLess(state['iterations_per_second_causal_lower'], state['iterations_per_second'])
                        self.assertGreater(state['iterations_per_second_causal_upper'], state['iterations_per_second'])
                        if memory:
                            expected = (((300 if zero else 533)+2)//3-(281+2)//3)*65536
                            self.assertEqual(state['logical_read_bytes'], expected)
                            self.assertEqual(state['logical_write_bytes'], expected)
                        offset = 0 if policy == 'fair' else 4000000
                        verify_fence_window(report, policy, offset+1000200, offset+2999800, 1000000000)
        # End can precede the next complete serial report; no unreported tail is guessed.
        log = re.sub(r'^LINUX_LOAD_PROGRESS batches=768.*\n', '', fixture(), flags=re.M)
        log = log.replace(f'final_batches=768 checksum={checksum_after(768*8192)} reports=3',
                          f'final_batches=512 checksum={checksum_after(512*8192)} reports=2')
        _, loads, _ = validate_load(log)
        self.assertEqual(loads['fair']['final_reported_batches'], 512)
        self.assertEqual(loads['fair']['fenced_throughput']['end_batches'], 533)

    def test_incomplete_reordered_or_inconsistent_fence_evidence_cannot_credit_work(self):
        valid = fixture(True)
        mutations = (
            valid.replace('VIRQ_LINUX_FENCE_CONFIG version=1 mode=serial clock=monotonic_raw\n', ''),
            valid.replace('mode=serial', 'mode=off'),
            valid.replace('LINUX_LOAD_READY version=2', 'LINUX_LOAD_READY version=1', 1),
            valid.replace('LINUX_FENCE_READY version=1', 'LINUX_FENCE_READY version=2', 1),
            valid.replace('resolution_ns=1 ', 'resolution_ns=0 ', 1),
            valid.replace('resolution_ns=1 working_set_bytes=1056768', 'resolution_ns=1 working_set_bytes=1048576', 1),
            valid.replace('phase=begin', 'phase=end', 1),
            valid.replace('phase=end', 'phase=begin', 1),
            valid.replace('phase=begin batches=281', 'phase=begin batches=600', 1),
            valid.replace('phase=begin batches=281 checksum=', 'phase=begin batches=281 checksum=1', 1),
            valid.replace('time_ns=1000000 guest_cpu=0', 'time_ns=1000000 guest_cpu=1', 1),
            valid.replace('time_ns=1000000 guest_cpu=0 memory_batches=94', 'time_ns=1000000 guest_cpu=0 memory_batches=93', 1),
            valid.replace('begin_batches=281', 'begin_batches=282', 1),
            valid.replace('end_ns=3000000', 'end_ns=4000000', 1),
            valid.replace('time_ns=3000000', 'time_ns=4000000').replace('end_ns=3000000', 'end_ns=4000000'),
            valid.replace('begin_observed_ticks=1000100', 'begin_observed_ticks=3000000', 1),
            valid.replace('end_observed_ticks=3000100', 'end_observed_ticks=2000000', 1),
            valid.replace('frequency_hz=1000000000', 'frequency_hz=100000000', 1),
            valid.replace('VIRQ_LINUX_FENCE_SUMMARY policy=fair', 'VIRQ_LINUX_FENCE_SUMMARY policy=fifo80', 1),
            re.sub(r'^LINUX_FENCE_REPLY.*phase=end.*\n', '', valid, count=1, flags=re.M),
            re.sub(r'^VIRQ_LINUX_FENCE_SUMMARY.*\n', '', valid, count=1, flags=re.M),
            valid + 'LINUX_FENCE_REPLY version=1 phase=end\n',
            valid.replace('VIRQ_VM_GROUP_RETIRED count=2 empty=1\n', '', 1),
        )
        for invalid in mutations:
            self.assertNotEqual(invalid, valid)
            with self.subTest(tail=invalid[-60:]), self.assertRaises(ValueError):
                validate_load(invalid)

    def test_fences_cover_planned_arrival_and_pressure_covers_both_handshakes(self):
        log = fixture()
        result = validate_fences(log)
        for start, end, hz in ((1000099, 2999800, 1000000000),
                               (1000200, 2999901, 1000000000),
                               (1000200, 2999800, 100000000)):
            with self.assertRaises(ValueError):
                verify_fence_window(result, 'fair', start, end, hz)
        pressure = pressure_clock_fixture(policy_stride=4000000, window_duration=4000000)
        validate_load(log + pressure)
        # This pressure still covers the task interval but misses the Begin request.
        with self.assertRaises(ValueError):
            validate_load(log + pressure.replace('window_start_ticks=1000 ', 'window_start_ticks=1000000 ', 1))
        # An End reply arriving after pressure stops is likewise outside the proof.
        with self.assertRaises(ValueError):
            validate_load(log + pressure.replace('window_end_ticks=4000000', 'window_end_ticks=3000000', 1))


if __name__ == '__main__':
    unittest.main()
