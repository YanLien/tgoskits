#!/bin/sh
set -eu

archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
analysis_dir="$repo_dir/virtualization/axvm/tests/analysis"
raw_log="$archive_dir/raw/software-baseline-600.log"
out_dir="$archive_dir/results/replay/software-baseline-600"

mkdir -p "$out_dir/host" "$out_dir/isr"
python3 "$analysis_dir/analyze_virq_host.py" "$raw_log" --output-dir "$out_dir/host"
python3 "$analysis_dir/analyze_virq_isr.py" "$raw_log" --output-dir "$out_dir/isr"

python3 - "$out_dir" <<'PY'
import json
import math
import statistics
import sys
from pathlib import Path

root = Path(sys.argv[1])
host = json.loads((root / "host" / "summary.json").read_text())
isr = json.loads((root / "isr" / "summary.json").read_text())

def nearest(values, quantile):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]

report = {
    "source": "software",
    "host_samples_total": sum(v["samples"] for v in host["policies"].values()),
    "guest_isr_samples_total": sum(v["samples"] for v in isr["policies"].values()),
    "host_ack_observed_excluded_from_isr": True,
    "policies": {},
    "limitations": [
        "This is an archived QEMU software-interrupt baseline, not a hardware performance result.",
        "Host pulse and ack_observed_ns are retained for provenance; ack_observed_ns is not ISR latency.",
        "ISR intervals rely on the shared-rate, intersecting clock calibration and do not establish WCET/WCRT.",
        "The 600 host samples are 300 Fair plus 300 FIFO samples from one archived run.",
    ],
}
for policy in ("fair", "fifo80"):
    rows = []
    with (root / "isr" / "samples.csv").open(newline="") as stream:
        import csv
        for row in csv.DictReader(stream):
            if row["policy"] == policy:
                rows.append(row)
    report["policies"][policy] = {
        "host_samples": host["policies"][policy]["samples"],
        "guest_isr_samples": isr["policies"][policy]["samples"],
        "calibration_offset_width_ns": isr["policies"][policy]["offset_width_ns"],
        "isr_lower_ns": {q: nearest([int(r["isr_lower_ns"]) for r in rows], p)
                         for q, p in (("p50", .50), ("p95", .95), ("p99", .99), ("max", 1.0))},
        "isr_upper_ns": {q: nearest([int(r["isr_upper_ns"]) for r in rows], p)
                         for q, p in (("p50", .50), ("p95", .95), ("p99", .99), ("max", 1.0))},
        "host_ack_observed_ns": host["policies"][policy]["ack_observed_ns"],
    }
(root / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
PY
