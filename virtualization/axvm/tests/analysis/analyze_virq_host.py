#!/usr/bin/env python3
"""Export host-side virtual interrupt samples from one successful axvm run."""

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path


SAMPLE = re.compile(
    r"VIRQ_HOST_SAMPLE policy=(fair|fifo80) sample=(\d+) "
    r"pulse_ns=(\d+) ack_observed_ns=(\d+)"
)
SOURCE = re.compile(r"VIRQ_SOURCE kind=(software|physical_timer_ppi|pl031_spi)")


def measurement_source(log):
    matches = []
    for line in log.splitlines():
        if "VIRQ_SOURCE" not in line:
            continue
        match = SOURCE.search(line)
        if match is None or line[match.end():].strip():
            raise ValueError("malformed interrupt source identity")
        matches.append(match.group(1))
    if len(matches) > 1:
        raise ValueError("duplicate interrupt source identity")
    return matches[0] if matches else "software"


def measurement_count(log):
    """Explicit new count or the fixed legacy contract; never infer from rows."""
    matches = []
    pattern = re.compile(r"VIRQ_MEASUREMENT samples_per_policy=(\d+)")
    for line in log.splitlines():
        if "VIRQ_MEASUREMENT" not in line:
            continue
        match = pattern.search(line)
        if match is None or line[match.end():].strip():
            raise ValueError("malformed measurement count")
        matches.append(int(match.group(1)))
    if len(matches) > 1 or (matches and not 1 <= matches[0] <= 1000):
        raise ValueError("duplicate or out-of-range measurement count")
    return matches[0] if matches else 300


def analyze(log: str) -> tuple[list[dict], dict]:
    source = measurement_source(log)
    expected = measurement_count(log)
    submit_field = {"physical_timer_ppi": "timer_arm_ns", "pl031_spi": "rtc_arm_ns"}.get(source, "pulse_ns")
    if len(re.findall(r"(?m)^AXTEST_SUITE_OK\s*$", log)) != 1:
        raise ValueError("expected exactly one AXTEST_SUITE_OK")
    if re.search(r"AXTEST_SUITE_FAIL|AXTEST_CASE status=fail|panicked at|SOFTWARE VIRQ FAIL", log):
        raise ValueError("the run contains a failure marker")
    rows = []
    grouped = {"fair": [], "fifo80": []}
    for line in log.splitlines():
        if "VIRQ_HOST_SAMPLE" not in line:
            continue
        match = SAMPLE.search(line)
        if match is None or line[match.end():].strip():
            raise ValueError(f"malformed sample: {line}")
        policy, index, pulse, ack = match.groups()
        index, pulse, ack = int(index), int(pulse), int(ack)
        if index != len(grouped[policy]) + 1 or index > expected:
            raise ValueError(f"out-of-order or duplicate sample: {policy} {index}")
        if ack < pulse:
            raise ValueError("confirmation cannot precede the submission call's return")
        row = dict(policy=policy, sample=index, source=source, **{submit_field: pulse}, ack_observed_ns=ack)
        grouped[policy].append(row)
        rows.append(row)
    summary = {}
    for policy, samples in grouped.items():
        if len(samples) != expected:
            raise ValueError(f"expected {expected} {policy} samples, got {len(samples)}")
        summary[policy] = {"samples": len(samples), "source": source}
        for field in (submit_field, "ack_observed_ns"):
            values = sorted(row[field] for row in samples)
            summary[policy][field] = dict(
                median=statistics.median(values),
                p95=values[math.ceil(len(values) * 0.95) - 1],
                p99=values[math.ceil(len(values) * 0.99) - 1],
                max=values[-1],
            )
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows, summary = analyze(args.log.read_text())
    except (OSError, ValueError) as error:
        parser.exit(1, f"invalid measurement run: {error}\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = dict(
        units="ns",
        quantiles="nearest-rank; median uses the two middle samples",
        limitation="Host observation includes 1 ms polling; neither metric is guest ISR latency. "
        "QEMU timing is not a hardware performance result; Finite sample tails require a separate sufficiency audit.",
        policies=summary,
    )
    (args.output_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
