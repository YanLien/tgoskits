#!/usr/bin/env python3
"""Associate bounded vCPU runtime events with calibrated ISR samples."""

import argparse
from collections import Counter
import csv
import json
import re
from pathlib import Path

from analyze_virq_isr import analyze as analyze_isr, stats
from virq_irq_stages import STAGE_KINDS, validate_stages


EVENT = re.compile(
    r"VIRQ_RUNTIME cpu=(\d+) sequence=(\d+) ticks=(\d+) "
    r"kind=(Binding|IrqKick|WakeBegin|WakeEnd|Running|Stopped|GuestEntryBoundary|Marker|ReadyEnqueue|HostIrqEntry|IrqDispatchBegin|IrqDispatchEnd|TimerSyncBegin|TimerSyncEnd) "
    r"thread=(\d+) value0=(\d+) value1=(\d+)"
)
SUMMARY = re.compile(r"VIRQ_RUNTIME_SUMMARY records=(\d+) dropped=(\d+) incomplete=(\d+)")
ENVELOPE = re.compile(r"VIRQ_TRACE_ENVELOPE sample=(\d+) ticks=(\d+) frequency_hz=(\d+)")


def parse(log, marker, pattern):
    rows = []
    for line in log.splitlines():
        if marker not in line:
            continue
        match = pattern.search(line)
        if match is None or line[match.end():].strip():
            raise ValueError(f"malformed {marker}")
        rows.append(match.groups())
    return rows


def analyze(log):
    samples, _, calibrated = analyze_isr(log)
    raw = parse(log, "VIRQ_RUNTIME ", EVENT)
    summary = parse(log, "VIRQ_RUNTIME_SUMMARY", SUMMARY)
    if len(summary) != 1:
        raise ValueError("expected one runtime trace summary")
    declared, dropped, incomplete = map(int, summary[0])
    if declared != len(raw) or dropped or incomplete:
        raise ValueError("runtime capture is incomplete or lost records")
    events = []
    cpu_counts, cpu_ticks = Counter(), {}
    bindings = {}
    for cpu, sequence, ticks, kind, thread, value0, value1 in raw:
        cpu, sequence, ticks, thread, value0, value1 = map(int, (cpu, sequence, ticks, thread, value0, value1))
        if sequence != cpu_counts[cpu] or ticks < cpu_ticks.get(cpu, 0):
            raise ValueError("runtime records have a gap, duplicate or reversed CPU clock")
        cpu_counts[cpu] += 1
        cpu_ticks[cpu] = ticks
        event = dict(cpu=cpu, sequence=sequence, ticks=ticks, kind=kind,
                     thread=thread, value0=value0, value1=value1)
        events.append(event)
        if kind == "Binding":
            if thread in bindings:
                raise ValueError("thread generation has duplicate bindings")
            bindings[thread] = (value0, value1)
    if any(e["kind"] == "HostIrqEntry" and (e["thread"] != 0 or e["value1"] not in (1, 2)) for e in events):
        raise ValueError("invalid physical IRQ entry observation")
    if not events or any(e["kind"] not in ({"Marker", "HostIrqEntry"} | STAGE_KINDS) and e["thread"] not in bindings for e in events):
        raise ValueError("runtime events have no vCPU owner binding")
    irq_stages = validate_stages(log, events)
    envelopes = [dict(sample=int(n), ticks=int(t), frequency_hz=int(f))
                 for n, t, f in parse(log, "VIRQ_TRACE_ENVELOPE", ENVELOPE)]
    if [e["sample"] for e in envelopes] != list(range(1, 129)):
        raise ValueError("incomplete probe-envelope measurements")
    frequencies = {p["frequency_hz"] for p in calibrated.values()}
    if len(frequencies) != 1 or any(e["frequency_hz"] not in frequencies for e in envelopes):
        raise ValueError("probe envelope uses a different counter frequency")
    markers = [e["value0"] for e in events if e["kind"] == "Marker"]
    if sorted(markers) != list(range(128)):
        raise ValueError("missing or duplicate envelope markers")
    timeline = sorted(events, key=lambda e: (e["ticks"], e["cpu"], e["sequence"]))
    rows = []
    for sample in samples:
        policy = calibrated[sample["policy"]]
        start, end, guest = (sample[k] for k in ("submit_ticks", "observed_ticks", "guest_ticks"))
        low = max(start, guest + policy["offset_low_ticks"])
        high = min(end, guest + policy["offset_high_ticks"])
        row = dict(policy=sample["policy"], sample=sample["sample"],
                   target_thread="", status="missing_irq_request", state_at_submit="unknown",
                   irq_requests=0, worker_wakes=0, running_edges=0, entry_boundaries=0,
                   wake_end_after_running=False, full_chain=False,
                   submit_to_irq_ticks="", irq_to_worker_ticks="", worker_to_running_ticks="",
                   running_to_entry_ticks="", entry_to_isr_lower_ticks="", entry_to_isr_upper_ticks="")
        candidates = [e for e in timeline if e["kind"] == "IrqKick"
                      and start <= e["ticks"] <= high and bindings[e["thread"]] == (2, 1)]
        row["irq_requests"] = len(candidates)
        if len(candidates) != 1:
            if len(candidates) > 1:
                row["status"] = "ambiguous_irq_requests"
            rows.append(row)
            continue
        kick = candidates[0]
        row["target_thread"] = kick["thread"]
        if kick["ticks"] > low:
            row["status"] = "irq_within_clock_uncertainty"
            rows.append(row)
            continue
        target = [e for e in timeline if e["thread"] == kick["thread"]]
        previous = [e for e in target if e["kind"] in ("Running", "Stopped") and e["ticks"] < start]
        if previous:
            row["state_at_submit"] = previous[-1]["kind"].lower()
        window = [e for e in target if kick["ticks"] <= e["ticks"] <= high]
        wakes = [e for e in window if e["kind"] == "WakeBegin" and e["ticks"] <= low]
        runs = [e for e in window if e["kind"] == "Running" and e["ticks"] <= low]
        entries = [e for e in window if e["kind"] == "GuestEntryBoundary"]
        row.update(status="associated", worker_wakes=len(wakes), running_edges=len(runs),
                   entry_boundaries=len(entries), submit_to_irq_ticks=kick["ticks"]-start)
        if not wakes or not runs or not entries:
            row["status"] = ("running_no_new_switch" if not runs and row["state_at_submit"] == "running"
                             else "missing_worker_running_or_entry")
        elif entries[-1]["ticks"] > low:
            row["status"] = "entry_within_clock_uncertainty"
        else:
            wake, running, entry = wakes[0], runs[0], entries[-1]
            row["wake_end_after_running"] = any(e["kind"] == "WakeEnd" and e["ticks"] > running["ticks"] for e in window)
            if running["ticks"] < wake["ticks"] or entry["ticks"] < running["ticks"]:
                row["status"] = "nonserial_wake_running_path"
            else:
                row.update(full_chain=True,
                           irq_to_worker_ticks=wake["ticks"]-kick["ticks"],
                           worker_to_running_ticks=running["ticks"]-wake["ticks"],
                           running_to_entry_ticks=entry["ticks"]-running["ticks"],
                           entry_to_isr_lower_ticks=low-entry["ticks"],
                           entry_to_isr_upper_ticks=high-entry["ticks"])
        rows.append(row)
    policies = {}
    segments = ("submit_to_irq_ticks", "irq_to_worker_ticks", "worker_to_running_ticks",
                "running_to_entry_ticks", "entry_to_isr_lower_ticks", "entry_to_isr_upper_ticks")
    for name, clock in calibrated.items():
        selected = [r for r in rows if r["policy"] == name]
        complete = [r for r in selected if r["full_chain"]]
        hz = clock["frequency_hz"]
        policies[name] = dict(
            samples=len(selected), full_chain_samples=len(complete),
            statuses=dict(Counter(r["status"] for r in selected)),
            states_at_submit=dict(Counter(r["state_at_submit"] for r in selected)),
            wake_end_after_running=sum(r["wake_end_after_running"] for r in selected),
            conditional_segments_ns={field.replace("_ticks", "_ns"): stats([r[field]*1e9/hz for r in complete])
                                     for field in segments} if complete else {},
        )
    hz = next(iter(frequencies))
    report = dict(irq_stages=irq_stages, records=len(events), dropped=dropped, incomplete=incomplete,
                  event_kinds=dict(Counter(e["kind"] for e in events)), policies=policies,
                  probe_envelope_ns=stats([e["ticks"]*1e9/hz for e in envelopes]),
                  limitations=[
                      "QEMU observations; no hardware bottleneck or optimization claim.",
                      "WakeBegin/End bracket the wake transaction; explicit Ready/enqueue observations are analyzed separately by analyze_virq_ready.",
                      "Segment statistics are conditional on full-chain association; all declared sample statuses are retained.",
                      "First Running and last certain Entry bracket inclusive work and possible intervening preemption.",
                      "Probe envelope includes timestamp reads and may include preemption; not pure probe overhead.",
                  ])
    return rows, events, envelopes, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, events, envelopes, report = analyze(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f"invalid runtime measurement: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (("samples.csv", rows), ("events.csv", events), ("envelopes.csv", envelopes)):
        with (args.output_dir/name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(content[0]))
            writer.writeheader()
            writer.writerows(content)
    (args.output_dir/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
