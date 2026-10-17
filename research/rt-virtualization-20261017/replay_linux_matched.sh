#!/bin/sh
set -eu

archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
analysis_dir="$repo_dir/virtualization/axvm/tests/analysis"
out_dir="$archive_dir/results/replay/linux-matched"
mkdir -p "$out_dir"

for cohort in baseline linux_cpu; do
    if [ "$cohort" = baseline ]; then
        log="$archive_dir/raw/linux-matched-baseline-600.log"
    else
        log="$archive_dir/raw/linux-interference-600.log"
    fi
    cohort_dir="$out_dir/$cohort"
    mkdir -p "$cohort_dir/physical" "$cohort_dir/runtime" "$cohort_dir/ready"
    python3 "$analysis_dir/analyze_virq_physical.py" "$log" --output-dir "$cohort_dir/physical"
    python3 "$analysis_dir/audit_virq_tail.py" "$cohort_dir/physical/samples.csv" \
        --metric entry_to_c_isr --output "$cohort_dir/tail.json"
    python3 "$analysis_dir/analyze_virq_runtime.py" "$log" --output-dir "$cohort_dir/runtime"
    python3 "$analysis_dir/analyze_virq_ready.py" "$log" --output-dir "$cohort_dir/ready"
done

python3 - "$out_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
comparison = {}
for cohort in ("baseline", "linux_cpu"):
    physical = json.loads((root / cohort / "physical" / "summary.json").read_text())
    runtime = json.loads((root / cohort / "runtime" / "summary.json").read_text())
    ready = json.loads((root / cohort / "ready" / "summary.json").read_text())
    comparison[cohort] = {"source": physical["source"], "scenario": physical["load_and_ready"]["scenario"], "policies": {}}
    for policy in ("fair", "fifo80"):
        p = physical["policies"][policy]
        r = runtime["policies"][policy]
        q = ready["policies"][policy]
        load = physical["load_and_ready"]["loads"].get(policy)
        comparison[cohort]["policies"][policy] = {
            "samples": p["samples"],
            "calibration_offset_width_ns": p["clock"]["offset_width_ns"],
            "entry_to_c_isr_p99_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["p99"],
            "entry_to_c_isr_max_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["max"],
            "host_observation_p99_upper_ns": p["clock"]["c_isr_to_host_observation_ns"]["upper"]["p99"],
            "runtime_segments_p99_ns": {k: v["p99"] for k, v in r["conditional_segments_ns"].items()},
            "ready_segments_p99_ns": {k: v["p99"] for k, v in q["conditional_segments_ns"].items()},
            "linux_workload": None if load is None else {
                "start_batches": load["start_batches"],
                "end_batches": load["end_batches"],
                "samples_with_progress": load["samples_with_progress"],
                "samples_without_observed_progress": load["samples_without_observed_progress"],
            },
        }
(root / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
PY
