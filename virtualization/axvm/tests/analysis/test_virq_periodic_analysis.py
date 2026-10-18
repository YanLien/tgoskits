"""Fixed arrivals, non-dropped work, measured backlog and release-based deadlines."""
import unittest

from analyze_virq_task import analyze
from test_virq_task_analysis import fixture as task_fixture


def fixture():
    value = 0x12345678
    for _ in range(8192):
        value = (value*1664525+1013904223) % (1 << 32)
    lines = []
    for line in task_fixture().splitlines():
        if 'VIRQ_TASK_SAMPLE' in line:
            continue
        lines.append(line.replace('frequency_hz=1000000000', 'frequency_hz=1000000')
            .replace('rounds=4096 relative_deadline_ns=100', 'rounds=8192 relative_deadline_ns=400000 wait_mode=blocked'))
    lines.append('VIRQ_PERIODIC_CONFIG version=1 period_ns=100000 period_ticks=100 rounds=8192 jobs=3 frequency_hz=1000000 deadline_origin=scheduled_release')
    for policy in ('fair', 'fifo80'):
        lines.append(f'VIRQ_TASK_BACKGROUND policy={policy} non_target_vcpu_returns=0')
        for sample in (1, 2, 3):
            due, submitted = 9900+sample*100, 10000+sample*100
            start, end = 9160+(sample-1)*300, 9460+(sample-1)*300
            lines.append(f'VIRQ_TASK_SAMPLE policy={policy} sample={sample} start_ticks={start} end_ticks={end} checksum={value} observed_ticks=20000')
            lines.append(f'VIRQ_PERIODIC_RELEASE policy={policy} sample={sample} scheduled_ticks={due} submitted_ticks={submitted} host_due_backlog={1 if sample < 3 else 0}')
            lines.append(f'VIRQ_PERIODIC_BACKLOG policy={policy} sample={sample} isr_outstanding={sample} task_outstanding={2 if sample == 2 else 1}')
        lines.append(f'VIRQ_PERIODIC_DRAIN policy={policy} jobs=3 completed=3 observed_ticks=20000 ready=1')
    return '\n'.join(lines)+'\n'


def pressure_window(start):
    lines = ['VIRQ_IRQ_PRESSURE_CONFIG mode=sgi intid=15 sender_cpu=2 target_cpu=0 period_us=100 period_ticks=100 burst=1 rounds=64 limit=4096 frequency_hz=1000000']
    for policy in ('fair', 'fifo80'):
        for sequence, due in ((1, 8000), (2, 11000)):
            value = sequence
            for _ in range(64):
                value = (value * 6364136223846793005 + 1) % (1 << 64)
            lines.append(f'VIRQ_IRQ_PRESSURE_EVENT policy={policy} sequence={sequence} scheduled_ticks={due} sent_ticks={due+1} handler_start_ticks={due+2} handler_end_ticks={due+3} observed_ticks={due+4} checksum={value} intid=15 sender_cpu=2 target_cpu=0')
        lines.append(f'VIRQ_IRQ_PRESSURE_SUMMARY policy={policy} sent=2 handled=2 errors=0 start_count=1 end_count=2 window_start_ticks={start} window_end_ticks=20001 skipped_periods=29 joined=1 retired=1')
    return '\n'.join(lines)+'\n'


class PeriodicAnalysis(unittest.TestCase):
    def test_backlog_and_deadlines_include_release_lateness_without_dropping_jobs(self):
        rows, report = analyze(fixture())
        self.assertEqual(len(rows), 6)
        self.assertEqual([r['task_deadline_miss'] for r in rows[:3]], ['true', 'true', 'true'])
        self.assertLessEqual(rows[0]['submit_to_completion_upper_ns'], 400000)
        self.assertEqual(report['task_deadline_origin'], 'scheduled_release')
        self.assertEqual(rows[0]['release_to_completion_lower_ns'], 458000)
        self.assertEqual(rows[0]['submit_to_completion_lower_ns'], 358000)
        self.assertEqual(report['periodic']['policies']['fair']['max_isr_outstanding'], 3)
        self.assertEqual(report['periodic']['policies']['fair']['jobs_with_guest_backlog'], 2)
        self.assertEqual([r['task_outstanding'] for r in rows[:3]], [1, 2, 1])
        with_pressure, _ = analyze(fixture()+pressure_window(9900))
        self.assertEqual(with_pressure, rows)

    def test_incomplete_grid_false_backlog_or_inconsistent_drain_is_rejected(self):
        valid = fixture()
        for invalid in (
            valid.replace('scheduled_ticks=10100', 'scheduled_ticks=10101', 1),
            valid.replace('host_due_backlog=1', 'host_due_backlog=0', 1),
            valid.replace('isr_outstanding=2', 'isr_outstanding=1', 1),
            valid.replace('task_outstanding=2', 'task_outstanding=1', 1),
            valid.replace('completed=3', 'completed=2', 1),
            valid.replace('observed_ticks=20000 ready=1', 'observed_ticks=20001 ready=1', 1),
            valid.replace('sample=3 scheduled_ticks=', 'sample=2 scheduled_ticks=', 1),
            valid.replace('rounds=8192 jobs=3', 'rounds=8193 jobs=3'),
            valid.replace('start_ticks=9460', 'start_ticks=9459', 1),
            valid.replace('period_ticks=100', 'period_ticks=99'),
            valid.replace('wait_mode=blocked', 'wait_mode=spin'),
            valid+pressure_window(10050),
        ):
            self.assertNotEqual(valid, invalid)
            with self.subTest(invalid=invalid[-100:]), self.assertRaises(ValueError):
                analyze(invalid)


if __name__ == '__main__':
    unittest.main()
