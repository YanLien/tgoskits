#!/bin/sh
set -eu
cd /home/yanlien/Program/hypervisor/tgoskits
archive=research/cross-path-20261017
name=${1:?new cohort name required}
runtime=qemu
test ! -e "$archive/raw/$name.log"
mkdir -p "$archive/configs/$name"
export VIRQ_TASK=1 VIRQ_TASK_WAIT=spin VIRQ_TASK_DEADLINE_US=10000 VIRQ_SAMPLES=32
export VIRQ_PERIOD_US=0 VIRQ_TASK_ROUNDS=4096
export VIRQ_SOURCE=physical_timer_ppi VIRQ_HOST_LOAD=baseline VIRQ_IRQ_CONTEXT=guest_running
export VIRQ_SERVICE_PLACEMENT=cpu2 VIRQ_IRQ_SERVICE=off
export VIRQ_IRQ_PRESSURE=off VIRQ_IRQ_PRESSURE_PERIOD_US=2000 VIRQ_IRQ_PRESSURE_BURST=2
export VIRQ_LINUX_MEMORY_BYTES=16777216 VIRQ_LINUX_MEMORY_EVERY=1
export VIRQ_LINUX_FENCES=0 VIRQ_EXPLICIT_DTB=1
export VIRQ_RECORDING=${VIRQ_RECORDING:-on}
if [ "$runtime" = qemu ]; then export VIRQ_GIC_LAYOUT=qemu; else export VIRQ_GIC_LAYOUT=rk3588; fi
env | LC_ALL=C sort | sed -n '/^VIRQ_/p' > "$archive/configs/$name/environment.txt"
tar --exclude=__pycache__ -czf "$archive/configs/$name/sources.tar.gz" virtualization/axvm/tests
tar -czf "$archive/configs/$name/host-sources.tar.gz" virtualization/axvm/src
{
    date -u
    rustc -Vv
    cargo --version
    dtc --version
    ostool --version
} > "$archive/configs/$name/tool-versions-before-build.txt"
git diff --binary > "$archive/configs/$name/tracked-worktree-before.patch"
git status --short > "$archive/configs/$name/status-before.txt"
set +e
cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/irq-stages/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/irq-stages/qemu-aarch64.toml > "$archive/raw/$name.log" 2>&1
result=$?
set -e
printf '%s\n' "$result" > "$archive/configs/$name/exit-code.txt"
python3 "$archive/capture-periodic.py" "$name" --runtime "$runtime"
exit "$result"
