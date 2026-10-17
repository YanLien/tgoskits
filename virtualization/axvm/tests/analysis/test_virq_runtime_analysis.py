"""Validate runtime association, concurrency ordering and loss rejection."""

import re
import unittest

from analyze_virq_runtime import analyze
from test_virq_isr_analysis import fixture as clock_fixture


def fixture(mode="normal"):
    lines = clock_fixture().splitlines()
    for i, line in enumerate(lines):
        if "policy=fifo80" in line:
            lines[i] = re.sub(r"(submit_ticks|guest_ticks|observed_ticks|host_before|host_after)=(\d+)",
                              lambda m: f"{m[1]}={int(m[2])+1_000_000}", line)
    events = [(100 + n, "Marker", 0, n, 0) for n in range(128)]
    for policy in range(2):
        base, thread = policy*1_000_000, 100 + policy
        events.extend([(base+9990, "Binding", thread, 2, 1),
                       (base+9991, "Stopped", thread, 0, 0)])
        for n in range(1, 301):
            start = base + 10_000 + n*100
            sequence = [(2, "IrqKick"), (10, "WakeBegin"), (20, "Running"),
                        (25, "WakeEnd"), (30, "GuestEntryBoundary"), (60, "Stopped")]
            if policy == 0 and n == 1:
                if mode == "missing_worker":
                    sequence = [x for x in sequence if x[1] not in ("WakeBegin", "WakeEnd")]
                elif mode == "ambiguous_irq":
                    sequence.append((3, "IrqKick"))
            events.extend((start+offset, kind, thread, 0, 0) for offset, kind in sequence)
    for n in range(1, 129):
        lines.append(f"VIRQ_TRACE_ENVELOPE sample={n} ticks=3 frequency_hz=1000000000")
    for index, (ticks, kind, thread, a, b) in enumerate(sorted(events)):
        lines.append(f"VIRQ_RUNTIME cpu=0 sequence={index} ticks={ticks} kind={kind} "
                     f"thread={thread} value0={a} value1={b}")
    lines.append(f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0")
    return "\n".join(lines)+"\n"


class RuntimeAnalysis(unittest.TestCase):
    def test_concurrent_wake_completion_preserves_a_causal_decomposition(self):
        rows, _, _, report = analyze(fixture())
        self.assertEqual(len(rows), 600)
        for policy in report["policies"].values():
            self.assertEqual(policy["full_chain_samples"], 300)
            self.assertEqual(policy["wake_end_after_running"], 300)
        for row in rows:
            self.assertTrue(row["full_chain"])
            self.assertEqual((row["submit_to_irq_ticks"], row["irq_to_worker_ticks"],
                              row["worker_to_running_ticks"], row["running_to_entry_ticks"],
                              row["entry_to_isr_lower_ticks"], row["entry_to_isr_upper_ticks"]),
                             (2, 8, 10, 10, 18, 22))

    def test_unassociated_samples_are_retained_and_incomplete_traces_are_rejected(self):
        for mode in ("missing_worker", "ambiguous_irq"):
            with self.subTest(mode=mode):
                rows, _, _, report = analyze(fixture(mode))
                self.assertEqual(len(rows), 600)
                self.assertFalse(rows[0]["full_chain"])
                self.assertEqual(report["policies"]["fair"]["full_chain_samples"], 299)
        valid = fixture()
        for bad in (valid.replace("dropped=0", "dropped=1"),
                    valid.replace("incomplete=0", "incomplete=1"),
                    valid.replace("sequence=1 ticks=", "sequence=0 ticks=", 1),
                    valid.replace("kind=IrqKick thread=100", "kind=IrqKick thread=999", 1)):
            self.assertNotEqual(bad, valid)
            with self.assertRaises(ValueError):
                analyze(bad)


if __name__ == "__main__":
    unittest.main()
