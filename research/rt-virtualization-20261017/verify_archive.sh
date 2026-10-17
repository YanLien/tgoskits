#!/bin/sh
set -eu

archive_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$archive_dir/../.." && pwd)
cd "$repo_dir"

for script in \
    research/rt-virtualization-20261017/replay_archived_ppi.sh \
    research/rt-virtualization-20261017/replay_current_qemu.sh \
    research/rt-virtualization-20261017/replay_linux_interference.sh \
    research/rt-virtualization-20261017/replay_linux_matched.sh \
    research/rt-virtualization-20261017/replay_software_baseline.sh; do
    sh -n "$script"
done

python3 -m json.tool \
    research/rt-virtualization-20261017/configs/true-board-run-template.json >/dev/null
sha256sum -c research/rt-virtualization-20261017/raw/SHA256SUMS >/dev/null
sha256sum -c research/rt-virtualization-20261017/configs/SHA256SUMS >/dev/null
sha256sum -c research/rt-virtualization-20261017/results/SHA256SUMS >/dev/null
python3 -m unittest discover -s virtualization/axvm/tests/analysis -p 'test_virq_*.py'

printf '%s\n' 'archive verification passed: scripts, template, checksums, and analysis tests'
