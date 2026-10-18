"""Protect the block-level uncertainty contract, not synthetic event pooling."""

import unittest

from analyze_virq_interaction import summarize_replicates


class InteractionBlockContract(unittest.TestCase):
    def test_common_block_drift_is_retained_when_resampling(self):
        baseline = [100, 1000, 10000, 100000]
        # Each complete block has interaction +40, despite large common drift.
        report = summarize_replicates(baseline, [x+20 for x in baseline],
                                      [x+30 for x in baseline], [x+90 for x in baseline], seed=9)
        self.assertEqual(report["interaction_ns"], 40)
        self.assertEqual((report["ci95_low_ns"], report["ci95_high_ns"]), (40, 40))
        self.assertEqual(report["sampling_unit"], "independent_complete_block_of_four_runs")

    def test_invalid_or_nonindependent_input_shapes_are_rejected(self):
        for condition in ([], [1], [1, float("nan")], [1, float("inf")],
                          [1, -1], [1, True], [1, "2"]):
            with self.subTest(condition=condition), self.assertRaises(ValueError):
                summarize_replicates(condition, condition, condition, condition)


if __name__ == "__main__":
    unittest.main()
