"""Delivery identity, single in-flight SGIs, counter windows and joined teardown."""
import unittest
from analyze_virq_irq_pressure import validate_pressure


def fixture():
    lines = ['VIRQ_IRQ_PRESSURE_CONFIG mode=sgi intid=15 sender_cpu=2 target_cpu=0 period_us=2000 period_ticks=2000 burst=2 rounds=64 limit=4096 frequency_hz=1000000']
    for policy in ('fair', 'fifo80'):
        for sequence, due, sent in ((1, 100, 101), (2, 100, 110), (3, 4100, 4101), (4, 4100, 4110)):
            value = sequence
            for _ in range(64):
                value = (value * 6364136223846793005 + 1) & ((1 << 64) - 1)
            lines.append(f'VIRQ_IRQ_PRESSURE_EVENT policy={policy} sequence={sequence} scheduled_ticks={due} sent_ticks={sent} handler_start_ticks={sent+1} handler_end_ticks={sent+2} observed_ticks={sent+3} checksum={value} intid=15 sender_cpu=2 target_cpu=0')
        lines.append(f'VIRQ_IRQ_PRESSURE_SUMMARY policy={policy} sent=4 handled=4 errors=0 start_count=1 end_count=4 window_start_ticks=105 window_end_ticks=4200 skipped_periods=1 joined=1 retired=1')
    return '\n'.join(lines) + '\n'


class PressureAnalysis(unittest.TestCase):
    def test_serial_delivery_bursts_and_completion_windows(self):
        report = validate_pressure(fixture())
        self.assertEqual([e['sequence'] for e in report['policies']['fair']['events']], [1, 2, 3, 4])
        self.assertEqual(report['policies']['fair']['handled'], 4)
        self.assertTrue(report['policies']['fifo80']['retired'])
        self.assertEqual(validate_pressure('')['mode'], 'off_legacy')
        disabled = fixture().splitlines()[0].replace('mode=sgi', 'mode=off') + '\n'
        self.assertEqual(validate_pressure(disabled)['policies'], {})

    def test_corrupt_incomplete_or_unretired_deliveries_are_rejected(self):
        valid = fixture()
        for invalid in (
            valid.replace('sequence=2', 'sequence=1', 1),
            valid.replace('checksum=', 'checksum=9', 1),
            valid.replace('intid=15', 'intid=0', 1),
            valid.replace('target_cpu=0', 'target_cpu=1', 1),
            valid.replace('handler_start_ticks=102', 'handler_start_ticks=100', 1),
            valid.replace('sent_ticks=110', 'sent_ticks=103', 1),
            valid.replace('scheduled_ticks=4100', 'scheduled_ticks=4099'),
            valid.replace('handled=4', 'handled=3', 1),
            valid.replace('end_count=4', 'end_count=2', 1),
            valid.replace('start_count=1', 'start_count=2', 1),
            valid.replace('window_end_ticks=4200', 'window_end_ticks=4100', 1),
            valid.replace('retired=1', 'retired=0', 1),
            valid.replace('period_ticks=2000', 'period_ticks=2001'),
            valid.replace('burst=2', 'burst=1'),
            valid.replace('mode=sgi', 'mode=off'),
            '\n'.join(valid.splitlines()[1:]),
            valid + 'VIRQ_IRQ_PRESSURE_CLEANUP_FAILED error\n',
        ):
            with self.subTest(invalid=invalid[:100]), self.assertRaises(ValueError):
                validate_pressure(invalid)


if __name__ == '__main__':
    unittest.main()
