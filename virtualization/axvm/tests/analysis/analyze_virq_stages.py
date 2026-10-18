#!/usr/bin/env python3
"""Associate IRQ route and lower-EL timer synchronization with physical task samples."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from analyze_virq_physical import analyze as analyze_physical
from analyze_virq_isr import stats


def analyze(log):
    if "VIRQ_RECORDING mode=off " in log:
        raise ValueError("disabled recorder has no IRQ stage observations")
    rows, physical = analyze_physical(log)
    stages = physical["runtime"]["irq_stages"]
    if stages["version"] != 1 or not stages["observations_available"]:
        raise ValueError("physical IRQ stages require schema version 1 and actual observations")
    by_key = {(s["cpu"], s["intid"], s["entry_ticks"]): s for s in stages["entries"]}
    used = set()
    for row in rows:
        key = row["irq_cpu"], row["intid"], row["irq_entry_ticks"]
        if key not in by_key or key in used:
            raise ValueError("physical sample does not have a unique stage observation")
        used.add(key)
        span = by_key[key]
        hz = physical["policies"][row["policy"]]["clock"]["frequency_hz"]
        # analyze_physical already proves a unique source-CPU target IrqKick.
        kick_ticks = row["irq_kick_ticks"]
        if not span["dispatch_begin_ticks"] <= kick_ticks <= span["dispatch_end_ticks"]:
            raise ValueError("interrupt publication is outside its Host route")
        row.update({k: v for k, v in span.items() if k.endswith("_ticks") and k != "entry_ticks"})
        row["entry_to_dispatch_begin_ns"] = (span["dispatch_begin_ticks"]-key[2])*1e9/hz
        row["dispatch_ns"] = (span["dispatch_end_ticks"]-span["dispatch_begin_ticks"])*1e9/hz
        lower = span["entry_context"] == 2
        row["timer_sync_ns"] = ((span["timer_sync_end_ticks"]-span["timer_sync_begin_ticks"])*1e9/hz if lower else None)
        row["timer_end_to_dispatch_begin_ns"] = ((span["dispatch_begin_ticks"]-span["timer_sync_end_ticks"])*1e9/hz if lower else None)
        # Compare duration from the same T0 using outward-rounded ISR bounds.
        dispatch_end_ns = (span["dispatch_end_ticks"]-key[2])*1e9/hz
        row["dispatch_end_vs_isr"] = (
            "certainly_before" if dispatch_end_ns < row["entry_to_c_isr_lower_ns"]
            else "certainly_after" if dispatch_end_ns > row["entry_to_c_isr_upper_ns"]
            else "within_clock_uncertainty")
    if len(used) != len(by_key):
        raise ValueError("unassociated physical IRQ stages")
    policies = {}
    for policy in physical["policies"]:
        selected = [r for r in rows if r["policy"] == policy]
        policies[policy] = dict(
            samples=len(selected),
            contexts=dict(Counter(r["irq_entry_context"] for r in selected)),
            dispatch_end_vs_isr=dict(Counter(r["dispatch_end_vs_isr"] for r in selected)),
            intervals_ns={field: stats(values) if values else None for field in (
                "entry_to_dispatch_begin_ns", "dispatch_ns", "timer_sync_ns", "timer_end_to_dispatch_begin_ns")
                for values in ([r[field] for r in selected if r[field] is not None],)})
    return rows, dict(schema_version=1, samples=len(rows), policies=policies,
                      dropped=physical["runtime"]["dropped"], incomplete=physical["runtime"]["incomplete"],
                      M1=False, M2=False, new_probe_cost_quantified=False,
                      limitations=[
                          "Software Host route and lower-EL synchronize_timer intervals include instrumentation; no hardware IRQ-arrival or pure register-operation latency.",
                          "Current-EL timer synchronization is absent and represented by null, never zero.",
                          "Cross-CPU Ready/Running/ISR may overlap Host route; intervals are not additive path components.",
                          "The gap after timer synchronization includes VGIC saving and adapter work; no exclusive subsystem attribution.",
                          "New probes require fresh cost measurements; older recorder costs do not apply to this source version.",
                          "Descriptive observed distributions only; frequency, temperature, full T0-T6 coverage and hard bounds remain unverified.",
                      ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, report = analyze(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f"invalid IRQ stage measurement: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir/"samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
