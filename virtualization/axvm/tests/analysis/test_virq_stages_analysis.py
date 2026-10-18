"""Protect schema/causality and physical sample acceptance without hardware substitutes."""

from collections import Counter
import unittest

from analyze_virq_runtime import EVENT, SUMMARY
from analyze_virq_stages import analyze
from test_virq_physical_analysis import fixture
from virq_irq_stages import validate_stages

CONFIG = "VIRQ_STAGE_CONFIG version=1 key=cpu_intid_entry_ticks dispatch=host_route timer_sync=lower_el_only\n"


def event(kind, ticks, sequence, value1=100, cpu=0):
    return dict(cpu=cpu, sequence=sequence, ticks=ticks, kind=kind,
                thread=0, value0=30, value1=value1)


class IrqStagesAnalysis(unittest.TestCase):
    def test_context_specific_spans_preserve_absence_and_reject_bad_correlation(self):
        current = [event("HostIrqEntry", 100, 0, 1),
                   event("IrqDispatchBegin", 110, 1), event("IrqDispatchEnd", 150, 2)]
        lower = [event("HostIrqEntry", 100, 0, 2),
                 event("TimerSyncBegin", 110, 1), event("TimerSyncEnd", 120, 2),
                 event("IrqDispatchBegin", 130, 3), event("IrqDispatchEnd", 150, 4)]
        result = validate_stages(CONFIG, current)["entries"][0]
        self.assertIsNone(result["timer_sync_begin_ticks"])
        self.assertEqual(result["dispatch_end_ticks"]-result["dispatch_begin_ticks"], 40)
        result = validate_stages(CONFIG, lower)["entries"][0]
        self.assertEqual(result["timer_sync_end_ticks"]-result["timer_sync_begin_ticks"], 10)
        overlap = current+[dict(event("Running", 120, 0, cpu=1), thread=101)]
        self.assertEqual(validate_stages(CONFIG, overlap), validate_stages(CONFIG, current))
        self.assertFalse(validate_stages("", current[:1])["observations_available"])
        self.assertEqual(validate_stages(CONFIG, [])["entries"], [])
        for broken in (current[:-1], current+[current[-1]], lower[1:],
                       lower+[event("HostIrqEntry", 100, 0, 2)],
                       [dict(e, cpu=1) if e["kind"] == "IrqDispatchEnd" else e for e in current],
                       [dict(e, value1=99) if e["kind"] == "IrqDispatchEnd" else e for e in current],
                       [dict(e, thread=101) if e["kind"] == "IrqDispatchBegin" else e for e in current],
                       [dict(e, ticks=129) if e["kind"] == "TimerSyncEnd" else
                        dict(e, ticks=128) if e["kind"] == "IrqDispatchBegin" else e for e in lower],
                       current+[event("TimerSyncBegin", 105, 1)]):
            with self.assertRaises(ValueError):
                validate_stages(CONFIG, broken)
        for declaration in ("", CONFIG+CONFIG, CONFIG.replace("version=1", "version=2"), CONFIG.rstrip()+" extra\n"):
            with self.assertRaises(ValueError):
                validate_stages(declaration, current)

    def test_physical_samples_join_spans_and_allow_remote_execution_overlap(self):
        lines, events = [CONFIG.rstrip()], []
        for line in fixture().splitlines():
            match = EVENT.fullmatch(line)
            if not match:
                if not SUMMARY.fullmatch(line):
                    lines.append(line)
                continue
            cpu, _, ticks, kind, thread, a, b = match.groups()
            cpu, ticks, thread, a, b = map(int, (cpu, ticks, thread, a, b))
            events.append((ticks, 0 if kind == "HostIrqEntry" else 2, cpu, kind, thread, a, b))
            if kind == "HostIrqEntry":
                events += [(ticks, 1, cpu, "IrqDispatchBegin", 0, a, ticks),
                           (ticks+60, 3, cpu, "IrqDispatchEnd", 0, a, ticks)]
        counts = Counter()
        for ticks, _, cpu, kind, thread, a, b in sorted(events):
            lines.append(f"VIRQ_RUNTIME cpu={cpu} sequence={counts[cpu]} ticks={ticks} kind={kind} thread={thread} value0={a} value1={b}")
            counts[cpu] += 1
        lines.append(f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0")
        log = "\n".join(lines)+"\n"
        rows, report = analyze(log)
        self.assertEqual(len(rows), 600)
        self.assertTrue(all(r["dispatch_ns"] == 60 and r["timer_sync_ns"] is None
                            and r["dispatch_end_vs_isr"] == "certainly_after" for r in rows))
        self.assertFalse(report["M1"])
        for invalid in (fixture(), "VIRQ_RECORDING mode=off scope=recorder_writes\n"+log,
                        log.replace("kind=IrqDispatchBegin", "kind=TimerSyncBegin", 1)):
            with self.assertRaises(ValueError):
                analyze(invalid)


if __name__ == "__main__":
    unittest.main()
