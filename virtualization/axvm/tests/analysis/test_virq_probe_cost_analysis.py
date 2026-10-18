"""Recorder-off task observations must preserve work and unavailable stages."""
import unittest

from analyze_virq_probe_cost import analyze
from analyze_virq_task import analyze as complete_chain
from test_virq_periodic_analysis import fixture as periodic_fixture


def fixture(mode):
    log = periodic_fixture()
    if mode == 'off':
        log = '\n'.join(line for line in log.splitlines() if not line.startswith('VIRQ_RUNTIME'))+'\n'
    count, visibility = ('100','available') if mode == 'on' else ('0','unavailable')
    return (f'VIRQ_RECORDING mode={mode} scope=recorder_writes\n'+log+
            f'VIRQ_RECORDING_SUMMARY mode={mode} records={count} dropped=0 incomplete=0 stage_observations={visibility}\n')


class RecorderCostAnalysis(unittest.TestCase):
    def test_equal_work_preserves_deadlines_without_inventing_missing_stages(self):
        enabled, _ = analyze(fixture('on'))
        disabled, result = analyze(fixture('off'))
        self.assertFalse(result['complete_chain_accepted'])
        self.assertEqual([r['task_deadline_miss'] for r in disabled],['true']*6)
        self.assertTrue(all(r['trace_loss'] is None and r['irq_entry_to_completion_lower_ns'] is None
                            for r in disabled))
        for on, off in zip(enabled,disabled):
            self.assertEqual({k:v for k,v in on.items() if k != 'trace_loss'},
                             {k:v for k,v in off.items() if k != 'trace_loss'})
        # Version 2 names the enabled operations accurately. Declaration
        # migration must preserve workload validation and unavailable stages.
        for mode, legacy_rows in (('on', enabled), ('off', disabled)):
            current = fixture(mode).replace('scope=recorder_writes',
                                           'scope=recorder_operations version=2')
            current_rows, current_report = analyze(current)
            self.assertEqual(current_rows, legacy_rows)
            self.assertEqual(current_report['recording_declaration_version'], 2)
            self.assertEqual(current_report['comparison_scope'], 'recorder_operations')
            self.assertEqual(current_report['complete_chain_accepted'], mode == 'on')
        with self.assertRaises(ValueError):
            complete_chain(fixture('off'))
        physical = fixture('off')+'VIRQ_SOURCE kind=physical_timer_ppi\n'
        for policy in ('fair','fifo80'):
            for n in (1,2,3):
                physical += f'VIRQ_PHYSICAL_ARM policy={policy} sample={n} due_ticks={10005+n*100} intid=30 cpu=0\n'
            physical += f'VIRQ_PHYSICAL_SUMMARY policy={policy} intid=30 cpu=0 handled=3 errors=0 retired=1\n'
        self.assertEqual(len(analyze(physical)[0]),6)
        for broken in (physical.replace('handled=3','handled=2',1),
                       physical.replace('due_ticks=10105','due_ticks=20000',1)):
            with self.assertRaises(ValueError):
                analyze(broken)

    def test_unknown_modes_false_completeness_and_corrupt_work_are_rejected(self):
        off, on = fixture('off'), fixture('on')
        for broken in (off.replace('mode=off scope','mode=on scope'),
                       off.replace('scope=recorder_writes', 'scope=recorder_operations'),
                       off.replace('scope=recorder_writes', 'scope=recorder_operations version=3'),
                       off.replace('scope=recorder_writes', 'scope=recorder_writes version=2'),
                       off.replace('scope=recorder_writes', 'scope=all_probes version=2'),
                       off.replace('stage_observations=unavailable','stage_observations=available'),
                       off+'VIRQ_RUNTIME_SUMMARY records=0 dropped=0 incomplete=0\n',
                       off.replace('checksum=','checksum=9',1),
                       off.replace('completed=3','completed=2',1),
                       off.replace('start_ticks=9460','start_ticks=9459',1),
                       off.replace('dropped=0','dropped=1',1),
                       on.replace('SUMMARY mode=on records=100','SUMMARY mode=on records=99'),
                       off.replace('VIRQ_RECORDING mode=off scope=recorder_writes\n','')):
            with self.subTest(broken=broken[-100:]), self.assertRaises(ValueError):
                analyze(broken)


if __name__ == '__main__':
    unittest.main()
