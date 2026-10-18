#!/bin/sh
set -eu
archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
cd "$repo_dir"
analysis=virtualization/axvm/tests/analysis
for name in dual-linux-task-32 task-blocked-32 dual-linux-blocked-32 task-disabled-8; do
    log="research/cross-path-20261017/raw/$name.log"
    out="research/cross-path-20261017/results/$name"
    for kind in physical runtime ready isr; do
        python3 "$analysis/analyze_virq_$kind.py" "$log" --output-dir "$out/$kind" >/dev/null
    done
    if [ "$name" != task-disabled-8 ]; then
        python3 "$analysis/analyze_virq_task.py" "$log" --output-dir "$out/task" >/dev/null
    fi
done
printf '%s\n' 'dual-VM, blocked-task and disabled-mode replays passed'
