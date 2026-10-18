"""Protect complete-block sampling and outward clock-bound propagation."""
from collections import Counter
import unittest

from factorial_statistics import balanced_blocks, summarize_blocks


class FactorialStatistics(unittest.TestCase):
    def test_complete_blocks_preserve_common_drift_and_clock_bounds(self):
        blocks = []
        for i, drift in enumerate((100, 1000, 10000, 100000)):
            # Independent expected result: 190-120-130+100 = 40;
            # four endpoint errors of +/-1 give [36, 44].
            blocks.append(dict(block=i+1, conditions={name: [drift+delta-1, drift+delta+1]
                for name, delta in (("0", 0), ("A", 20), ("B", 30), ("AB", 90))}))
        report = summarize_blocks(blocks, seed=12, resamples=1000)
        self.assertEqual(report["interaction_mean_bounds_ns"], [36, 44])
        self.assertEqual(report["bootstrap_95_bounds_ns"], [36, 44])
        self.assertEqual(report["independent_complete_blocks"], 4)
        self.assertEqual(report["positive_block_bounds"], 4)
        self.assertEqual(report["leave_one_block_out_mean_bounds_ns"], [[36, 44]]*4)
        for broken in (blocks[:1], blocks+[blocks[0]],
                       [dict(block=b["block"], conditions={k: v for k, v in b["conditions"].items() if k != "B"}) for b in blocks],
                       [dict(block=b["block"], conditions={**b["conditions"], "AB": [1, float("nan")]}) for b in blocks],
                       [dict(block=b["block"], conditions={**b["conditions"], "0": [20, 10]}) for b in blocks],
                       [dict(block=b["block"], conditions={**b["conditions"], "0": [-2, -1]}) for b in blocks]):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                summarize_blocks(broken, seed=12, resamples=1000)

    def test_random_plan_balances_positions_without_inventing_repetitions(self):
        blocks = balanced_blocks(25)
        self.assertEqual(blocks, balanced_blocks(25))
        self.assertNotEqual(blocks, balanced_blocks(26))
        self.assertEqual(len(blocks), 8)
        for order in blocks:
            self.assertEqual(set(order), {"0", "A", "B", "AB"})
            self.assertEqual(len(order), 4)
        for position in zip(*blocks):
            self.assertEqual(Counter(position), {"0": 2, "A": 2, "B": 2, "AB": 2})
        transitions = Counter(pair for order in blocks for pair in zip(order, order[1:]))
        self.assertEqual(set(transitions), {(a, b) for a in ("0", "A", "B", "AB") for b in ("0", "A", "B", "AB") if a != b})
        self.assertEqual(set(transitions.values()), {2})


if __name__ == "__main__":
    unittest.main()
