#!/bin/sh
set -eu
archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$archive_dir/../.."
if [ "$#" -eq 0 ]; then
    set -- throughput-periodic-cpu-32 throughput-memory-short-32 throughput-off-128
fi
sh "$archive_dir/replay-periodic.sh" "$@"
for name in "$@"; do
    out="$archive_dir/results/$name"
    log="$out/analysis-input.log"
    mode=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["linux_fences"]["mode"])' "$out/task/summary.json")
    if [ "$mode" = serial ]; then
        python3 virtualization/axvm/tests/analysis/analyze_virq_linux_fence.py "$log" --output-dir "$out/linux_fence"
    fi
done
