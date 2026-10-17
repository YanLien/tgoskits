"""Check service placement provenance and failure-sensitive aggregation."""

import unittest

from analyze_virq_services import analyze


def fixture():
    return "\n".join([
        "VIRQ_SERVICE_PLACEMENT mode=cpu0",
        "VIRQ_SERVICE_THREAD role=control thread=11 requested_cpu=0 observations=12 wrong_cpu=0",
        "VIRQ_SERVICE_THREAD role=signal thread=12 requested_cpu=0 observations=15 wrong_cpu=0",
        "VIRQ_SERVICE_THREAD role=signal thread=13 requested_cpu=0 observations=16 wrong_cpu=0",
        "VIRQ_SERVICE_SUMMARY role=control requested_cpu=0 started=1 finished=1 observations=12 wrong_cpu=0",
        "VIRQ_SERVICE_SUMMARY role=signal requested_cpu=0 started=2 finished=2 observations=31 wrong_cpu=0",
    ]) + "\n"


class ServiceAnalysis(unittest.TestCase):
    def test_placement_requires_all_completed_service_threads_and_matching_counts(self):
        self.assertEqual(analyze(fixture())["roles"]["signal"]["threads"], 2)
        cpu1 = fixture().replace("mode=cpu0", "mode=cpu1").replace("requested_cpu=0", "requested_cpu=1")
        self.assertEqual(analyze(cpu1)["roles"]["signal"]["cpu"], 1)
        for bad in [fixture().replace("wrong_cpu=0", "wrong_cpu=1", 1),
                    fixture().replace("thread=13", "thread=12"),
                    fixture().replace("started=2", "started=3"),
                    fixture().replace("observations=31", "observations=30"),
                    fixture().replace("requested_cpu=0", "requested_cpu=2", 1),
                    fixture().replace("mode=cpu0", "mode=unrestricted"),
                    fixture().replace("role=control requested_cpu=0 started", "role=signal requested_cpu=0 started"),
                    fixture().replace("mode=cpu0", "mode=invalid")]:
            with self.assertRaises(ValueError):
                analyze(bad)
        self.assertFalse(analyze("")["verified"])
        self.assertFalse(analyze("VIRQ_SERVICE_PLACEMENT mode=unrestricted\n")["verified"])


if __name__ == "__main__":
    unittest.main()
