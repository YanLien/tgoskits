#!/bin/sh
set -eu
archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$archive_dir/../.."
if [ "$#" -eq 0 ]; then
    set -- periodic-backlog-32 periodic-normal-32 periodic-disabled-128 periodic-ab-backlog-32
fi
analysis=virtualization/axvm/tests/analysis
for name in "$@"; do
    out="research/cross-path-20261017/results/$name"
    python3 "$archive_dir/prepare-analysis-input.py" "$archive_dir/raw/$name.log" "$out"
    log="$out/analysis-input.log"
    for kind in physical runtime ready isr load task irq_service irq_pressure; do
        python3 "$analysis/analyze_virq_$kind.py" "$log" --output-dir "$out/$kind" >/dev/null
    done
    active=$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["periodic"] is not None))' "$out/task/summary.json")
    if [ "$active" -eq 1 ]; then
        python3 "$analysis/analyze_virq_periodic.py" "$log" --output-dir "$out/periodic" >/dev/null
    fi
    printf '%s\n' "verified periodic-aware analyses: $name"
done
