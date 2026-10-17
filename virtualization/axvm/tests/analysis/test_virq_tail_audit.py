import csv
import itertools
from pathlib import Path
import tempfile
import unittest

from audit_virq_tail import audit, minimum_n, summarize


class TailAuditTests(unittest.TestCase):
    def test_exact_small_sample_probability_and_size_boundary(self):
        # Three equiprobable draws: at least one reaches the top category in
        # 37/64 outcomes; same count as exceeding Q75 for continuous uniform.
        outcomes = list(itertools.product(range(4), repeat=3))
        probability = sum(max(draw) >= 3 for draw in outcomes) / len(outcomes)
        self.assertEqual(probability, 37 / 64)
        self.assertAlmostEqual(probability, 1 - .75 ** 3)
        n = minimum_n(.999, .95)
        self.assertEqual(n, 2995)
        self.assertLess(1 - .999 ** (n - 1), .95)
        self.assertGreaterEqual(1 - .999 ** n, .95)
        self.assertAlmostEqual(summarize([(0, 1)] * 300)["quantiles"]["0.999"][
            "iid_hypothetical_max_covers_population_quantile_probability"],
            1 - .999 ** 300)

    def test_interval_envelope_contains_every_endpoint_realization(self):
        intervals = [(0, 20), (10, 11), (3, 30)]
        summary = summarize(intervals)
        for values in itertools.product(*intervals):
            for entry in summary["quantiles"].values():
                x = sorted(values)[entry["empirical_nearest_rank"] - 1]
                lo, hi = entry["empirical_quantile_interval_ns"]
                self.assertLessEqual(lo, x)
                self.assertLessEqual(x, hi)
        q = summarize([(i, i + 1) for i in range(300)])["quantiles"]
        self.assertEqual(q["0.999"]["empirical_nearest_rank"], 300)
        self.assertEqual(q["0.99"]["empirical_nearest_rank"], 297)

    def test_contexts_split_and_corruption_rejected(self):
        fields = ["policy", "source", "irq_entry_context", "scenario", "intid",
                  "sample", "complete", "entry_to_c_isr_lower_ns", "entry_to_c_isr_upper_ns"]
        rows = [dict(zip(fields, ["fair", "pl031_spi", context, "baseline", "34",
                                str(i), "True", "10", "20"]))
                for i, context in enumerate(("current_el_callback", "lower_el_pre_iar"), 1)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.csv"

            def write(selected):
                with path.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(selected)

            write(rows)
            result = audit(path, "entry_to_c_isr")
            self.assertEqual([s["observations"] for s in result["strata"]], [1, 1])
            self.assertFalse(result["iid_stationarity_and_independence_verified"])
            # A missing/ambiguous Ready decomposition must not censor a valid
            # physical-entry-to-ISR interval already checked by the upstream tool.
            write([dict(rows[0], complete="False")])
            result = audit(path, "entry_to_c_isr")
            self.assertEqual(result["strata"][0]["observations"], 1)
            self.assertEqual(result["strata"][0]["schedule_decomposition_counts"]["False"], 1)
            for corrupted in [rows + [rows[0]], [],
                              [dict(rows[0], complete="unknown")],
                              [dict(rows[0], entry_to_c_isr_lower_ns="21")],
                              [dict(rows[0], entry_to_c_isr_upper_ns="nan")]]:
                write(corrupted)
                with self.assertRaises(ValueError):
                    audit(path, "entry_to_c_isr")


if __name__ == "__main__":
    unittest.main()
