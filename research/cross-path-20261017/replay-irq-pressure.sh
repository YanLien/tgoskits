#!/bin/sh
set -eu
archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$archive_dir/../.."
if [ "$#" -eq 0 ]; then
    set -- dual-linux-memory-sgi-128 dual-linux-memory-sgi-off-128
fi
analysis=virtualization/axvm/tests/analysis
for name in "$@"; do
    log="research/cross-path-20261017/raw/$name.log"
    out="research/cross-path-20261017/results/$name"
    for kind in physical runtime ready isr load task irq_service irq_pressure; do
        python3 "$analysis/analyze_virq_$kind.py" "$log" --output-dir "$out/$kind" >/dev/null
    done
    printf '%s\n' "verified eight analyses: $name"
done
