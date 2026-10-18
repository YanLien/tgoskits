"""Check distinct physical-entry intervals and reject synthetic or incomplete provenance."""

from collections import Counter
import re
import unittest

from analyze_virq_physical import analyze
from analyze_virq_runtime import EVENT, SUMMARY
from test_virq_ready_analysis import fixture as ready_fixture
from test_virq_memory_analysis import memory_fixture


def fixture():
    lines, events = ["VIRQ_SOURCE kind=physical_timer_ppi", "VIRQ_CONTROLLER cpu=0",
                     "VIRQ_SCENARIO name=baseline"], []
    for line in ready_fixture().splitlines():
        match = EVENT.fullmatch(line)
        if match:
            _, _, ticks, kind, thread, a, b = match.groups()
            cpu = 0 if kind in ("Marker", "IrqKick", "WakeBegin", "WakeEnd", "ReadyEnqueue") else 1
            if kind == "ReadyEnqueue":
                a = "1"
            events.append((int(ticks), cpu, kind, int(thread), int(a), int(b)))
        elif not SUMMARY.fullmatch(line):
            lines.append(line)
    for policy, base in (("fair", 0), ("fifo80", 1_000_000)):
        for index in range(1, 301):
            ticks = base+10_000+index*100+1
            lines.append(f"VIRQ_PHYSICAL_ARM policy={policy} sample={index} due_ticks={ticks} intid=30 cpu=0")
            events.append((ticks, 0, "HostIrqEntry", 0, 30, 1))
        lines.append(f"VIRQ_PHYSICAL_SUMMARY policy={policy} intid=30 cpu=0 handled=300 errors=0 retired=1")
    counters = Counter()
    for ticks, cpu, kind, thread, a, b in sorted(events):
        lines.append(f"VIRQ_RUNTIME cpu={cpu} sequence={counters[cpu]} ticks={ticks} kind={kind} thread={thread} value0={a} value1={b}")
        counters[cpu] += 1
    lines.append(f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0")
    return "\n".join(lines)+"\n"


def running_fixture():
    lines, events, startup_ready = [], [], set()
    for line in fixture().splitlines():
        match = EVENT.fullmatch(line)
        if match:
            cpu, _, ticks, kind, thread, a, b = match.groups()
            if kind in ("HostIrqEntry", "IrqKick"):
                cpu = "1"
            if kind == "HostIrqEntry":
                b = "2"
            if kind == "Running":
                ticks = str(int(ticks)-21)
            if kind == "ReadyEnqueue":
                if thread in startup_ready:
                    continue
                startup_ready.add(thread)
                ticks, cpu = str((int(thread)-100)*1_000_000+9992), "2"
            events.append((int(ticks), int(cpu), kind, int(thread), int(a), int(b)))
        elif not SUMMARY.fullmatch(line) and not line.startswith("VIRQ_READY_SUMMARY"):
            lines.append(line.replace("intid=30 cpu=0", "intid=30 cpu=1"))
    lines += ["VIRQ_GUEST_EXECUTION mode=running target_cpu=1 controller_policy=default service_cpu=2 irq_cpu=1",
              "VIRQ_SERVICE_PLACEMENT mode=cpu2"]
    for role, thread in (("control", 900), ("signal", 901)):
        lines += [f"VIRQ_SERVICE_THREAD role={role} thread={thread} requested_cpu=2 observations=1000 wrong_cpu=0",
                  f"VIRQ_SERVICE_SUMMARY role={role} requested_cpu=2 started=1 finished=1 observations=1000 wrong_cpu=0"]
    counters = Counter()
    for ticks, cpu, kind, thread, a, b in sorted(events):
        lines.append(f"VIRQ_RUNTIME cpu={cpu} sequence={counters[cpu]} ticks={ticks} kind={kind} thread={thread} value0={a} value1={b}")
        counters[cpu] += 1
    lines.append(f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0")
    lines.append(f"VIRQ_READY_SUMMARY records={len(startup_ready)}")
    return "\n".join(lines)+"\n"


def cross_core_mixed_fixture(owner_events):
    lines, events = [
        "VIRQ_TASK_CONFIG protocol=1 rounds=4096 relative_deadline_ns=100 wait_mode=blocked"
    ], list(owner_events)
    for line in fixture().splitlines():
        match = EVENT.fullmatch(line)
        if match:
            cpu, _, ticks, kind, thread, a, b = match.groups()
            cpu, ticks, thread, a, b = map(int, (cpu, ticks, thread, a, b))
            if kind == "HostIrqEntry" and ticks == 10101:
                b = 2
            events.append((ticks, 2, cpu, kind, thread, a, b))
        elif not SUMMARY.fullmatch(line):
            lines.append(line)
    counts = Counter()
    for ticks, _, cpu, kind, thread, a, b in sorted(events):
        lines.append(f"VIRQ_RUNTIME cpu={cpu} sequence={counts[cpu]} ticks={ticks} kind={kind} thread={thread} value0={a} value1={b}")
        counts[cpu] += 1
    lines.append(f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0")
    return "\n".join(lines)+"\n"


class PhysicalAnalysis(unittest.TestCase):
    def test_declared_scale_controls_all_completeness_gates(self):
        lines, events = ["VIRQ_MEASUREMENT samples_per_policy=299"], []
        for line in fixture().splitlines():
            match = EVENT.fullmatch(line)
            if match:
                cpu, _, ticks, kind, thread, a, b = match.groups()
                if kind == "HostIrqEntry" and int(ticks) in (40001, 1040001):
                    continue
                events.append((cpu, ticks, kind, thread, a, b))
            elif not SUMMARY.fullmatch(line):
                if re.search(r"VIRQ_(?:HOST_SAMPLE|ISR_SAMPLE|PHYSICAL_ARM).* sample=300\b", line):
                    continue
                lines.append(line.replace("handled=300", "handled=299"))
        counters = Counter()
        for cpu, ticks, kind, thread, a, b in events:
            lines.append(f"VIRQ_RUNTIME cpu={cpu} sequence={counters[cpu]} ticks={ticks} kind={kind} thread={thread} value0={a} value1={b}")
            counters[cpu] += 1
        lines.append(f"VIRQ_RUNTIME_SUMMARY records={len(events)} dropped=0 incomplete=0")
        log = "\n".join(lines)+"\n"
        rows, _ = analyze(log)
        self.assertEqual(len(rows), 598)
        for broken in (log.replace("samples_per_policy=299", "samples_per_policy=300"),
                       log.replace("VIRQ_MEASUREMENT samples_per_policy=299\n", ""),
                       "VIRQ_MEASUREMENT samples_per_policy=299\n"+log,
                       log.replace("samples_per_policy=299", "samples_per_policy=1001"),
                       log.replace("handled=299", "handled=300")):
            with self.assertRaises(ValueError):
                analyze(broken)

    def test_rtc_alarm_seconds_never_become_host_timer_deadlines(self):
        lines = []
        for line in fixture().splitlines():
            line = line.replace("kind=physical_timer_ppi", "kind=pl031_spi")
            if line.startswith("VIRQ_PHYSICAL_ARM"):
                line = re.sub(r"due_ticks=\d+", "match_seconds=123", line)
                line = line.replace("VIRQ_PHYSICAL_ARM", "VIRQ_RTC_ARM").replace("intid=30", "intid=34")
            if line.startswith("VIRQ_PHYSICAL_SUMMARY"):
                line = line.replace("VIRQ_PHYSICAL_SUMMARY", "VIRQ_RTC_SUMMARY").replace("intid=30", "intid=34")
                line += " restored_mr=0 imsc=0 ris=0 mis=0"
            if "kind=HostIrqEntry" in line:
                line = line.replace("value0=30", "value0=34")
            lines.append(line)
        lines += ["VIRQ_RTC_CONFIG base=0x9010000 intid=34 cpu=0 target_cpu=1 initial_mr=0 imsc=0 ris=0 mis=0"]*2
        valid = "\n".join(lines)+"\n"
        rows, report = analyze(valid)
        self.assertEqual(len(rows), 600)
        self.assertEqual(report["source"], "pl031_spi")
        self.assertTrue(all(r["rtc_match_seconds"] == 123 and "due_ticks" not in r
                            and "deadline_to_entry_ns" not in r for r in rows))
        self.assertIn("rtc_arm_to_c_isr_ns", report["policies"]["fair"]["clock"])
        for invalid in (valid.replace("restored_mr=0", "restored_mr=1", 1),
                        valid.replace("VIRQ_RTC_CONFIG base=0x9010000", "VIRQ_RTC_CONFIG base=0x9000000", 1),
                        valid+"VIRQ_PHYSICAL_ARM policy=fair sample=1 due_ticks=2 intid=30 cpu=0\n"):
            with self.assertRaises(ValueError):
                analyze(invalid)

    def test_low_el_and_current_el_origins_remain_classified_with_execution_proof(self):
        valid = running_fixture()
        mixed = valid.replace("value0=30 value1=2", "value0=30 value1=1", 1)
        rows, report = analyze(mixed)
        self.assertEqual(len(rows), 600)
        self.assertEqual(report["policies"]["fair"]["irq_entry_context_counts"],
                         {"current_el_callback": 1, "lower_el_pre_iar": 299})
        self.assertEqual(rows[0]["irq_cpu"], 1)
        memory = memory_fixture().replace("cpu=2", "cpu=3")
        memory = "\n".join(line for line in memory.splitlines()
                           if not line.startswith(("VIRQ_CONTROLLER", "VIRQ_SCENARIO")))+"\n"
        combined = valid.replace("name=baseline", "name=memory_cross_core")+memory
        memory_rows, memory_report = analyze(combined)
        self.assertEqual(len(memory_rows), 600)
        self.assertEqual(memory_report["load_and_ready"]["loads"]["fair"]["cpu"], 3)
        with self.assertRaises(ValueError):
            analyze(combined.replace("cpu=3", "cpu=2"))
        profile = next(line for line in valid.splitlines() if line.startswith("VIRQ_GUEST_EXECUTION"))
        running = next(line for line in valid.splitlines() if "kind=Running" in line)
        for bad in (valid.replace(profile+"\n", ""),
                    valid.replace("value0=30 value1=2", "value0=30 value1=1"),
                    valid.replace(running, running.replace("kind=Running", "kind=Stopped")),
                    valid.replace("mode=cpu2", "mode=unrestricted")):
            with self.assertRaises(ValueError):
                analyze(bad)
        # CPU0 can be in the non-target Guest while CPU1 remains the target.
        binding = (9900, 0, 0, "Binding", 200, 2, 0)
        running = (10000, 0, 0, "Running", 200, 0, 0)
        entry = (10100, 0, 0, "GuestEntryBoundary", 200, 0, 0)
        stopped = (10102, 0, 0, "Stopped", 200, 0, 0)
        owners = [binding, running, entry, stopped]
        mixed = cross_core_mixed_fixture(owners)
        rows, report = analyze(mixed)
        self.assertEqual(report["execution_context"], "mixed")
        self.assertEqual(report["policies"]["fair"]["irq_entry_context_counts"],
                         {"lower_el_pre_iar": 1, "current_el_callback": 299})
        self.assertEqual(rows[0]["irq_source_thread"], 200)
        self.assertEqual((rows[0]["irq_source_vm"], rows[0]["irq_source_vcpu"]), (2, 0))
        self.assertTrue(all(row["irq_source_thread"] is None for row in rows[1:]))
        # Same-tick source order is established by the one CPU's sequence.
        boundary = (10101, 1, *entry[2:])
        self.assertEqual(len(analyze(cross_core_mixed_fixture(
            [binding, running, boundary, stopped]))[0]), 600)
        self.assertEqual(len(analyze(cross_core_mixed_fixture(
            [(10001, 0, *binding[2:]), running, entry, stopped]))[0]), 600)
        invalid_owners = (
            [running, entry, stopped], [binding, entry, stopped],
            [binding, running, stopped],
            [(10102, 0, *binding[2:]), running, entry, stopped],
            [(9900, 0, 1, *binding[3:]), running, entry, stopped],
            [(*binding[:5], 1, 0), running, entry, stopped],
            [binding, running, (9999, 0, *entry[2:]), stopped],
            [binding, running, (10101, 3, *entry[2:]), stopped],
            [binding, running, entry, (10101, 1, *stopped[2:])],
            [binding, running, (10040, 0, *entry[2:]),
             (10050, 0, *stopped[2:]), (10090, 0, *running[2:]), stopped],
            owners+[(9901, 0, 0, "Binding", 201, 2, 0),
                    (10001, 0, 0, "Running", 201, 0, 0)],
        )
        for source_events in invalid_owners:
            with self.assertRaises(ValueError):
                analyze(cross_core_mixed_fixture(source_events))
        for invalid in (mixed.replace("wait_mode=blocked", "wait_mode=spin"),
                        mixed.replace(" wait_mode=blocked", ""),
                        mixed+mixed.splitlines()[0]+"\n"):
            with self.assertRaises(ValueError):
                analyze(invalid)

    def test_timer_arm_and_irq_entry_are_distinct_calibrated_observation_points(self):
        rows, report = analyze(fixture())
        self.assertEqual(len(rows), 600)
        self.assertTrue(all((r["entry_to_c_isr_lower_ns"], r["entry_to_c_isr_upper_ns"]) == (47, 51)
                            and r["entry_to_kick_ns"] == 1 for r in rows))
        self.assertTrue(all(r["deadline_ns"] == 1 and r["deadline_miss"] == "true" for r in rows))
        clock = report["policies"]["fair"]["clock"]
        self.assertIn("timer_arm_to_c_isr_ns", clock)
        self.assertNotIn("injection_to_c_isr_ns", clock)

    def test_missing_wrong_source_deadline_or_retirement_is_rejected(self):
        valid = fixture()
        first_entry = next(line for line in valid.splitlines() if "kind=HostIrqEntry" in line)
        for invalid in (valid+"VIRQ_STAGE_CONFIG version=1 key=cpu_intid_entry_ticks dispatch=host_route timer_sync=lower_el_only\n",
                        valid.replace("VIRQ_SOURCE kind=physical_timer_ppi", "VIRQ_SOURCE kind=software"),
                        valid.replace("due_ticks=10101", "due_ticks=10102", 1),
                        valid.replace("handled=300 errors=0", "handled=299 errors=0", 1),
                        valid.replace("retired=1", "retired=0", 1),
                        valid.replace(first_entry, first_entry.replace("value0=30", "value0=31")),
                        valid.replace(first_entry+"\n", "", 1),
                        valid+"VIRQ_SOURCE kind=physical_timer_ppi\n",
                        valid+"VIRQ_PHYSICAL_CLEANUP_FAILED error\n"):
            with self.assertRaises(ValueError):
                analyze(invalid)


if __name__ == "__main__":
    unittest.main()
