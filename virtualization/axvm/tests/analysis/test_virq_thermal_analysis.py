"""Protect thermal availability and timestamp provenance as a parsing contract."""
import unittest
from analyze_virq_thermal import validate

CONFIG='VIRQ_THERMAL_CONFIG enabled=1 scope=policy_before_create_after_retirement sensors=soc0_little3\n'


class ThermalAnalysis(unittest.TestCase):
    def test_snapshots_bracket_each_policy_and_absence_never_becomes_zero(self):
        windows={p:dict(frequency_hz=24_000_000,first_submit_ticks=base+100,last_completion_observed_ticks=base+200)
                 for p,base in (('fair',0),('fifo80',1000))}
        lines=[CONFIG.rstrip()]
        for policy,base in (('fair',0),('fifo80',1000)):
            for point,offset in (('before_create',20),('after_retirement',220)):
                lines.append(f'VIRQ_THERMAL_SAMPLE policy={policy} point={point} begin_ticks={base+offset} end_ticks={base+offset+24} frequency_hz=24000000 soc_mc=40000 little_mc=42000')
        log='\n'.join(lines)+'\n'
        rows,report=validate(log,windows)
        self.assertEqual(len(rows),4)
        self.assertTrue(all(r['query_pair_envelope_ns']==1000 for r in rows))
        self.assertTrue(report['observations_available'])
        self.assertIsNone(report['window_maximum_mc'])
        off=CONFIG.replace('enabled=1','enabled=0')
        off_rows,off_report=validate(off,windows)
        self.assertEqual(off_rows,[])
        self.assertIsNone(off_report['temperature_mc'])
        self.assertFalse(off_report['observations_available'])
        for broken in (CONFIG,log+lines[1]+'\n',log.replace(CONFIG,''),
                       log.replace('enabled=1','enabled=0'),log.replace('enabled=1','enabled=2'),
                       log.replace('frequency_hz=24000000','frequency_hz=62500000',1),
                       log.replace('end_ticks=44','end_ticks=101',1),
                       log.replace('begin_ticks=220','begin_ticks=199',1),
                       log.replace('little_mc=42000','little_mc=125001',1),
                       log.replace('end_ticks=44','end_ticks=19',1)):
            with self.assertRaises(ValueError):
                validate(broken,windows)


if __name__=='__main__':
    unittest.main()
