#!/bin/sh
set -eu

archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
analysis_dir="$repo_dir/virtualization/axvm/tests/analysis"
raw_dir="$archive_dir/raw"
out_dir="$archive_dir/results/replay"

mkdir -p "$out_dir"
for mode in off inherit bounded; do
    mode_dir="$out_dir/ppi-$mode"
    mkdir -p "$mode_dir"
    python3 "$analysis_dir/analyze_virq_physical.py" \
        "$raw_dir/ppi-$mode.log" --output-dir "$mode_dir"
    python3 "$analysis_dir/audit_virq_tail.py" \
        "$mode_dir/samples.csv" --metric entry_to_c_isr \
        --output "$mode_dir/tail.json"
    python3 "$analysis_dir/analyze_virq_runtime.py" \
        "$raw_dir/ppi-$mode.log" --output-dir "$mode_dir/runtime"
    python3 "$analysis_dir/analyze_virq_ready.py" \
        "$raw_dir/ppi-$mode.log" --output-dir "$mode_dir/ready"
done

python3 - "$out_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
comparison = {}
for mode in ("off", "inherit", "bounded"):
    summary = json.loads((root / f"ppi-{mode}" / "summary.json").read_text())
    comparison[mode] = {}
    for policy in ("fair", "fifo80"):
        p = summary["policies"][policy]
        comparison[mode][policy] = {
            "samples": p["samples"],
            "calibration_offset_width_ns": p["clock"]["offset_width_ns"],
            "deadline_to_entry_p95_ns": p["intervals_ns"]["deadline_to_entry_ns"]["p95"],
            "entry_to_kick_p99_ns": p["intervals_ns"]["entry_to_kick_ns"]["p99"],
            "entry_to_c_isr_p99_lower_ns": p["intervals_ns"]["entry_to_c_isr_lower_ns"]["p99"],
            "entry_to_c_isr_p99_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["p99"],
            "entry_to_c_isr_max_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["max"],
            "host_observation_p99_upper_ns": p["clock"]["c_isr_to_host_observation_ns"]["upper"]["p99"],
        }
(root / "ppi-policy-comparison.json").write_text(
    json.dumps(comparison, ensure_ascii=False, indent=2) + "\n"
)

decomposition = {}
for mode in ("off", "inherit", "bounded"):
    runtime = json.loads((root / f"ppi-{mode}" / "runtime" / "summary.json").read_text())
    ready = json.loads((root / f"ppi-{mode}" / "ready" / "summary.json").read_text())
    decomposition[mode] = {
        policy: {
            "runtime": runtime["policies"][policy]["conditional_segments_ns"],
            "ready": ready["policies"][policy]["conditional_segments_ns"],
            "full_chain_samples": runtime["policies"][policy]["full_chain_samples"],
            "ready_associated_samples": ready["policies"][policy]["ready_associated_samples"],
        }
        for policy in ("fair", "fifo80")
    }
(root / "ppi-bottleneck-decomposition.json").write_text(
    json.dumps(decomposition, ensure_ascii=False, indent=2) + "\n"
)
PY
