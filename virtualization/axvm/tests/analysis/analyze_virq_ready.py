#!/usr/bin/env python3
"""Associate scheduler enqueue observations with the existing vCPU trace."""

import argparse
from collections import Counter
import csv
import json
import re
from pathlib import Path

from analyze_virq_isr import analyze as analyze_isr, stats
from analyze_virq_runtime import analyze as analyze_runtime, parse


READY_SUMMARY = re.compile(r"VIRQ_READY_SUMMARY records=(\d+)")
KINDS = {
    1: "direct_wake", 2: "on_run_queue_wake", 3: "owner_wake", 4: "owner_yield",
    5: "owner_preempted", 6: "owner_replenished", 7: "owner_migrated", 8: "owner_policy_changed",
}


def analyze(log):
    parent_rows, events, _, parent = analyze_runtime(log)
    isr_rows, _, clocks = analyze_isr(log)
    source = {(s["policy"], s["sample"]): s for s in isr_rows}
    ready = [dict(e) for e in events if e["kind"] == "ReadyEnqueue"]
    counts = parse(log, "VIRQ_READY_SUMMARY", READY_SUMMARY)
    if len(counts) != 1 or int(counts[0][0]) != len(ready) or not ready:
        raise ValueError("missing or inconsistent Ready capture")
    for event in ready:
        code = event["value1"] & 255
        if code not in KINDS or event["value1"] & ~511 or event["value0"] > 0xffff_ffff:
            raise ValueError("invalid Ready path, flags or destination CPU")
        event.update(path=KINDS[code], on_cpu=bool(event["value1"] & 256),
                     destination_cpu=event["value0"])
    output = []
    for base in parent_rows:
        row = dict(policy=base["policy"], sample=base["sample"], target_thread=base["target_thread"],
                   parent_status=base["status"], status="parent_path_not_serial", ready_candidates=0,
                   on_cpu_observations=0, ready_kind="", ready_observer_cpu="", destination_cpu="",
                   running_cpu="", wake_to_ready_ticks="", ready_to_running_ticks="", complete=False)
        if not base["full_chain"]:
            output.append(row)
            continue
        sample = source[(base["policy"], base["sample"])]
        kick = sample["submit_ticks"] + base["submit_to_irq_ticks"]
        wake = kick + base["irq_to_worker_ticks"]
        running = wake + base["worker_to_running_ticks"]
        window = [e for e in ready if e["thread"] == base["target_thread"] and wake <= e["ticks"] <= running]
        row["on_cpu_observations"] = sum(e["on_cpu"] for e in window)
        candidates = [e for e in window if not e["on_cpu"] and (e["value1"] & 255) in (1, 2, 3)]
        row["ready_candidates"] = len(candidates)
        if len(candidates) != 1:
            row["status"] = "missing_fresh_ready" if not candidates else "ambiguous_fresh_ready"
        else:
            selected = candidates[0]
            matching = [e for e in events if e["thread"] == base["target_thread"]
                        and e["kind"] == "Running" and e["ticks"] == running]
            if len(matching) != 1:
                row["status"] = "ambiguous_running_boundary"
            else:
                row.update(ready_kind=selected["path"], ready_observer_cpu=selected["cpu"],
                           destination_cpu=selected["destination_cpu"], running_cpu=matching[0]["cpu"])
                if selected["destination_cpu"] != matching[0]["cpu"]:
                    row["status"] = "destination_cpu_changed"
                else:
                    row.update(status="associated", complete=True,
                               wake_to_ready_ticks=selected["ticks"]-wake,
                               ready_to_running_ticks=running-selected["ticks"])
        output.append(row)
    policies = {}
    for policy, clock in clocks.items():
        rows = [r for r in output if r["policy"] == policy]
        complete = [r for r in rows if r["complete"]]
        hz = clock["frequency_hz"]
        policies[policy] = dict(
            samples=len(rows), ready_associated_samples=len(complete),
            statuses=dict(Counter(r["status"] for r in rows)),
            parent_statuses=dict(Counter(r["parent_status"] for r in rows if not r["complete"])),
            ready_paths=dict(Counter(r["ready_kind"] for r in complete)),
            cross_cpu_observations=sum(r["ready_observer_cpu"] != r["destination_cpu"] for r in complete),
            ready_observer_cpu_counts=dict(Counter(r["ready_observer_cpu"] for r in complete)),
            conditional_segments_ns={field.replace("_ticks", "_ns"): stats([r[field]*1e9/hz for r in complete])
                                     for field in ("wake_to_ready_ticks", "ready_to_running_ticks")} if complete else {},
        )
    summary = dict(records=len(events), ready_records=len(ready),
                   ready_paths=dict(Counter(e["path"] for e in ready)),
                   on_cpu_records=sum(e["on_cpu"] for e in ready), policies=policies,
                   limitations=[
                       "Ready is an rq-locked software observation before commit/unlock, not physical execution.",
                       "Only unique fresh wake enqueues are split; all declared sample statuses remain in the CSV.",
                       "Ready-to-Running includes remaining commit/unlock and dispatch costs, not pure queue-policy wait.",
                       "On-CPU requeue and non-wake reasons are retained in raw Ready events, not relabeled as fresh wakes.",
                       "QEMU only; no hardware bottleneck, performance improvement or hard real-time bound is established.",
                   ])
    return output, ready, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        samples, events, report = analyze(args.log.read_text())
    except (ValueError, OSError) as error:
        parser.exit(1, f"invalid Ready measurement: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("samples.csv", samples), ("ready-events.csv", events)):
        with (args.output_dir/name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (args.output_dir/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
