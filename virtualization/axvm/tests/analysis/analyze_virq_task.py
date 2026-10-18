#!/usr/bin/env python3
"""Join Guest thread completion to calibrated ISR events and task deadlines."""

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

from analyze_virq_isr import analyze as analyze_isr
from analyze_virq_irq_pressure import validate_pressure, verify_window
from analyze_virq_linux_fence import validate_fences, verify_fence_window
from analyze_virq_physical import analyze as analyze_physical
from analyze_virq_periodic import annotate, workload_checksum


CONFIG = re.compile(r"VIRQ_TASK_CONFIG protocol=1 rounds=\d+ relative_deadline_ns=(\d+)"
                    r"(?: wait_mode=(spin|blocked))?")
TASK = re.compile(
    r"VIRQ_TASK_SAMPLE policy=(fair|fifo80) sample=(\d+) "
    r"start_ticks=(\d+) end_ticks=(\d+) checksum=(\d+) observed_ticks=(\d+)"
)
BACKGROUND = re.compile(r"VIRQ_TASK_BACKGROUND policy=(fair|fifo80) non_target_vcpu_returns=(\d+)")


def marked_records(log, marker, pattern):
    records = []
    for line in log.splitlines():
        if marker not in line:
            continue
        match = pattern.search(line)
        if match is None or line[match.end():].strip():
            raise ValueError(f"malformed {marker}")
        records.append(match.groups())
    return records


def stats(values):
    ordered = sorted(values)
    return {"mean": statistics.mean(ordered), "p50": statistics.median(ordered),
            "p99": ordered[math.ceil(len(ordered)*.99)-1],
            "p999": ordered[math.ceil(len(ordered)*.999)-1], "max": ordered[-1]}


def analyze(log):
    if 'VIRQ_RECORDING mode=off ' in log:
        raise ValueError('disabled recorder cannot establish a complete runtime chain')
    deliveries, _, clocks = analyze_isr(log)
    if any(clock["trace_loss"] is not False for clock in clocks.values()):
        raise ValueError("task analysis requires a complete loss-free runtime summary")
    entries = {}
    if deliveries[0]["source"] != "software":
        physical, _ = analyze_physical(log)
        entries = {(r["policy"], r["sample"]): r["irq_entry_ticks"] for r in physical}
    return join_completions(log, deliveries, clocks, entries)


def join_completions(log, deliveries, clocks, entries):
    """Validate task work and causal windows without inventing missing stages.

    Complete-chain callers must first validate runtime/physical observations;
    the recorder-cost caller deliberately retains unknown loss and absent T0.
    """
    pressure = validate_pressure(log)
    fences = validate_fences(log)
    configs = marked_records(log, "VIRQ_TASK_CONFIG", CONFIG)
    if len(configs) != 1 or int(configs[0][0]) <= 0:
        raise ValueError("one positive independent task deadline is required")
    deadline_ns = int(configs[0][0])
    rounds = int(re.search(r'VIRQ_TASK_CONFIG protocol=1 rounds=(\d+)', log)[1])
    if not 4096 <= rounds <= 1048576:
        raise ValueError('Invalid Guest task work size')
    samples = marked_records(log, "VIRQ_TASK_SAMPLE", TASK)
    background = marked_records(log, "VIRQ_TASK_BACKGROUND", BACKGROUND)
    if ((configs[0][1] is not None or background)
            and [p for p, _ in background] != ["fair", "fifo80"]):
        raise ValueError("new task modes require both background vCPU activity records")
    if configs[0][1] != "blocked" and any(int(count) for _, count in background):
        raise ValueError("non-target vCPU activity violates the spin-mode contract")
    if [(p, int(n)) for p, n, *_ in samples] != [(r["policy"], r["sample"]) for r in deliveries]:
        raise ValueError("task samples must match every ISR event exactly once in order")
    rows = []
    for sample, delivery in zip(samples, deliveries):
        policy, number, start, end, checksum, observed = sample
        number, start, end, checksum, observed = map(int, (number, start, end, checksum, observed))
        clock = clocks[policy]
        hz = clock["frequency_hz"]
        low, high = clock["offset_low_ticks"], clock["offset_high_ticks"]
        if delivery["guest_end_ticks"] is None:
            raise ValueError("task chain requires the Guest ISR end timestamp")
        if not delivery["guest_end_ticks"] <= start <= end:
            raise ValueError("task starts before ISR end or completes before starting")
        if checksum != workload_checksum(rounds):
            raise ValueError("Guest task result failed the independent known-answer check")
        submitted = delivery["submit_ticks"]
        verify_window(pressure, policy, submitted, observed, hz)
        if observed < delivery["observed_ticks"] or end+low > observed or start+high < submitted:
            raise ValueError("task timestamps violate their causal Host observation window")
        lower = max(submitted, end+low)
        upper = min(observed, end+high)
        if lower > upper:
            raise ValueError("task clock interval does not intersect its Host window")
        latency_low = (lower-submitted)*1_000_000_000
        latency_high = (upper-submitted)*1_000_000_000
        miss = ("true" if latency_low > deadline_ns*hz else
                "false" if latency_high <= deadline_ns*hz else "unknown")
        entry = entries.get((policy, number))
        if entry is not None and entry > lower:
            raise ValueError("task completion is not certainly after physical IRQ entry")
        rows.append(dict(
            policy=policy, sample=number, source=delivery["source"],
            submit_ticks=submitted, task_start_ticks=start, task_end_ticks=end,
            host_task_observed_ticks=observed, frequency_hz=hz,
            guest_isr_ticks=delivery['guest_ticks'], guest_isr_end_ticks=delivery['guest_end_ticks'],
            host_isr_observed_ticks=delivery['observed_ticks'],
            task_checksum=checksum, task_execution_ns=(end-start)*1e9/hz,
            isr_end_to_task_start_ns=(start-delivery["guest_end_ticks"])*1e9/hz,
            submit_to_completion_lower_ns=latency_low//hz,
            submit_to_completion_upper_ns=(latency_high+hz-1)//hz,
            irq_entry_to_completion_lower_ns=(lower-entry)*1_000_000_000//hz if entry is not None else None,
            irq_entry_to_completion_upper_ns=((upper-entry)*1_000_000_000+hz-1)//hz if entry is not None else None,
            task_relative_deadline_ns=deadline_ns, task_deadline_miss=miss,
            trace_loss=clock['trace_loss'],
        ))
    periodic = annotate(log, rows, clocks, deadline_ns, rounds)
    if periodic and configs[0][1] != 'blocked':
        raise ValueError('Periodic jobs require the counted blocked-task mode')
    if periodic:
        for row in rows:
            verify_window(pressure, row['policy'], row['scheduled_release_ticks'],
                          row['host_task_observed_ticks'], row['frequency_hz'])
    for row in rows:
        verify_fence_window(fences, row['policy'],
                            row.get('scheduled_release_ticks', row['submit_ticks']),
                            row['host_task_observed_ticks'], row['frequency_hz'])
    policies = {}
    for policy in clocks:
        group = [r for r in rows if r["policy"] == policy]
        counts = {k: sum(r["task_deadline_miss"] == k for r in group)
                  for k in ("true", "false", "unknown")}
        policies[policy] = dict(
            samples=len(group), deadline_miss_counts=counts,
            deadline_miss_ratio_lower=counts["true"]/len(group),
            deadline_miss_ratio_upper=(counts["true"]+counts["unknown"])/len(group),
        )
        for metric in ("task_execution_ns", "isr_end_to_task_start_ns",
                       "submit_to_completion_lower_ns", "submit_to_completion_upper_ns",
                       "irq_entry_to_completion_lower_ns", "irq_entry_to_completion_upper_ns",
                       *(('release_to_completion_lower_ns', 'release_to_completion_upper_ns', 'release_lateness_ns') if periodic else ())):
            values = [r[metric] for r in group if r[metric] is not None]
            policies[policy][metric] = stats(values) if values else None
    return rows, dict(
        units="ns unless named ticks or Hz", task_deadline_origin="scheduled_release" if periodic else "host_submit",
        periodic=periodic, linux_fences=fences, task_rounds=rounds,
        task_wait_mode=configs[0][1] or "spin_legacy",
        non_target_vcpu_returns={policy: int(count) for policy, count in background},
        task_relative_deadline_ns=deadline_ns, policies=policies,
        limitations=[
            ("Host fixed-plan arrivals with ISR-serialized physical admission; not externally timed hardware arrivals." if periodic else "Event-driven one-outstanding-task fixture; not periodic release or queueing evidence."),
            "Task completion is a Guest thread timestamp after a fixed known-answer workload, not a device output timestamp.",
            "Host-submit latency includes timer programming-to-trigger delay for physical timer sources.",
            "Miss-ratio bounds express clock-classification uncertainty, not statistical confidence intervals.",
            "Quantiles are descriptive; finite samples do not establish WCET, WCRT, or hardware performance.",
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, summary = analyze(args.log.read_text())
    except (OSError, ValueError) as error:
        parser.exit(1, f"invalid task measurement: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir/"samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
