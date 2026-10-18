#!/bin/sh
set -eu
cd /home/yanlien/Program/hypervisor/tgoskits
archive=research/cross-path-20261017
# Preserve boot replies; target measurement logging is unchanged.
export RUST_LOG=info,uboot_shell=debug
name=${1:?new cohort name required}
runtime=${2:?qemu or board required}
case "$runtime" in qemu|board) ;; *) exit 2 ;; esac
test ! -e "$archive/raw/$name.log"
frequency_mode=${5:-enabled}
case "$frequency_mode" in
    enabled) profile=frequency ;;
    disabled) profile=linux ;;
    *) exit 2 ;;
esac
export VIRQ_FREQUENCY_REQUEST="$frequency_mode"
export VIRQ_THERMAL_REQUEST=disabled
if [ "$runtime" = board ] && [ "$frequency_mode" = enabled ]; then export VIRQ_THERMAL_REQUEST=enabled; fi
mkdir -p "$archive/configs/$name"
export VIRQ_TASK=1 VIRQ_TASK_WAIT=blocked VIRQ_TASK_DEADLINE_US=10000 VIRQ_SAMPLES=32
export VIRQ_PERIOD_US=20000 VIRQ_TASK_ROUNDS=4096
export VIRQ_SOURCE=physical_timer_ppi VIRQ_HOST_LOAD=${3:-linux_cpu} VIRQ_IRQ_CONTEXT=current_el
export VIRQ_SERVICE_PLACEMENT=cpu0 VIRQ_IRQ_SERVICE=off
export VIRQ_IRQ_PRESSURE=${4:-off} VIRQ_IRQ_PRESSURE_PERIOD_US=2000 VIRQ_IRQ_PRESSURE_BURST=2
export VIRQ_LINUX_MEMORY_BYTES=16777216 VIRQ_LINUX_MEMORY_EVERY=1
export VIRQ_LINUX_FENCES=1 VIRQ_EXPLICIT_DTB=1
export VIRQ_RECORDING=${VIRQ_RECORDING:-on}
if [ "$runtime" = qemu ]; then export VIRQ_GIC_LAYOUT=qemu; else export VIRQ_GIC_LAYOUT=rk3588; fi
export VIRQ_LINUX_BASE_PROFILE=registry-v0.0.14 VIRQ_LINUX_CC=/usr/bin/aarch64-linux-gnu-gcc
export VIRQ_LINUX_KERNEL="$PWD/target/research-assets/images/qemu-aarch64/linux/linux-qemu"
export VIRQ_LINUX_INITRAMFS_BASE="$PWD/target/research-assets/images/initramfs-aarch64-busybox.cpio.gz/initramfs-aarch64-busybox.cpio.gz"
env | LC_ALL=C sort | sed -n '/^VIRQ_/p' > "$archive/configs/$name/environment.txt"
printf 'RUST_LOG=%s\n' "$RUST_LOG" >> "$archive/configs/$name/environment.txt"
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
if [ "$runtime" = qemu ]; then
    cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
      --config virtualization/axvm/tests/vcpu-runtime/$profile/build-aarch64-unknown-none-softfloat.toml \
      --qemu-config virtualization/axvm/tests/vcpu-runtime/$profile/qemu-aarch64.toml > "$archive/raw/$name.log" 2>&1
else
    cargo xtask ktest board -p axvm --test vcpu_runtime -b orangepi-5-plus \
      --config virtualization/axvm/tests/vcpu-runtime/$profile/build-orangepi-5-plus.toml \
      --board-config "$archive/configs/factorial-board.toml" \
      --board-type BallPick-Robot --server http://10.3.10.60 --port 2999 > "$archive/raw/$name.log" 2>&1
fi
result=$?
set -e
printf '%s\n' "$result" > "$archive/configs/$name/exit-code.txt"
python3 "$archive/capture-periodic.py" "$name" --runtime "$runtime"
python3 "$archive/capture-thermal-driver.py" "$name"
python3 "$archive/capture-frequency-cpu.py" "$name"
exit "$result"
