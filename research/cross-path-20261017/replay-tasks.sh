#!/bin/sh
set -eu
archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
cd "$repo_dir"
analysis=virtualization/axvm/tests/analysis
for name in task-on-32 task-on-260 task-off-32; do
    log="research/cross-path-20261017/raw/$name.log"
    out="research/cross-path-20261017/results/$name"
    for kind in physical runtime ready isr; do
        python3 "$analysis/analyze_virq_$kind.py" "$log" --output-dir "$out/$kind" >/dev/null
    done
    case "$name" in
        task-on-*) python3 "$analysis/analyze_virq_task.py" "$log" --output-dir "$out" >/dev/null ;;
    esac
done
printf '%s\n' 'task-enabled and task-disabled archive replays passed'
