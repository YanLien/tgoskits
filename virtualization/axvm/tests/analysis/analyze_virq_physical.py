#!/usr/bin/env python3
"""Validate classified pre-IAR host PPI/SPI observations to Guest C ISR."""

import argparse
from collections import Counter
import csv
import json
import re
from pathlib import Path

from analyze_virq_host import measurement_source, measurement_count
from analyze_virq_isr import analyze as analyze_isr, stats
from analyze_virq_load import analyze as analyze_load
from analyze_virq_runtime import analyze as analyze_runtime, parse

ARM = re.compile(r"VIRQ_PHYSICAL_ARM policy=(fair|fifo80) sample=(\d+) due_ticks=(\d+) intid=(\d+) cpu=(\d+)")
SUMMARY = re.compile(r"VIRQ_PHYSICAL_SUMMARY policy=(fair|fifo80) intid=(\d+) cpu=(\d+) handled=(\d+) errors=(\d+) retired=(\d+)")
EXECUTION = re.compile(r"VIRQ_GUEST_EXECUTION mode=running target_cpu=1 controller_policy=default service_cpu=2 irq_cpu=1")
RTC_ARM = re.compile(r"VIRQ_RTC_ARM policy=(fair|fifo80) sample=(\d+) match_seconds=(\d+) intid=(\d+) cpu=(\d+)")
RTC_SUMMARY = re.compile(r"VIRQ_RTC_SUMMARY policy=(fair|fifo80) intid=(\d+) cpu=(\d+) handled=(\d+) errors=(\d+) retired=(\d+) restored_mr=0 imsc=0 ris=0 mis=0")
RTC_CONFIG = re.compile(r"VIRQ_RTC_CONFIG base=0x9010000 intid=34 cpu=0 target_cpu=1 initial_mr=0 imsc=0 ris=0 mis=0")


def analyze(log):
    source_kind = measurement_source(log)
    sample_count = measurement_count(log)
    rtc = source_kind == "pl031_spi"
    if source_kind not in ("physical_timer_ppi", "pl031_spi"):
        raise ValueError("physical analysis requires an explicit physical source")
    foreign = ("VIRQ_PHYSICAL_ARM", "VIRQ_PHYSICAL_SUMMARY") if rtc else ("VIRQ_RTC_",)
    if any(marker in log for marker in foreign):
        raise ValueError("mixed physical source cohorts")
    if "VIRQ_PHYSICAL_CLEANUP_FAILED" in log or "VIRQ_RTC_CLEANUP_FAILED" in log:
        raise ValueError("physical source cleanup failed")
    samples, _, clocks = analyze_isr(log)
    _, events, _, runtime = analyze_runtime(log)
    load_samples, loaded = analyze_load(log)
    execution = parse(log, "VIRQ_GUEST_EXECUTION", EXECUTION)
    if len(execution) > 1:
        raise ValueError("duplicated guest execution profile")
    guest_running = bool(execution)
    if rtc and (guest_running or len(parse(log, "VIRQ_RTC_CONFIG", RTC_CONFIG)) != 2):
        raise ValueError("RTC source needs its exact current-EL device configuration")
    intid = 34 if rtc else 30
    target_cpu = 1
    source_cpu = 1 if guest_running else 0
    if guest_running and (loaded["scenario"] not in ("baseline", "memory_cross_core")
                          or loaded["service_placement"]["mode"] != "cpu2"
                          or not loaded["service_placement"]["verified"]):
        raise ValueError("guest-running profile has no verified dedicated service CPU")
    if guest_running and loaded["scenario"] == "memory_cross_core":
        if any(load["cpu"] != 3 for load in loaded["loads"].values()):
            raise ValueError("guest-running memory worker must be separate from CPU2 services")
    load_by_sample = {(r["policy"], r["sample"]): r for r in load_samples}
    raw = parse(log, "VIRQ_RTC_ARM" if rtc else "VIRQ_PHYSICAL_ARM", RTC_ARM if rtc else ARM)
    arm = {}
    for policy in ("fair", "fifo80"):
        selected = [s for s in raw if s[0] == policy]
        if len(selected) != sample_count or [int(s[1]) for s in selected] != list(range(1, sample_count + 1)):
            raise ValueError("missing or duplicated physical timer arms")
        for _, index, due, intid, cpu in selected:
            if int(intid) != (34 if rtc else 30) or int(cpu) != source_cpu:
                raise ValueError("unexpected physical source identity")
            arm[(policy, int(index))] = int(due)
    summaries = parse(log, "VIRQ_RTC_SUMMARY" if rtc else "VIRQ_PHYSICAL_SUMMARY", RTC_SUMMARY if rtc else SUMMARY)
    intid = 34 if rtc else 30
    if len(summaries) != 2 or {s[0] for s in summaries} != {"fair", "fifo80"}:
        raise ValueError("missing physical source retirement summaries")
    if any(tuple(map(int, s[1:])) != (intid, source_cpu, sample_count, 0, 1) for s in summaries):
        raise ValueError("physical source count, errors or retirement mismatch")
    entries = [e for e in events if e["kind"] == "HostIrqEntry"]
    allowed = (1, 2) if guest_running else (1,)
    if len(entries) != sample_count * 2 or any((e["cpu"], e["thread"], e["value0"]) != (source_cpu, 0, intid)
                                 or e["value1"] not in allowed for e in entries):
        raise ValueError("expected the declared number of complete, correctly classified physical IRQ entries")
    bindings = {e["thread"]: (e["value0"], e["value1"]) for e in events if e["kind"] == "Binding"}
    if any(e["kind"] in ("Running", "GuestEntryBoundary") and bindings.get(e["thread"]) == (2, 1)
           and e["cpu"] != target_cpu for e in events):
        raise ValueError("physical fixture target vCPU left its declared CPU")
    rows, used = [], set()
    for sample in samples:
        policy, index = sample["policy"], sample["sample"]
        clock = clocks[policy]
        start, end, guest = (sample[k] for k in ("submit_ticks", "observed_ticks", "guest_ticks"))
        window = [e for e in entries if start <= e["ticks"] <= end]
        if len(window) != 1:
            raise ValueError("sample has no unique physical IRQ entry")
        entry = window[0]
        identity = entry["cpu"], entry["sequence"]
        if identity in used:
            raise ValueError("physical IRQ entry reused across samples")
        used.add(identity)
        due = arm[(policy, index)]
        if not rtc and not start < due <= entry["ticks"]:
            raise ValueError("physical IRQ entry precedes its programmed deadline")
        if rtc and (not start <= entry["ticks"] or not 0 <= due < (1 << 32)):
            raise ValueError("RTC ingress or match seconds outside its domain")
        low = max(entry["ticks"], guest + clock["offset_low_ticks"])
        high = min(end, guest + clock["offset_high_ticks"])
        if low > high:
            raise ValueError("physical entry and ISR violate calibrated causality")
        kicks = [e for e in events if e["kind"] == "IrqKick"
                 and bindings[e["thread"]] == (2, 1) and entry["ticks"] <= e["ticks"] <= high]
        if len(kicks) != 1 or kicks[0]["ticks"] > low or kicks[0]["cpu"] != source_cpu:
            raise ValueError("no unique certainly post-entry, pre-ISR interrupt publication")
        if entry["value1"] == 2:
            history = [e for e in events if e["thread"] == kicks[0]["thread"]
                       and e["kind"] in ("Running", "Stopped") and e["ticks"] <= entry["ticks"]]
            previous = max(history, key=lambda e: e["ticks"], default=None)
            if previous is None or previous["kind"] != "Running" or previous["cpu"] != source_cpu:
                raise ValueError("low-EL entry has no running target vCPU provenance")
        hz = clock["frequency_hz"]
        row = dict(load_by_sample[(policy, index)])
        row.update(sample)
        row["arm_to_c_isr_lower_ns"] = row.pop("isr_lower_ns")
        row["arm_to_c_isr_upper_ns"] = row.pop("isr_upper_ns")
        row.update(irq_entry_ticks=entry["ticks"],
                   irq_entry_context="lower_el_pre_iar" if entry["value1"] == 2 else "current_el_callback",
                   irq_entry_sequence=entry["sequence"], intid=intid, irq_cpu=source_cpu,
                   arm_to_entry_ns=(entry["ticks"]-start)*1e9/hz,
                   entry_to_kick_ns=(kicks[0]["ticks"]-entry["ticks"])*1e9/hz,
                   entry_to_c_isr_lower_ns=(low-entry["ticks"])*1_000_000_000//hz,
                   entry_to_c_isr_upper_ns=((high-entry["ticks"])*1_000_000_000+hz-1)//hz)
        if rtc:
            row["rtc_match_seconds"] = due
        else:
            row.update(due_ticks=due, deadline_to_entry_ns=(entry["ticks"]-due)*1e9/hz)
        rows.append(row)
    if len(used) != len(entries):
        raise ValueError("unassociated physical IRQ entries")
    policies = {}
    for policy, clock in clocks.items():
        group = [r for r in rows if r["policy"] == policy]
        contexts = dict(Counter(r["irq_entry_context"] for r in group))
        if guest_running and not contexts.get("lower_el_pre_iar", 0):
            raise ValueError("guest-running policy captured no low-EL IRQ entry")
        policies[policy] = dict(
            samples=len(group), clock=clock, irq_entry_context_counts=contexts,
            by_entry_context={context: {
                field: stats([r[field] for r in group if r["irq_entry_context"] == context])
                for field in ("entry_to_kick_ns", "entry_to_c_isr_lower_ns", "entry_to_c_isr_upper_ns")
            } for context in contexts},
            intervals_ns={field: stats([r[field] for r in group]) for field in (
                "arm_to_entry_ns", "deadline_to_entry_ns", "entry_to_kick_ns",
                "entry_to_c_isr_lower_ns", "entry_to_c_isr_upper_ns") if field in group[0]})
    return rows, dict(source=source_kind, execution_context="guest_running" if guest_running else "current_el",
                      target_cpu=target_cpu, source_cpu=source_cpu, policies=policies,
                      runtime=runtime, load_and_ready=loaded,
                      limitations=[
                          "Current-EL starts at the pre-IAR HostGuestTrap callback after GPR save/Rust wrapper; low-EL starts in assembly after GPR save, before IAR.",
                          ("This is a host-owned QEMU peripheral SPI forwarded to vector48, not pin-arrival latency or device passthrough. RTC seconds are not host comparator deadlines." if rtc else
                           "This is an internal physical timer PPI, not external device SPI or pin-arrival latency."),
                          "Entry origins remain classified per sample and in stratified summaries; neither point is vector-first-instruction or pin arrival.",
                          "Guest-running uses CPU1 PPI, busy target Guest and CPU2 services; its source/controller topology differs from the cross-core suspend case.",
                          ("One outstanding immediate RTC alarm at a time is not a periodic interrupt-rate experiment." if rtc else
                           "One outstanding 1ms comparator deadline at a time is not a periodic 1kHz throughput experiment."),
                          "QEMU functional and measurement evidence; hardware performance and hard real-time bounds remain unproven.",
                      ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, report = analyze(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f"invalid physical IRQ measurement: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir/"samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
