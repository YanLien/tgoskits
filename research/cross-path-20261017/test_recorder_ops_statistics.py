"""The uncertainty unit is the independent boot pair, never its task count."""
import unittest
from recorder_ops_statistics import paired_endpoints


class PairedStatistics(unittest.TestCase):
    def test_whole_pair_uncertainty_preserves_endpoint_width_and_negative_costs(self):
        rows = [dict(block=i+1, latency_difference_lower_ns=value,
                     latency_difference_upper_ns=value+2) for i, value in enumerate((10, 20, 30, 40))]
        # Enumerating all 4**4 whole-pair resamples gives endpoint percentiles
        # 15 and 37. The seeded empirical draw lands on the same support points.
        result = paired_endpoints(rows, 20261022)
        self.assertEqual(result['latency_on_minus_off_mean_lower_ns'], 25)
        self.assertEqual(result['latency_on_minus_off_mean_upper_ns'], 27)
        self.assertEqual((result['paired_bootstrap_95_lower_ns'], result['paired_bootstrap_95_upper_ns']), (15, 37))
        shifted = [dict(block=r['block'], latency_difference_lower_ns=r['latency_difference_lower_ns']-100,
                        latency_difference_upper_ns=r['latency_difference_upper_ns']-100) for r in rows]
        negative = paired_endpoints(shifted, 20261022)
        self.assertEqual((negative['paired_bootstrap_95_lower_ns'], negative['paired_bootstrap_95_upper_ns']), (-85, -63))
        for broken in (rows+[rows[0]], [dict(r, latency_difference_upper_ns=r['latency_difference_lower_ns']-1) for r in rows]):
            with self.assertRaises(ValueError):
                paired_endpoints(broken, 20261022)


if __name__ == '__main__':
    unittest.main()
