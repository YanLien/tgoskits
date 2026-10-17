"""Validate workload progress evidence and reject mislabeled measurements."""

import unittest

from analyze_virq_load import analyze, checksum_after, validate_load
from test_virq_ready_analysis import fixture as ready_fixture


def load_fixture(scenario="cpu_same_core"):
    lines = ["VIRQ_CONTROLLER cpu=0", f"VIRQ_SCENARIO name={scenario}"]
    start = 11 if scenario == "cpu_continuous" else 1
    for thread, policy in enumerate(("fair", "fifo80"), 1):
        for sample in range(1, 301):
            # Include intervals with zero progress; FIFO need not run EEVDF per IRQ.
            before = start + (sample-1)//2
            after = start + sample//2
            lines.append(f"VIRQ_LOAD_SAMPLE policy={policy} sample={sample} before_batches={before} after_batches={after}")
        checksum = checksum_after((start+151)*8192)
        lines.append(f"VIRQ_LOAD_SUMMARY policy={policy} cpu=1 thread={thread} batch_iterations=8192 start_batches={start} end_batches={start+150} final_batches={start+151} wrong_cpu=0 checksum={checksum} joined=1")
        if scenario == "cpu_continuous":
            lines.append(f"VIRQ_LOAD_BOOT_WORK policy={policy} batches=10")
    return "\n".join(lines)+"\n"


def linux_fixture():
    lines = ["VIRQ_CONTROLLER cpu=0", "VIRQ_SCENARIO name=linux_cpu",
             "VIRQ_LINUX_CONFIG vm=1 vcpu=0 host_cpu=3 guest_cpu=0 workload=cpu batch_iterations=8192 report_batches=256"]
    sequence = 0
    for thread, policy in enumerate(("fair", "fifo80"), 10):
        lines.append("LINUX_LOAD_READY version=1 guest_cpu=0 batch_iterations=8192 report_batches=256")
        for count in (256, 512, 768):
            lines.append(f"LINUX_LOAD_PROGRESS batches={count} checksum={checksum_after(count*8192)} guest_cpu=0")
            if count == 256:
                lines.append("VIRQ_LINUX_BOOT vm=1 vcpu=0 host_cpu=3 guest_cpu=0 batches=256")
        lines.append(f"VIRQ_LINUX_SUMMARY policy={policy} vm=1 vcpu=0 host_cpu=3 guest_cpu=0 start_batches=256 end_batches=512 final_batches=768 checksum={checksum_after(768*8192)} reports=3 batch_iterations=8192 report_batches=256 stopped=1")
        for sample in range(1, 301):
            after = 512 if sample == 300 else 256
            lines.append(f"VIRQ_LINUX_SAMPLE policy={policy} sample={sample} before_batches=256 after_batches={after}")
        lines.append("VIRQ_VM_GROUP_RETIRED count=2 empty=1")
        for kind, v0 in (("Binding", 1), ("Running", 0), ("GuestEntryBoundary", 0), ("Stopped", 0)):
            lines.append(f"VIRQ_RUNTIME cpu=3 sequence={sequence} ticks={sequence} kind={kind} thread={thread} value0={v0} value1=0")
            sequence += 1
    return "\n".join(lines)+"\n"


class LoadAnalysis(unittest.TestCase):
    def test_measured_work_is_joined_to_all_samples_with_zero_progress_windows_retained(self):
        # Independently apply the recurrence to check the fast arithmetic.
        expected = 1
        for _ in range(16384):
            expected = (expected*6364136223846793005+1) % (1 << 64)
        self.assertEqual(checksum_after(16384), expected)
        rows, report = analyze(ready_fixture()+load_fixture())
        self.assertEqual(len(rows), 600)
        self.assertEqual(report["loads"]["fair"]["samples_with_progress"], 150)
        self.assertEqual(rows[0]["load_window_batches"], 0)
        self.assertEqual(rows[1]["load_window_batches"], 1)
        baseline, report = analyze(ready_fixture()+"VIRQ_CONTROLLER cpu=0\nVIRQ_SCENARIO name=baseline\n")
        self.assertEqual(len(baseline), 600)
        self.assertEqual(report["loads"], {})
        _, continuous = analyze(ready_fixture()+load_fixture("cpu_continuous"))
        self.assertEqual(continuous["loads"]["fair"]["pre_vm_batches"], 10)
        scenario, guests, windows = validate_load(linux_fixture())
        self.assertEqual(scenario, "linux_cpu")
        self.assertEqual(guests["fair"]["interval_reported_iterations"], 256*8192)
        self.assertEqual(len(windows), 600)
        self.assertEqual(windows[("fair", 1)]["load_window_batches"], 0)

    def test_missing_wrong_cpu_unjoined_or_inconsistent_work_is_rejected(self):
        valid = load_fixture()
        mutations = [valid.replace("cpu=1", "cpu=0", 1),
                     valid.replace("VIRQ_CONTROLLER cpu=0", "VIRQ_CONTROLLER cpu=1"),
                     valid.replace("wrong_cpu=0", "wrong_cpu=1", 1),
                     valid.replace("joined=1", "joined=0", 1),
                     valid.replace("end_batches=151", "end_batches=1", 1),
                     valid.replace("final_batches=152", "final_batches=153", 1),
                     valid.replace("after_batches=2", "after_batches=0", 1),
                     valid.replace("sample=300", "sample=299", 1),
                     valid.replace("name=cpu_same_core", "name=baseline"),
                     valid+"VIRQ_LOAD_CLEANUP_FAILED error\n",
                     valid+"VIRQ_SCENARIO name=baseline\n"]
        for invalid in mutations:
            with self.subTest(invalid=invalid[-80:]), self.assertRaises(ValueError):
                validate_load(invalid)
        continuous = load_fixture("cpu_continuous")
        for invalid in (continuous.replace("VIRQ_LOAD_BOOT_WORK policy=fair batches=10\n", ""),
                        continuous.replace("batches=10", "batches=12"),
                        continuous.replace("name=cpu_continuous", "name=cpu_same_core")):
            with self.assertRaises(ValueError):
                validate_load(invalid)
        linux = linux_fixture()
        for invalid in (
            linux.replace("batches=512 checksum=", "batches=768 checksum=", 1),
            linux.replace("guest_cpu=0\n", "guest_cpu=1\n", 1),
            linux.replace("reports=3", "reports=4", 1),
            linux.replace("stopped=1", "stopped=0", 1),
            linux.replace("kind=Running", "kind=Stopped", 1),
            linux.replace("cpu=3 sequence=1", "cpu=2 sequence=1", 1),
            linux.replace("count=2 empty=1", "count=2 empty=0", 1),
            linux.replace("VIRQ_VM_GROUP_RETIRED count=2 empty=1\n", "", 1),
            linux.replace("after_batches=256", "after_batches=257", 1),
            linux.replace("name=linux_cpu", "name=baseline"),
            linux+"VIRQ_LOAD_BOOT_WORK policy=fair batches=10\n",
        ):
            with self.subTest(linux=invalid[-80:]), self.assertRaises(ValueError):
                validate_load(invalid)


if __name__ == "__main__":
    unittest.main()
