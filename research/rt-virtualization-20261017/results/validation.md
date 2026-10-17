# Validation record

Date: 2026-10-17 (Asia/Shanghai)

## Source and analysis checks

- `cargo fmt --all -- --check`: passed.
- `cargo xtask clippy --package axvm`: passed all 21 configured AxVM checks.
- `python3 -m unittest discover -s virtualization/axvm/tests/analysis -p 'test_virq_*.py'`: 19 tests passed.
- Archived A0 witness and throttling replays passed their independent analyzer checks; the witness traces remain separate from ordinary performance distributions.
- `sha256sum -c research/rt-virtualization-20261017/raw/SHA256SUMS` from the repository root: all 19 archived raw files passed.
- After the D/E pre-check documentation update, the analysis suite was rerun: 19 tests passed.

## Workspace test sweep

Command: `cargo xtask test --since origin/dev`

The sweep reached all 19 selected packages. AxVM host tests (426 tests), virtualization tests (11 tests), Starry kernel tests (313 unit tests plus integration/doc tests), and Starry signal tests passed. One unrelated package failed: `aic8800` attempted to download its build dependency from `raw.githubusercontent.com`, but this environment refused the network connection. The command therefore exited non-zero for an external network reason; no failure was attributed to the AxVM changes.

## Evidence boundary

The QEMU traces in this archive validate the measurement chain and the minimal A0 prototype. They do not establish true-board performance, hardware isolation, or hard real-time guarantees. A true-board matched baseline and the phase-4 comparison/ablation matrix remain open.
