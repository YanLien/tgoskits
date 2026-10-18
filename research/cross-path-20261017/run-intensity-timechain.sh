#!/bin/sh
set -eu
cd /home/yanlien/Program/hypervisor/tgoskits
archive=research/cross-path-20261017
test "$#" -eq 5
name=$1
scenario=$2
pressure=$3
irq_period=$4
memory_every=$5
python3 "$archive/intensity_sensitivity.py" --check-run "$name" "$scenario" "$pressure" "$irq_period" "$memory_every"
for key in $(env | sed -n 's/^\(VIRQ_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$key"; done
unset ZEPHYR_BASE CROSS_COMPILE
export CARGO_TARGET_DIR="$PWD/target" AXBUILD_TARGET_DIR="$PWD/target"
export RUST_LOG=info,uboot_shell=debug
test ! -e "$archive/raw/$name.log"
test ! -e "$archive/configs/$name"
test ! -e "$archive/results/$name"
mkdir "$archive/configs/$name"
export VIRQ_TASK=1 VIRQ_TASK_WAIT=blocked VIRQ_TASK_DEADLINE_US=10000 VIRQ_SAMPLES=32
export VIRQ_PERIOD_US=20000 VIRQ_TASK_ROUNDS=4096
export VIRQ_SOURCE=physical_timer_ppi VIRQ_HOST_LOAD="$scenario" VIRQ_IRQ_CONTEXT=current_el
export VIRQ_SERVICE_PLACEMENT=cpu0 VIRQ_IRQ_SERVICE=off
export VIRQ_IRQ_PRESSURE="$pressure" VIRQ_IRQ_PRESSURE_PERIOD_US="$irq_period" VIRQ_IRQ_PRESSURE_BURST=2
export VIRQ_LINUX_MEMORY_BYTES=16777216 VIRQ_LINUX_MEMORY_EVERY="$memory_every"
export VIRQ_LINUX_HOST_CPU=3 VIRQ_LINUX_FENCES=1 VIRQ_EXPLICIT_DTB=1
export VIRQ_RECORDING=on VIRQ_GIC_LAYOUT=rk3588
export VIRQ_FREQUENCY_REQUEST=enabled VIRQ_THERMAL_REQUEST=enabled
export VIRQ_LINUX_BASE_PROFILE=registry-v0.0.14 VIRQ_LINUX_CC=/usr/bin/aarch64-linux-gnu-gcc
export VIRQ_LINUX_KERNEL="$PWD/target/research-assets/images/qemu-aarch64/linux/linux-qemu"
export VIRQ_LINUX_INITRAMFS_BASE="$PWD/target/research-assets/images/initramfs-aarch64-busybox.cpio.gz/initramfs-aarch64-busybox.cpio.gz"
env | LC_ALL=C sort | sed -n '/^VIRQ_/p' > "$archive/configs/$name/environment.txt"
printf 'RUST_LOG=%s\nCARGO_TARGET_DIR=%s\nAXBUILD_TARGET_DIR=%s\n' "$RUST_LOG" "$CARGO_TARGET_DIR" "$AXBUILD_TARGET_DIR" >> "$archive/configs/$name/environment.txt"
tar --exclude=__pycache__ -czf "$archive/configs/$name/sources.tar.gz" virtualization/axvm/tests
tar -czf "$archive/configs/$name/host-sources.tar.gz" virtualization/axvm/src
tar -czf "$archive/configs/$name/cpu-sources.tar.gz" components/axcpu
tar --exclude=__pycache__ -czf "$archive/configs/$name/driver-sources.tar.gz" drivers/ax-driver virtualization/axvm/Cargo.toml Cargo.lock
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
cargo xtask ktest board -p axvm --test vcpu_runtime -b orangepi-5-plus \
  --config virtualization/axvm/tests/vcpu-runtime/frequency/build-orangepi-5-plus.toml \
  --board-config "$archive/configs/intensity-v3/board.toml" \
  --board-type BallPick-Robot --server http://10.3.10.60 --port 2999 > "$archive/raw/$name.log" 2>&1
result=$?
set -e
printf '%s\n' "$result" > "$archive/configs/$name/exit-code.txt"
python3 "$archive/capture-periodic.py" "$name" --runtime board
python3 "$archive/capture-thermal-driver.py" "$name"
python3 "$archive/capture-frequency-cpu.py" "$name"
exit "$result"
