"""Exercise Ready association without substituting wake returns for enqueue."""

import unittest

from analyze_virq_ready import analyze
from analyze_virq_runtime import EVENT, SUMMARY
from test_virq_runtime_analysis import fixture as runtime_fixture


def fixture(mode="normal"):
    lines, events = [], []
    for line in runtime_fixture().splitlines():
        match = EVENT.fullmatch(line)
        if match:
            cpu, _, ticks, kind, thread, a, b = match.groups()
            events.append((int(ticks), kind, int(thread), int(a), int(b)))
        elif not SUMMARY.fullmatch(line):
            lines.append(line)
    fresh = []
    for ticks, kind, thread, _, _ in events:
        if kind == "WakeBegin":
            fresh.append((ticks+5, "ReadyEnqueue", thread, 0, 1))
    if mode == "already_on_cpu":
        first = fresh[0]
        fresh[0] = (*first[:4], 1 | 256)
    elif mode == "different_destination":
        first = fresh[0]
        fresh[0] = (*first[:3], 1, 1)
    elif mode == "duplicate_ready":
        first = fresh[0]
        fresh.append((first[0]+1, *first[1:]))
    events.extend(fresh)
    for index, (ticks, kind, thread, a, b) in enumerate(sorted(events)):
        lines.append(f"VIRQ_RUNTIME cpu=0 sequence={index} ticks={ticks} kind={kind} thread={thread} value0={a} value1={b}")
    lines.append(f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0")
    lines.append(f"VIRQ_READY_SUMMARY records={len(fresh)}")
    return "\n".join(lines)+"\n"


class ReadyAnalysis(unittest.TestCase):
    def test_real_enqueue_splits_the_existing_transaction_without_wake_end_order_assumptions(self):
        rows, events, report = analyze(fixture())
        self.assertEqual((len(rows), len(events)), (600, 600))
        for row in rows:
            self.assertTrue(row["complete"])
            self.assertEqual((row["wake_to_ready_ticks"], row["ready_to_running_ticks"]), (5, 5))
        self.assertEqual(report["policies"]["fair"]["ready_associated_samples"], 300)

    def test_on_cpu_migration_and_ambiguity_are_retained_instead_of_imputed(self):
        for mode, expected in (("already_on_cpu", "missing_fresh_ready"),
                               ("different_destination", "destination_cpu_changed"),
                               ("duplicate_ready", "ambiguous_fresh_ready")):
            with self.subTest(mode=mode):
                rows, _, report = analyze(fixture(mode))
                self.assertEqual(len(rows), 600)
                self.assertFalse(rows[0]["complete"])
                self.assertEqual(rows[0]["status"], expected)
                self.assertEqual(report["policies"]["fair"]["ready_associated_samples"], 299)
        valid = fixture()
        for bad in (valid.replace("VIRQ_READY_SUMMARY records=600", "VIRQ_READY_SUMMARY records=599"),
                    valid.replace("value0=0 value1=1", "value0=0 value1=999", 1)):
            self.assertNotEqual(bad, valid)
            with self.assertRaises(ValueError):
                analyze(bad)


if __name__ == "__main__":
    unittest.main()
