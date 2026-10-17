#!/bin/sh
set -eu
archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
analysis_dir="$repo_dir/virtualization/axvm/tests/analysis"
raw_dir="$archive_dir/raw"
out_root="$archive_dir/results/replay"
for mode in baseline-off memory-cross-core-off; do
    case "$mode" in
        baseline-off) name=current-qemu-ppi-memory-cross-core-baseline-600 ;;
        memory-cross-core-off) name=current-qemu-ppi-memory-cross-core-off-600 ;;
    esac
    log="$raw_dir/$name.log"; out="$out_root/$name"
    mkdir -p "$out/physical" "$out/runtime" "$out/ready"
    python3 "$analysis_dir/analyze_virq_physical.py" "$log" --output-dir "$out/physical"
    python3 "$analysis_dir/audit_virq_tail.py" "$out/physical/samples.csv" --metric entry_to_c_isr --output "$out/tail.json"
    python3 "$analysis_dir/analyze_virq_runtime.py" "$log" --output-dir "$out/runtime"
    python3 "$analysis_dir/analyze_virq_ready.py" "$log" --output-dir "$out/ready"
done
