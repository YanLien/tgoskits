"""Deterministic checks for the counter calibration analysis, without hardware."""

import unittest

from analyze_virq_isr import analyze


def fixture(frequency=1_000_000_000):
    lines = []
    for policy in ("fair", "fifo80"):
        for phase, sequences in (("before", range(1, 33)), ("after", range(34, 66))):
            for sequence in sequences:
                guest = (1_000 if phase == "before" else 100_000) + sequence * 100
                # Strongly asymmetric probes still bound the true offset 1000.
                low, high = (990, 1002) if phase == "before" else (998, 1010)
                lines.append(f"VIRQ_CLOCK_SAMPLE policy={policy} phase={phase} sequence={sequence} "
                             f"host_before={guest+low} guest_ticks={guest} host_after={guest+high} "
                             f"frequency_hz={frequency}")
        for sample in range(1, 301):
            start = 10_000 + sample * 100
            lines.append(f"VIRQ_HOST_SAMPLE policy={policy} sample={sample} pulse_ns=1 ack_observed_ns=100")
            lines.append(f"VIRQ_ISR_SAMPLE policy={policy} sample={sample} submit_ticks={start} "
                         f"guest_ticks={start+50-1000} observed_ticks={start+100} frequency_hz={frequency}")
    return "\n".join(lines) + "\nAXTEST_SUITE_OK\n"


class ClockAnalysis(unittest.TestCase):
    def test_independent_asymmetric_calibration_retains_known_latency(self):
        rows, probes, summary = analyze(fixture())
        self.assertEqual((len(rows), len(probes)), (600, 128))
        self.assertTrue(all((r["isr_lower_ns"], r["isr_upper_ns"]) == (48, 52) for r in rows))
        for policy in summary.values():
            self.assertEqual((policy["offset_low_ticks"], policy["offset_high_ticks"]), (998, 1002))
            self.assertEqual(policy["injection_to_c_isr_ns"]["lower"]["p99"], 48)
        rounded, _, _ = analyze(fixture(3_000_000_000))
        self.assertTrue(all((r["isr_lower_ns"], r["isr_upper_ns"]) == (16, 18) for r in rounded))

    def test_guest_isr_end_and_trace_status_are_reported(self):
        log = fixture().replace(
            "guest_ticks=9150 observed_ticks=10200 frequency_hz=1000000000",
            "guest_ticks=9150 guest_end_ticks=9175 observed_ticks=10200 "
            "frequency_hz=1000000000",
        )
        rows, _, summary = analyze(log)
        # The fixture changes one sample per policy; old-format rows remain
        # explicitly unavailable instead of receiving a guessed duration.
        ended = [row for row in rows if row["guest_end_ticks"] is not None]
        self.assertEqual(len(ended), 2)
        self.assertTrue(all(row["isr_duration_lower_ns"] == 25 for row in ended))
        self.assertTrue(all(row["isr_duration_upper_ns"] == 25 for row in ended))
        self.assertTrue(all(row["trace_loss"] is None for row in rows))
        self.assertEqual(summary["fair"]["isr_duration_ns"]["samples"], 1)

    def test_runtime_trace_summary_is_joined_without_using_ack_window(self):
        log = fixture().replace(
            "AXTEST_SUITE_OK",
            "VIRQ_RUNTIME_SUMMARY records=100 dropped=0 incomplete=0\nAXTEST_SUITE_OK",
        )
        rows, _, summary = analyze(log)
        self.assertTrue(all(row["trace_loss"] is False for row in rows))
        self.assertEqual(summary["fifo80"]["trace_loss"], False)

    def test_invalid_measurements_do_not_produce_latency_results(self):
        valid = fixture()
        lines = valid.splitlines()
        failures = {
            "unsuccessful suite": valid.replace("AXTEST_SUITE_OK", "AXTEST_SUITE_FAIL"),
            "missing calibration": valid.replace(lines[0] + "\n", "", 1),
            "duplicate calibration": valid.replace(lines[1], lines[0], 1),
            "incompatible clocks": valid.replace("host_before=2090 guest_ticks=1100 host_after=2102",
                                                 "host_before=2090 guest_ticks=900 host_after=2102", 1),
            "frequency mismatch": valid.replace("frequency_hz=1000000000", "frequency_hz=0", 1),
            "causally impossible ISR": valid.replace("guest_ticks=9150 observed_ticks=10200",
                                                     "guest_ticks=20000 observed_ticks=10200", 1),
            "ISR end after observation": valid.replace("guest_ticks=9150 observed_ticks=10200",
                                                       "guest_ticks=9150 guest_end_ticks=20000 observed_ticks=10200", 1),
            "reversed host counter": valid.replace("submit_ticks=10100", "submit_ticks=10300", 1),
            "malformed ISR": valid.replace("submit_ticks=10100", "submit_ticks=invalid", 1),
        }
        for reason, invalid in failures.items():
            self.assertNotEqual(invalid, valid, reason)
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                analyze(invalid)


if __name__ == "__main__":
    unittest.main()
