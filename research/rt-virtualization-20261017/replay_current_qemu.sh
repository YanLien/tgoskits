#!/bin/sh
set -eu

archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
analysis_dir="$repo_dir/virtualization/axvm/tests/analysis"
raw_dir="$archive_dir/raw"
out_root="$archive_dir/results/replay"

for mode in baseline inherit bounded; do
    name="current-qemu-ppi-$mode-600"
    log="$raw_dir/$name.log"
    out="$out_root/$name"
    mkdir -p "$out/physical" "$out/runtime" "$out/ready"
    python3 "$analysis_dir/analyze_virq_physical.py" "$log" --output-dir "$out/physical"
    python3 "$analysis_dir/audit_virq_tail.py" "$out/physical/samples.csv" \
        --metric entry_to_c_isr --output "$out/tail.json"
    python3 - "$out/tail.json" "$repo_dir" <<'PYTAIL'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
repo = Path(sys.argv[2])
data = json.loads(path.read_text())
data["input"] = str(Path(data["input"]).resolve().relative_to(repo.resolve()))
path.write_text(json.dumps(data, indent=2) + "\n")
PYTAIL
    python3 "$analysis_dir/analyze_virq_runtime.py" "$log" --output-dir "$out/runtime"
    python3 "$analysis_dir/analyze_virq_ready.py" "$log" --output-dir "$out/ready"
done

python3 - "$out_root" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for mode in ("baseline", "inherit", "bounded"):
    out = root / f"current-qemu-ppi-{mode}-600"
    physical = json.loads((out / "physical" / "summary.json").read_text())
    runtime = json.loads((out / "runtime" / "summary.json").read_text())
    ready = json.loads((out / "ready" / "summary.json").read_text())
    comparison = {
        "source": physical["source"],
        "execution_context": physical["execution_context"],
        "samples_per_policy": {},
        "policies": {},
        "limitations": [
            f"Current-branch QEMU run with physical_timer_ppi, IRQ service {'off' if mode == 'baseline' else mode}, and 600 samples per policy.",
            "QEMU validates the measurement chain and prototype correctness, not hardware performance or hard real-time bounds.",
            "Host observation windows remain separate from Guest ISR latency.",
        ],
    }
    for policy in ("fair", "fifo80"):
        p = physical["policies"][policy]
        r = runtime["policies"][policy]
        q = ready["policies"][policy]
        comparison["samples_per_policy"][policy] = p["samples"]
        comparison["policies"][policy] = {
            "calibration_offset_width_ns": p["clock"]["offset_width_ns"],
            "entry_to_c_isr_p99_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["p99"],
            "entry_to_c_isr_max_upper_ns": p["intervals_ns"]["entry_to_c_isr_upper_ns"]["max"],
            "host_observation_p99_upper_ns": p["clock"]["c_isr_to_host_observation_ns"]["upper"]["p99"],
            "runtime_segments_p99_ns": {
                key: value["p99"] for key, value in r["conditional_segments_ns"].items()
            },
            "ready_segments_p99_ns": {
                key: value["p99"] for key, value in q["conditional_segments_ns"].items()
            },
            "full_chain_samples": r["full_chain_samples"],
            "ready_associated_samples": q["ready_associated_samples"],
        }
    (out / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
PY

python3 - "$out_root" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
mode_names = {"baseline": "off", "inherit": "inherit", "bounded": "bounded"}
metrics = ["entry_to_c_isr_p99_upper_ns", "entry_to_c_isr_max_upper_ns", "host_observation_p99_upper_ns"]
comparison = {
    "source": "physical_timer_ppi",
    "samples_per_policy": {"fair": 600, "fifo80": 600},
    "modes": ["off", "inherit", "bounded"],
    "policies": {},
    "interpretation": [
        "Values are descriptive QEMU observations from separate launches, not a paired performance experiment.",
        "Deltas are arithmetic differences against the off launch and do not establish causality or a population bound.",
        "Guest ISR metrics exclude the host acknowledgement observation window.",
        "The bounded/FIFO tail records prototype throttling cost under this QEMU construction.",
    ],
}
for policy in ("fair", "fifo80"):
    values = {}
    for mode in mode_names:
        path = root / f"current-qemu-ppi-{mode}-600" / "comparison.json"
        values[mode_names[mode]] = json.loads(path.read_text())["policies"][policy]
    off = values["off"]
    deltas = {}
    for mode in ("inherit", "bounded"):
        current = values[mode]
        delta = {}
        for metric in metrics:
            delta[metric] = current[metric] - off[metric]
        delta["runtime_segments_p99_ns"] = {
            key: current["runtime_segments_p99_ns"][key] - off["runtime_segments_p99_ns"][key]
            for key in off["runtime_segments_p99_ns"]
        }
        delta["ready_segments_p99_ns"] = {
            key: current["ready_segments_p99_ns"][key] - off["ready_segments_p99_ns"][key]
            for key in off["ready_segments_p99_ns"]
        }
        deltas[mode] = delta
    comparison["policies"][policy] = {"observations": values, "delta_vs_off_ns": deltas}
(root / "current-qemu-service-comparison.json").write_text(
    json.dumps(comparison, ensure_ascii=False, indent=2) + "\n"
)
PY
