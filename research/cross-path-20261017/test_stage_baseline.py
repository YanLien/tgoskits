"""Protect offline chain algebra and association, without claiming runtime proof."""

from collections import Counter
import importlib
import importlib.util
from pathlib import Path
import re
import sys
import unittest

ARCHIVE = Path(__file__).resolve().parent
ANALYSIS = ARCHIVE.parent.parent / "virtualization/axvm/tests/analysis"
sys.path.insert(0, str(ANALYSIS))
from test_virq_isr_analysis import fixture as clock_fixture


def fixture(mode="complete", frequency=3_000_000_000):
    """Use the existing calibration fixture with a small physical-task cohort."""
    lines = ["VIRQ_MEASUREMENT samples_per_policy=3", "VIRQ_SOURCE kind=physical_timer_ppi",
             "VIRQ_CONTROLLER cpu=0", "VIRQ_SCENARIO name=baseline",
             "VIRQ_TASK_CONFIG protocol=1 rounds=4096 relative_deadline_ns=100",
             "VIRQ_STAGE_CONFIG version=1 key=cpu_intid_entry_ticks dispatch=host_route timer_sync=lower_el_only"]
    events = [(100+n, 0, "Marker", 0, n, 0) for n in range(128)]
    for line in clock_fixture(frequency).splitlines():
        sample = re.search(r"sample=(\d+)", line)
        if sample and int(sample[1]) > 3:
            continue
        if "VIRQ_ISR_SAMPLE" in line:
            guest = int(re.search(r"guest_ticks=(\d+)", line)[1])
            line = line.replace(" observed_ticks=", f" guest_end_ticks={guest+5} observed_ticks=")
        if line != "AXTEST_SUITE_OK":
            lines.append(line)
    for policy, thread in (("fair", 100), ("fifo80", 101)):
        # Separate host windows keep the original join's candidate set unique.
        base = 0 if policy == "fair" else 1_000_000
        if base:
            lines = [re.sub(r"(submit_ticks|guest_ticks|guest_end_ticks|observed_ticks|host_before|host_after)=(\d+)",
                            lambda m: f"{m[1]}={int(m[2])+base}", line)
                     if "policy=fifo80" in line else line for line in lines]
        events += [(base+9990, 1, "Binding", thread, 2, 1),
                   (base+9991, 1, "Stopped", thread, 0, 0)]
        for n in range(1, 4):
            start = base+10_000+n*100
            lines += [f"VIRQ_PHYSICAL_ARM policy={policy} sample={n} due_ticks={start+1} intid=30 cpu=0",
                      f"VIRQ_TASK_SAMPLE policy={policy} sample={n} start_ticks={start-940} "
                      f"end_ticks={start-920} checksum=1853662840 observed_ticks={start+200}"]
            sequence = [(1, 0, "HostIrqEntry", 0, 30, 1),
                        (1, 0, "IrqDispatchBegin", 0, 30, start+1),
                        (2, 0, "IrqKick", thread, 0, 0),
                        (10, 0, "WakeBegin", thread, 0, 0),
                        (15, 0, "ReadyEnqueue", thread, 1, 1),
                        (20, 1, "Running", thread, 0, 0),
                        (25, 0, "WakeEnd", thread, 0, 0),
                        (30, 1, "GuestEntryBoundary", thread, 0, 0),
                        (60, 1, "Stopped", thread, 0, 0),
                        (61, 0, "IrqDispatchEnd", 0, 30, start+1)]
            if mode in ("route_end_before_running", "route_end_at_running"):
                route_end = 19 if mode == "route_end_before_running" else 20
                sequence = [(route_end, *e[1:]) if e[2] == "IrqDispatchEnd" else e for e in sequence]
            if policy == "fair" and n == 1:
                if mode == "missing_ready":
                    sequence = [e for e in sequence if e[2] != "ReadyEnqueue"]
                elif mode == "multiple_entries":
                    sequence += [(31, 1, "GuestEntryBoundary", thread, 0, 0)]
            events.extend((start+t, cpu, kind, owner, a, b) for t, cpu, kind, owner, a, b in sequence)
        lines.append(f"VIRQ_PHYSICAL_SUMMARY policy={policy} intid=30 cpu=0 handled=3 errors=0 retired=1")
    for n in range(1, 129):
        lines.append(f"VIRQ_TRACE_ENVELOPE sample={n} ticks=3 frequency_hz={frequency}")
    counters = Counter()
    for ticks, cpu, kind, thread, a, b in sorted(events):
        lines.append(f"VIRQ_RUNTIME cpu={cpu} sequence={counters[cpu]} ticks={ticks} kind={kind} "
                     f"thread={thread} value0={a} value1={b}")
        counters[cpu] += 1
    lines += [f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0",
              f"VIRQ_READY_SUMMARY records={sum(e[2] == 'ReadyEnqueue' for e in events)}", "AXTEST_SUITE_OK"]
    return "\n".join(lines)+"\n"


class StageBaseline(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("stage_baseline"),
                             "stage baseline analysis has not been implemented")
        return importlib.import_module("stage_baseline")

    def test_serial_chain_excludes_overlapping_route_and_preserves_offset_correlation(self):
        analysis = self.module()
        rows, report = analysis.analyze(fixture())
        self.assertEqual((len(rows), report["full_chain_samples"]), (6, 6))
        row = rows[0]
        self.assertEqual((row["t0_ticks"], row["irq_kick_ticks"]), (10101, 10102))
        self.assertGreater(row["dispatch_end_ticks"], row["running_ticks"])
        self.assertTrue("dispatch_end_vs_isr" in row, "the original route-end/ISR-begin classification must be retained")
        self.assertEqual((row["dispatch_end_vs_isr"], row["dispatch_end_vs_ready"], row["dispatch_end_vs_running"]),
                         ("certainly_after", "after", "after"))
        self.assertEqual(report["policies"]["fair"]["overlap_classifications"]["dispatch_end_vs_running"], {"after": 3})
        self.assertIsNone(row["lower_el_timer_sync_lower_ns"])
        self.assertNotIn("host_route", row["additive_stage_names"].split(","))
        with self.assertRaisesRegex(ValueError, "overlap|additive"):
            analysis.correlated_sum(row, [*analysis.ADDITIVE_STAGES, "host_route"])
        total = analysis.correlated_sum(row, analysis.ADDITIVE_STAGES)
        self.assertEqual((total["lower_ticks"], total["upper_ticks"]), (77, 81))
        self.assertEqual((row["chain_algebra_residual_constant_ticks"],
                          row["chain_algebra_residual_offset_coefficient"]), (0, 0))
        self.assertLessEqual(row["chain_rounding_residual_lower_ns"], 0)
        self.assertGreaterEqual(row["chain_rounding_residual_upper_ns"], 0)
        self.assertNotEqual(row["chain_rounding_residual_lower_ns"],
                            row["chain_rounding_residual_upper_ns"])
        # Crossing into Guest and back to Host uses the same offset variable.
        observed = analysis.correlated_sum(row, ["t0_to_guest_isr_begin_correlated",
                                                  "guest_isr_begin_to_host_observation"])
        self.assertEqual((observed["offset_coefficient"], observed["lower_ticks"], observed["upper_ticks"]),
                         (0, 99, 99))
        self.assertEqual(row["guest_isr_execution_lower_ticks"], 5)
        self.assertEqual(row["guest_isr_execution_upper_ticks"], 5)
        self.assertEqual(report["policies"]["fair"]["conditional_distributions_ns"]["host_route"]["samples"], 3)
        annotated = [dict(r, boot=boot, condition="example") for boot in ("boot-a", "boot-b") for r in rows]
        pooled = analysis.summarize(annotated)
        self.assertEqual((pooled["samples"], pooled["full_chain_samples"]), (12, 12))
        self.assertEqual(pooled["policies"]["fair"]["conditional_distributions_ns"]["task_execution"]["lower"]["mean"],
                         report["policies"]["fair"]["conditional_distributions_ns"]["task_execution"]["lower"]["mean"])
        clipped = fixture().replace("guest_end_ticks=9155 observed_ticks=10200",
                                    "guest_end_ticks=9151 observed_ticks=10150", 1)
        clipped = clipped.replace("end_ticks=9180 checksum=1853662840 observed_ticks=10300",
                                  "end_ticks=9180 checksum=1853662840 observed_ticks=10180", 1)
        clipped_row = analysis.analyze(clipped)[0][0]
        self.assertEqual((clipped_row["t0_to_guest_isr_begin_correlated_upper_ticks"],
                          clipped_row["t0_to_guest_isr_begin_causal_upper_ticks"]), (51, 49))
        self.assertEqual((clipped_row["t0_to_task_end_correlated_upper_ticks"],
                          clipped_row["t0_to_task_end_causal_upper_ticks"]), (81, 79))
        for mode, expected in (("route_end_before_running", "before"), ("route_end_at_running", "same_tick")):
            current = analysis.analyze(fixture(mode))[0][0]
            self.assertEqual((current["dispatch_end_vs_running"], current["dispatch_end_vs_isr"]),
                             (expected, "certainly_before"))

    def test_missing_or_ambiguous_boundaries_keep_the_denominator_and_no_synthetic_stages(self):
        analysis = self.module()
        for mode, expected in (("missing_ready", "ready:missing_fresh_ready"),
                               ("multiple_entries", "ambiguous_runtime_boundaries")):
            with self.subTest(mode=mode):
                rows, report = analysis.analyze(fixture(mode))
                self.assertEqual((len(rows), report["full_chain_samples"]), (6, 5))
                self.assertEqual(rows[0]["status"], expected)
                unavailable = "ready_to_running" if mode == "missing_ready" else "running_to_guest_entry_boundary"
                self.assertIsNone(rows[0][unavailable+"_lower_ns"])
                policy = report["policies"]["fair"]
                self.assertEqual((policy["samples"], policy["full_chain_samples"]), (3, 2))
                self.assertEqual(policy["conditional_distributions_ns"]["task_execution"]["samples"], 2)
                self.assertIn("all_sample_auxiliary_distributions_ns", policy)
                self.assertEqual(policy["all_sample_auxiliary_distributions_ns"]["host_route"]["samples"], 3)
                self.assertTrue("dispatch_end_vs_running" in rows[0], "unique Host boundaries need actual relation classifications")
                self.assertEqual(rows[0]["dispatch_end_vs_running"], "after")
                self.assertEqual(rows[0]["dispatch_end_vs_ready"], "missing" if mode == "missing_ready" else "after")
                self.assertEqual(sum(policy["overlap_classifications"]["dispatch_end_vs_ready"].values()), 3)
        valid = fixture()
        for invalid in (valid.replace("dropped=0", "dropped=1"),
                        valid.replace("kind=IrqDispatchEnd", "kind=TimerSyncEnd", 1),
                        valid.replace("VIRQ_TASK_SAMPLE policy=fair sample=1", "VIRQ_TASK_SAMPLE policy=fair sample=2", 1),
                        "VIRQ_RECORDING mode=off scope=recorder_writes\n"+valid):
            with self.assertRaises(ValueError):
                analysis.analyze(invalid)

    def test_formal_aggregation_requires_every_original_run_and_successful_finalizer(self):
        analysis = self.module()
        plan = {"pilots": [dict(name="pilot-"+mode, mode=mode, runtime="qemu", block=None)
                            for mode in ("on", "off")], "blocks": []}
        for block in range(1, 9):
            plan["blocks"].append(dict(block=block, runs=[dict(name=f"boot-{block}-{mode}", mode=mode,
                                                              runtime="board", block=block)
                                                         for mode in ("on", "off")]))
        expected = plan["pilots"]+[r for block in plan["blocks"] for r in block["runs"]]
        state = dict(terminal=True, success=True, completed=expected)
        sealed = dict(terminal=True, success=True, phase="sealed")
        self.assertEqual(len(analysis.require_completed_plan(plan, state, sealed)), 8)
        for changed, finalizer in ((dict(state, terminal=False), sealed),
                                   (dict(state, success=False), sealed),
                                   (dict(state, completed=expected[:-1]), sealed),
                                   (dict(state, completed=expected[:-1]+[expected[0]]), sealed),
                                   (state, dict(sealed, success=False)),
                                   (state, dict(sealed, phase="waiting"))):
            with self.assertRaises(ValueError):
                analysis.require_completed_plan(plan, changed, finalizer)


if __name__ == "__main__":
    unittest.main()
