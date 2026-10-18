"""Keep complete counter series and assumptions distinct from hardware bounds."""
import json
import unittest
from analyze_virq_counter import validate


class CounterAnalysis(unittest.TestCase):
    def test_sequences_are_complete_causal_and_raw_reordering_is_only_diagnostic(self):
        windows = {p: dict(frequency_hz=1000, first_submit_ticks=base+3000,
                           last_completion_observed_ticks=base+4000)
                   for p, base in (('fair', 0), ('fifo80', 10000))}
        config = 'VIRQ_COUNTER_CONFIG enabled=1 version=1 reads=256 modes=physical_virtual_raw scope=before_frequency_cycles exception_level=2'
        lines = ['VIRQ_FREQUENCY_CONFIG enabled=1 scope=policy_before_create_after_retirement method=pmu_cycle_bracket target_us=2000 cpus=1', config]
        for policy, base in (('fair', 0), ('fifo80', 10000)):
            for point, offset in (('before_create', 1), ('after_retirement', 5000)):
                start = base+offset
                for index, mode in enumerate(('physical', 'virtual', 'physical_raw')):
                    begin = start+index*600
                    values = [begin+(i//2)*3 for i in range(256)]
                    lines.append(f'VIRQ_COUNTER_SERIES policy={policy} point={point} cpu=0 mode={mode} begin_ticks={begin} end_ticks={begin+500} counter_hz=1000 values={json.dumps(values)}')
                t = start+2000
                lines.append(f'VIRQ_FREQUENCY_SAMPLE policy={policy} point={point} cpu=0 midr=1093652560 pmuver=4 t0={t} t1={t+1} t2={t+5} t3={t+6} c0=100 c1=4100 counter_hz=1000')
        log = '\n'.join(lines)+'\n'
        rows, sensitivity, report = validate(log, windows)
        self.assertEqual(len(rows), 12)
        self.assertEqual(report['raw_reads'], 3072)
        self.assertEqual(report['by_mode']['physical']['observed_positive_ticks'], [3])
        self.assertFalse(report['effective_resolution_verified'])
        self.assertFalse(report['physical_frequency_error_bounds_verified'])
        self.assertEqual({s['assumed_quantum_ticks'] for s in sensitivity}, {1, 3})
        raw = next(line for line in lines if 'mode=physical_raw ' in line)
        data = json.loads(raw.split('values=')[1]);data[10], data[20] = data[20], data[10]
        altered = raw.split('values=')[0]+'values='+json.dumps(data)
        _, _, reordered = validate(log.replace(raw, altered), windows)
        self.assertGreater(reordered['by_mode']['physical_raw']['backwards_differences'], 0)
        off = '\n'.join(lines[:2]).replace('enabled=1', 'enabled=0')+'\n'
        self.assertEqual(validate(off, windows)[0], [])
        for broken in (log+lines[2]+'\n', log.replace(lines[2]+'\n', ''),
                       log.replace(config, ''), log.replace(config, config.replace('enabled=1', 'enabled=0')),
                       log.replace('counter_hz=1000', 'counter_hz=2000', 1),
                       log.replace('begin_ticks=5000', 'begin_ticks=3999', 1),
                       log.replace('end_ticks=501', 'end_ticks=3001', 1),
                       log.replace('values=[1, 1,', 'values=[true, 1,', 1),
                       log.replace('values=[1, 1,', 'values=[18446744073709551616, 1,', 1),
                       log.replace('values=[1, 1,', 'values=[9, 1,', 1)):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    validate(broken, windows)


if __name__ == '__main__':
    unittest.main()
