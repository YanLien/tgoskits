"""Prove complete stratified interactions and paired macroblock sensitivity."""
import copy
import importlib.util
from pathlib import Path
import random
import unittest

from factorial_statistics import balanced_blocks

SCRIPT = Path(__file__).with_name('summarize-intensity.py')
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location('intensity_report', SCRIPT)
    subject = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subject)
else:
    subject = None


def synthetic_run_means():
    """Shared time drift cancels within blocks and between paired strata."""
    strata = ('reference', 'irq2x', 'memory_sparse')
    orders = {name: balanced_blocks(20261025+i) for i, name in enumerate(strata)}
    rng = random.Random(20261028)
    rows = []
    for block in range(1, 9):
        sequence = list(strata)
        rng.shuffle(sequence)
        for slot, stratum in enumerate(sequence):
            interaction = {'reference': 40, 'irq2x': -40, 'memory_sparse': 0}[stratum]
            interaction += 2*block-9
            for position, condition in enumerate(orders[stratum][block-1], 1):
                for policy, multiplier in [('fair', 1), ('fifo80', 2)]:
                    value = 100000*block+{'0': 0, 'A': 100, 'B': 200,
                                               'AB': 300+interaction}[condition]*multiplier
                    row = dict(block=block, stratum=stratum, position=position,
                               macro_position=slot*4+position, condition=condition,
                               name=f'synthetic-{block}-{stratum}-{condition}', policy=policy, tasks=32)
                    for metric, factor in [('release_to_completion', 1), ('irq_entry_to_completion', 3)]:
                        row[metric+'_lower_ns'] = value*factor-.125
                        row[metric+'_upper_ns'] = value*factor+.125
                    rows.append(row)
    return rows


class IntensityReport(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(subject, 'the intensity report algorithm is not implemented')

    def test_stratified_signed_interactions_and_paired_changes_cancel_shared_drift(self):
        result = subject.summarize_records(synthetic_run_means(), resamples=1000)
        for policy, multiplier in [('fair', 1), ('fifo80', 2)]:
            for metric, factor in [('release_to_completion', 1), ('irq_entry_to_completion', 3)]:
                scale = multiplier*factor
                positive = result['effects']['reference'][policy][metric]
                negative = result['effects']['irq2x'][policy][metric]
                null = result['effects']['memory_sparse'][policy][metric]
                self.assertEqual(positive['interaction_mean_bounds_ns'], [40*scale-.5, 40*scale+.5])
                self.assertEqual(negative['interaction_mean_bounds_ns'], [-40*scale-.5, -40*scale+.5])
                self.assertEqual(null['interaction_mean_bounds_ns'], [-.5, .5])
                self.assertEqual(positive['candidate_stable_sign'], 'positive')
                self.assertEqual(negative['candidate_stable_sign'], 'negative')
                self.assertIsNone(null['candidate_stable_sign'])
                for stratum, change in [('irq2x', -80), ('memory_sparse', -40)]:
                    paired = result['paired_changes'][stratum][policy][metric]
                    self.assertEqual(paired['mean_bounds_ns'], [change*scale-1, change*scale+1])
                    self.assertEqual(paired['bootstrap_95_bounds_ns'], [change*scale-1, change*scale+1])

    def test_incomplete_or_misaligned_design_is_rejected_before_inference(self):
        rows = synthetic_run_means()
        broken_position = copy.deepcopy(rows)
        broken_position[0]['macro_position'] = 12 if broken_position[0]['macro_position'] != 12 else 1
        broken_condition = copy.deepcopy(rows)
        broken_condition[2]['condition'] = broken_condition[0]['condition']
        for broken in (rows[:-1], broken_position, broken_condition):
            with self.subTest(reason='incomplete or mismatched pairing'):
                with self.assertRaises(ValueError):
                    subject.summarize_records(broken, resamples=200)


if __name__ == '__main__':
    unittest.main()
