"""Frequency bounds require complete, causal and explicitly enabled snapshots."""
import unittest
from analyze_virq_frequency import validate

CONFIG = 'VIRQ_FREQUENCY_CONFIG enabled=1 scope=policy_before_create_after_retirement method=pmu_cycle_bracket target_us=2000 cpus=2\n'


class FrequencyAnalysis(unittest.TestCase):
    def test_cycle_bounds_require_all_cpus_and_never_imply_window_coverage(self):
        windows = {p: dict(frequency_hz=1000, first_submit_ticks=base+30,
                           last_completion_observed_ticks=base+40)
                   for p, base in (('fair', 0), ('fifo80', 100))}
        lines = [CONFIG.rstrip()]
        for policy, base in (('fair', 0), ('fifo80', 100)):
            for point, offset in (('before_create', 1), ('after_retirement', 50)):
                for cpu in range(2):
                    t = base+offset+cpu*10
                    lines.append(f'VIRQ_FREQUENCY_SAMPLE policy={policy} point={point} cpu={cpu} midr=1091555385 pmuver=4 t0={t} t1={t+1} t2={t+3} t3={t+4} c0=100 c1=4100 counter_hz=1000')
        log = '\n'.join(lines)+'\n'
        rows, report = validate(log, windows)
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r['frequency_lower_hz'] == 799_800 and r['frequency_upper_hz'] == 4_001_000 for r in rows))
        quantized = log.replace('t1=2 ', 't1=1 ', 1).replace('t3=5 ', 't3=4 ', 1)
        same_tick_rows, _ = validate(quantized, windows)
        self.assertLess(same_tick_rows[0]['frequency_lower_hz'], same_tick_rows[0]['frequency_upper_hz'])
        self.assertEqual(same_tick_rows[0]['frequency_lower_hz'], 999_750)
        self.assertEqual(same_tick_rows[0]['frequency_upper_hz'], 2_000_500)
        self.assertFalse(report['continuous_coverage'])
        self.assertIsNone(report['window_frequency_hz'])
        off = CONFIG.replace('enabled=1', 'enabled=0')
        off_rows, off_report = validate(off, windows)
        self.assertEqual(off_rows, [])
        self.assertFalse(off_report['observations_available'])
        self.assertIsNone(off_report['window_frequency_hz'])
        for broken in (CONFIG, log+lines[1]+'\n', log.replace(CONFIG, ''),
                       log.replace('enabled=1', 'enabled=0'), log.replace('enabled=1', 'enabled=2'),
                       log.replace('counter_hz=1000', 'counter_hz=2000', 1),
                       log.replace('t3=5', 't3=31', 1), log.replace('t0=50', 't0=39', 1),
                       log.replace('t2=4', 't2=2', 1), log.replace('c1=4100', 'c1=100', 1),
                       log.replace('pmuver=4', 'pmuver=9', 1), log.replace('cpu=1', 'cpu=0', 1),
                       log.replace('midr=1091555385', 'midr=1091555386', 1)):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    validate(broken, windows)


if __name__ == '__main__':
    unittest.main()
