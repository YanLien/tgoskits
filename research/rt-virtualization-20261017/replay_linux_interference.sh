#!/bin/sh
set -eu

archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
analysis_dir="$repo_dir/virtualization/axvm/tests/analysis"
raw_log="$archive_dir/raw/linux-interference-600.log"
out_dir="$archive_dir/results/replay/linux-interference-600"

mkdir -p "$out_dir/physical" "$out_dir/runtime" "$out_dir/ready"
python3 "$analysis_dir/analyze_virq_physical.py" "$raw_log" --output-dir "$out_dir/physical"
python3 "$analysis_dir/audit_virq_tail.py" \
    "$out_dir/physical/samples.csv" --metric entry_to_c_isr \
    --output "$out_dir/tail.json"
python3 "$analysis_dir/analyze_virq_runtime.py" "$raw_log" --output-dir "$out_dir/runtime"
python3 "$analysis_dir/analyze_virq_ready.py" "$raw_log" --output-dir "$out_dir/ready"

python3 - "$out_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
physical = json.loads((root / "physical" / "summary.json").read_text())
runtime = json.loads((root / "runtime" / "summary.json").read_text())
ready = json.loads((root / "ready" / "summary.json").read_text())
report = {
    "source": physical["source"],
    "scenario": physical["load_and_ready"]["scenario"],
    "service_placement": physical["load_and_ready"]["service_placement"],
    "policies": {},
    "limitations": [
        "This is a QEMU Linux-Guest CPU interference fixture, not a hardware shared-memory result.",
        "The Linux Guest runs on Host CPU3 while the measured vCPU and services use the declared fixture CPUs.",
        "Linux batch counts establish workload progress, not exact DRAM traffic or CPU utilization.",
        "The 1 ms Host observation window is excluded from Guest ISR latency.",
    ],
}
for policy in ("fair", "fifo80"):
    p = physical["policies"][policy]
    load = physical["load_and_ready"]["loads"][policy]
    r = runtime["policies"][policy]
    q = ready["policies"][policy]
    report["policies"][policy] = {
        "samples": p["samples"],
        "calibration_offset_width_ns": p["clock"]["offset_width_ns"],
        "entry_to_c_isr_p99_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["p99"],
        "entry_to_c_isr_max_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["max"],
        "host_observation_p99_upper_ns": p["clock"]["c_isr_to_host_observation_ns"]["upper"]["p99"],
        "runtime_segments_p99_ns": {
            k: v["p99"] for k, v in r["conditional_segments_ns"].items()
        },
        "ready_segments_p99_ns": {
            k: v["p99"] for k, v in q["conditional_segments_ns"].items()
        },
        "linux_workload": {
            "start_batches": load["start_batches"],
            "end_batches": load["end_batches"],
            "final_reported_batches": load["final_reported_batches"],
            "samples_with_progress": load["samples_with_progress"],
            "samples_without_observed_progress": load["samples_without_observed_progress"],
            "reports": load["reports"],
        },
    }
(root / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
PY
