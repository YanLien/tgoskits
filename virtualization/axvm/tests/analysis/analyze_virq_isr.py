#!/usr/bin/env python3
"""Recompute counter-offset and injection-to-C-ISR observation intervals."""

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

from analyze_virq_host import analyze as analyze_host, measurement_source, measurement_count


CLOCK = re.compile(
    r"VIRQ_CLOCK_SAMPLE policy=(fair|fifo80) phase=(before|after) sequence=(\d+) "
    r"host_before=(\d+) guest_ticks=(\d+) host_after=(\d+) frequency_hz=(\d+)"
)
ISR = re.compile(
    r"VIRQ_ISR_SAMPLE policy=(fair|fifo80) sample=(\d+) submit_ticks=(\d+) "
    r"guest_ticks=(\d+)(?: guest_end_ticks=(\d+))? observed_ticks=(\d+) "
    r"frequency_hz=(\d+)"
    r"(?: deadline_ns=(\d+) deadline_miss=(true|false|unknown|na)"
    r" trace_loss=(0|1|unknown))?"
)
RUNTIME_SUMMARY = re.compile(
    r"VIRQ_RUNTIME_SUMMARY records=(\d+) dropped=(\d+) incomplete=(\d+)"
)


def records(log, marker, pattern, columns):
    result = []
    for line in log.splitlines():
        if marker not in line:
            continue
        match = pattern.search(line)
        if match is None or line[match.end():].strip():
            raise ValueError(f"malformed {marker}")
        row = dict(zip(columns, match.groups()))
        for key in row.keys() - {"policy", "phase"}:
            row[key] = int(row[key])
        result.append(row)
    return result


def isr_records(log):
    result = []
    for line in log.splitlines():
        if "VIRQ_ISR_SAMPLE" not in line:
            continue
        match = ISR.search(line)
        if match is None or line[match.end():].strip():
            raise ValueError("malformed VIRQ_ISR_SAMPLE")
        policy, sample, submit, guest, guest_end, observed, frequency, deadline, miss, loss = match.groups()
        result.append({
            "policy": policy,
            "sample": int(sample),
            "submit_ticks": int(submit),
            "guest_ticks": int(guest),
            "guest_end_ticks": int(guest_end) if guest_end is not None else None,
            "observed_ticks": int(observed),
            "frequency_hz": int(frequency),
            "deadline_ns": int(deadline) if deadline is not None else None,
            "deadline_miss": miss or "na",
            "trace_loss": (None if loss in (None, "unknown") else loss == "1"),
        })
    return result


def trace_loss_state(log):
    matches = [RUNTIME_SUMMARY.fullmatch(line.strip()) for line in log.splitlines()]
    matches = [match for match in matches if match is not None]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("duplicated runtime trace summary")
    _, dropped, incomplete = (int(value) for value in matches[0].groups())
    return bool(dropped or incomplete)


def stats(values):
    ordered = sorted(values)
    return {
        "median": statistics.median(ordered),
        "p95": ordered[math.ceil(len(ordered) * .95) - 1],
        "p99": ordered[math.ceil(len(ordered) * .99) - 1],
        "max": ordered[-1],
    }


def analyze(log):
    analyze_host(log)  # Retain the successful suite and declared sample-count gate.
    source = measurement_source(log)
    sample_count = measurement_count(log)
    probes = records(log, "VIRQ_CLOCK_SAMPLE", CLOCK,
                     ("policy", "phase", "sequence", "host_before", "guest_ticks", "host_after", "frequency_hz"))
    samples = isr_records(log)
    runtime_trace_loss = trace_loss_state(log)
    result = {}
    output = []
    for policy in ("fair", "fifo80"):
        selected = [p for p in probes if p["policy"] == policy]
        deliveries = [s for s in samples if s["policy"] == policy]
        expected = [("before", n) for n in range(1, 33)] + [("after", n) for n in range(34, 66)]
        if [(p["phase"], p["sequence"]) for p in selected] != expected:
            raise ValueError(f"incomplete, duplicate or reordered {policy} calibration")
        if [s["sample"] for s in deliveries] != list(range(1, sample_count + 1)):
            raise ValueError(f"incomplete, duplicate or reordered {policy} ISR samples")
        frequencies = {p["frequency_hz"] for p in selected + deliveries}
        if len(frequencies) != 1 or 0 in frequencies:
            raise ValueError("inconsistent or zero counter frequency")
        frequency = frequencies.pop()
        if any(p["host_before"] > p["host_after"] for p in selected):
            raise ValueError("counter moved backwards during calibration")
        low = max(p["host_before"] - p["guest_ticks"] for p in selected)
        high = min(p["host_after"] - p["guest_ticks"] for p in selected)
        if low > high:
            raise ValueError("clock offset intervals do not intersect")
        for sample in deliveries:
            start, end, guest = (sample[k] for k in ("submit_ticks", "observed_ticks", "guest_ticks"))
            if start > end:
                raise ValueError("counter moved backwards during delivery")
            lower = max(start, guest + low)
            upper = min(end, guest + high)
            if lower > upper:
                raise ValueError("ISR sample is outside the causal host window")
            row = dict(sample)
            row["source"] = source
            row["trace_loss"] = runtime_trace_loss if runtime_trace_loss is not None else sample["trace_loss"]
            if row["guest_end_ticks"] is not None:
                if row["guest_end_ticks"] < guest:
                    raise ValueError("ISR end timestamp precedes ISR start")
                if row["guest_end_ticks"] + low > end:
                    raise ValueError("ISR end timestamp is outside the Host observation window")
                duration_ticks = row["guest_end_ticks"] - guest
                row["isr_duration_lower_ns"] = duration_ticks * 1_000_000_000 // frequency
                row["isr_duration_upper_ns"] = (
                    duration_ticks * 1_000_000_000 + frequency - 1
                ) // frequency
            else:
                row["isr_duration_lower_ns"] = None
                row["isr_duration_upper_ns"] = None
            # Round outward to retain interval coverage under tick conversion.
            row["isr_lower_ns"] = (lower - start) * 1_000_000_000 // frequency
            row["isr_upper_ns"] = ((upper - start) * 1_000_000_000 + frequency - 1) // frequency
            row["observation_lower_ns"] = (end - upper) * 1_000_000_000 // frequency
            row["observation_upper_ns"] = ((end - lower) * 1_000_000_000 + frequency - 1) // frequency
            output.append(row)
        group = [s for s in output if s["policy"] == policy]
        duration_group = [s for s in group if s["isr_duration_lower_ns"] is not None]
        result[policy] = {
            "samples": len(group), "calibration_probes": len(selected),
            "frequency_hz": frequency, "offset_low_ticks": low, "offset_high_ticks": high,
            "offset_width_ns": (high - low) * 1_000_000_000 / frequency,
            "source": source,
            "trace_loss": runtime_trace_loss,
            ({"physical_timer_ppi": "timer_arm_to_c_isr_ns", "pl031_spi": "rtc_arm_to_c_isr_ns"}.get(source, "injection_to_c_isr_ns")): {
                "lower": stats([s["isr_lower_ns"] for s in group]),
                "upper": stats([s["isr_upper_ns"] for s in group]),
            },
            "c_isr_to_host_observation_ns": {
                "lower": stats([s["observation_lower_ns"] for s in group]),
                "upper": stats([s["observation_upper_ns"] for s in group]),
            },
            "isr_duration_ns": {
                "samples": len(duration_group),
                "lower": stats([s["isr_duration_lower_ns"] for s in duration_group])
                if duration_group else None,
                "upper": stats([s["isr_duration_upper_ns"] for s in duration_group])
                if duration_group else None,
            },
        }
    return output, probes, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        samples, probes, policies = analyze(args.log.read_text())
    except (OSError, ValueError) as error:
        parser.exit(1, f"invalid ISR measurement: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("samples.csv", samples), ("calibration.csv", probes)):
        with (args.output_dir / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary = {
        "units": "ns unless named ticks or Hz", "policies": policies,
        "limitations": [
            "QEMU instrumented observation; not a physical hardware performance result.",
            "Intervals assume a shared rate and constant host-minus-guest offset across the run.",
            "ISR means the first counter read in the Zephyr C ISR, after guest vector dispatch.",
            "ISR duration is available only when the Guest publishes its end counter; old logs retain null duration fields.",
            "trace_loss is authoritative when VIRQ_RUNTIME_SUMMARY is present; otherwise it remains unknown.",
            "Finite calibration cannot prove permanent synchronization or hard real-time bounds.",
            "Finite sample tails require a sufficiency audit; no performance comparison is established.",
        ],
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
