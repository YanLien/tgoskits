"""Task completion must use Guest timestamps and an independent task deadline."""

import unittest

from analyze_virq_task import analyze
from test_virq_isr_analysis import fixture as isr_fixture


def fixture():
    lines = ["VIRQ_MEASUREMENT samples_per_policy=3",
             "VIRQ_TASK_CONFIG protocol=1 rounds=4096 relative_deadline_ns=100"]
    for line in isr_fixture().splitlines():
        if "VIRQ_HOST_SAMPLE" in line or "VIRQ_ISR_SAMPLE" in line:
            if int(line.split("sample=")[1].split()[0]) > 3:
                continue
        if "VIRQ_ISR_SAMPLE" in line:
            ticks = int(line.split("guest_ticks=")[1].split()[0])
            line = line.replace(" observed_ticks=", f" guest_end_ticks={ticks+5} observed_ticks=")
        if line != "AXTEST_SUITE_OK":
            lines.append(line)
    for policy in ("fair", "fifo80"):
        for sample, latency in enumerate((80, 100, 120), 1):
            submitted = 10_000 + sample * 100
            lines.append(f"VIRQ_TASK_SAMPLE policy={policy} sample={sample} "
                         f"start_ticks={submitted+60-1000} end_ticks={submitted+latency-1000} "
                         f"checksum=1853662840 observed_ticks={submitted+200}")
    return "\n".join(lines) + "\nVIRQ_RUNTIME_SUMMARY records=100 dropped=0 incomplete=0\nAXTEST_SUITE_OK\n"


class TaskCompletionAnalysis(unittest.TestCase):
    def test_completion_deadline_retains_clock_uncertainty(self):
        rows, summary = analyze(fixture())
        self.assertEqual(len(rows), 6)
        self.assertEqual([r["task_deadline_miss"] for r in rows[:3]],
                         ["false", "unknown", "true"])
        self.assertEqual((rows[0]["submit_to_completion_lower_ns"],
                          rows[0]["submit_to_completion_upper_ns"]), (78, 82))
        self.assertEqual(rows[0]["task_execution_ns"], 20)
        fair = summary["policies"]["fair"]
        self.assertAlmostEqual(fair["deadline_miss_ratio_lower"], 1/3)
        self.assertAlmostEqual(fair["deadline_miss_ratio_upper"], 2/3)
        self.assertEqual(fair["submit_to_completion_lower_ns"]["mean"], 98)
        self.assertEqual(fair["submit_to_completion_upper_ns"]["mean"], 102)
        blocked = fixture().replace("relative_deadline_ns=100\n",
                                    "relative_deadline_ns=100 wait_mode=blocked\n")
        blocked = blocked.replace("VIRQ_RUNTIME_SUMMARY", "VIRQ_TASK_BACKGROUND policy=fair non_target_vcpu_returns=7\n"
                                  "VIRQ_TASK_BACKGROUND policy=fifo80 non_target_vcpu_returns=3\nVIRQ_RUNTIME_SUMMARY")
        blocked_rows, blocked_summary = analyze(blocked)
        self.assertEqual(blocked_rows, rows)
        self.assertEqual(blocked_summary["task_wait_mode"], "blocked")

    def test_incomplete_or_impossible_tasks_cannot_be_reported_as_valid(self):
        valid = fixture()
        task_line = next(line for line in valid.splitlines() if "VIRQ_TASK_SAMPLE" in line)
        mutations = {
            "absent task": valid.replace(task_line+"\n", "", 1),
            "duplicate id": valid.replace(task_line, task_line+"\n"+task_line, 1),
            "task before ISR return": valid.replace("start_ticks=9160", "start_ticks=9150", 1),
            "completion before task": valid.replace("end_ticks=9180", "end_ticks=9159", 1),
            "completion after observation": valid.replace("observed_ticks=10300", "observed_ticks=10160", 1),
            "wrong result": valid.replace("checksum=1853662840", "checksum=0", 1),
            "missing config": valid.replace("VIRQ_TASK_CONFIG protocol=1 rounds=4096 relative_deadline_ns=100\n", ""),
            "zero budget": valid.replace("relative_deadline_ns=100", "relative_deadline_ns=0"),
            "loss": valid.replace("dropped=0", "dropped=1"),
            "unknown loss": valid.replace("VIRQ_RUNTIME_SUMMARY records=100 dropped=0 incomplete=0\n", ""),
            "disabled recorder with forged completeness": valid+"VIRQ_RECORDING mode=off scope=recorder_writes\n",
            "suite failed": valid.replace("AXTEST_SUITE_OK", "AXTEST_SUITE_FAIL"),
            "periodic record without configuration": valid+"VIRQ_PERIODIC_RELEASE policy=fair sample=0\n",
            "new mode missing background record": valid.replace("relative_deadline_ns=100\n",
                "relative_deadline_ns=100 wait_mode=blocked\n"),
            "spin mode background activity": valid.replace("relative_deadline_ns=100\n",
                "relative_deadline_ns=100 wait_mode=spin\n").replace("VIRQ_RUNTIME_SUMMARY",
                "VIRQ_TASK_BACKGROUND policy=fair non_target_vcpu_returns=1\n"
                "VIRQ_TASK_BACKGROUND policy=fifo80 non_target_vcpu_returns=0\nVIRQ_RUNTIME_SUMMARY"),
        }
        for reason, invalid in mutations.items():
            self.assertNotEqual(valid, invalid, reason)
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                analyze(invalid)


if __name__ == "__main__":
    unittest.main()
