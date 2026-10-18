#!/bin/sh
set -eu
archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
cd "$repo_dir"
log=research/cross-path-20261017/raw/qemu-pinned-fields-32.log
out=research/cross-path-20261017/results/qemu-pinned-fields-32
for kind in physical runtime ready isr; do
    python3 "virtualization/axvm/tests/analysis/analyze_virq_$kind.py" \
        "$log" --output-dir "$out/$kind" >/dev/null
done
printf '%s\n' 'four measurement analyzers passed'
