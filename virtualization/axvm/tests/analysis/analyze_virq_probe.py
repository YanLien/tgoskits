#!/usr/bin/env python3
"""Validate a declared probe state without inventing wake/IRQ decomposition."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re

from analyze_virq_isr import analyze as analyze_isr
from analyze_virq_host import measurement_count
from analyze_virq_runtime import EVENT, SUMMARY, parse

PROFILE = re.compile(r"VIRQ_PROBE_PROFILE compiled=([01]) enabled=([01])")
STATES = {"uncompiled": (0, 0), "disabled": (1, 0), "enabled": (1, 1)}


def analyze(log, expected):
    if expected not in STATES:
        raise ValueError("unknown probe state")
    profiles = parse(log, "VIRQ_PROBE_PROFILE", PROFILE)
    if len(profiles) != 1 or tuple(map(int, profiles[0])) != STATES[expected]:
        raise ValueError("observed probe state does not match the requested experiment")
    rows, calibration, clocks = analyze_isr(log)
    events = parse(log, "VIRQ_RUNTIME ", EVENT)
    summaries = parse(log, "VIRQ_RUNTIME_SUMMARY", SUMMARY)
    counts = Counter(e[3] for e in events)
    if expected != "enabled":
        if events or summaries:
            raise ValueError("inactive probe state unexpectedly exported a capture")
    else:
        if len(summaries) != 1 or tuple(map(int, summaries[0])) != (len(events), 0, 0):
            raise ValueError("enabled probe has missing, incomplete or dropped capture")
        next_sequence, previous_ticks = Counter(), {}
        for cpu, sequence, ticks, *_ in events:
            cpu, sequence, ticks = map(int, (cpu, sequence, ticks))
            if (cpu not in (0, 1) or sequence != next_sequence[cpu]
                    or ticks < previous_ticks.get(cpu, 0)):
                raise ValueError("probe CPU stream has a gap, duplicate or reversed clock")
            next_sequence[cpu] += 1
            previous_ticks[cpu] = ticks
        if (counts["Binding"] < 8 or counts["IrqKick"] < measurement_count(log) * 2
                or not counts["ReadyEnqueue"] or not counts["Running"]):
            raise ValueError("enabled probe did not observe the real VM lifecycle")
    return rows, calibration, {
        "profile": expected, "compiled": STATES[expected][0],
        "enabled": STATES[expected][1], "samples": len(rows),
        "calibration_probes": len(calibration), "clocks": clocks,
        "capture_records": len(events), "capture_event_counts": dict(counts),
        "limitations": [
            "This checker validates probe state and stream completeness, not a full wake-to-ISR decomposition.",
            "Disabled capture retains compiled branches and unconditional low-EL counter instructions.",
            "Source, Guest and binary matching require the separate provenance artifacts.",
            "QEMU differences do not establish hardware instrumentation overhead or mechanism benefit.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--profile", required=True, choices=STATES)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        rows, calibration, report = analyze(args.log.read_text(), args.profile)
    except (ValueError, OSError) as error:
        parser.exit(1, f"invalid probe experiment: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, records in (("samples", rows), ("calibration", calibration)):
        with (args.output_dir/f"{name}.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    (args.output_dir/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
