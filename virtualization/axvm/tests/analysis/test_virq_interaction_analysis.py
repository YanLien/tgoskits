import unittest

from analyze_virq_interaction import interaction_effect, summarize_replicates


class InteractionAnalysisTests(unittest.TestCase):
    def test_interaction_effect_uses_mean_additive_contrast(self):
        self.assertEqual(interaction_effect(100, 120, 130, 190), 40)

    def test_replicates_report_mean_and_percentile_interval(self):
        report = summarize_replicates(
            [100, 101, 99], [120, 121, 119], [130, 131, 129], [190, 191, 189],
            seed=7,
        )
        self.assertEqual(report["interaction_ns"], 40)
        self.assertEqual(report["replicates"], 3)
        self.assertLessEqual(report["ci95_low_ns"], 40)
        self.assertGreaterEqual(report["ci95_high_ns"], 40)

    def test_mismatched_replicate_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize_replicates([1], [2, 3], [4], [5])


if __name__ == "__main__":
    unittest.main()
