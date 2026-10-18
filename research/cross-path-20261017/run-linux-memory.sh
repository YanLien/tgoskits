#!/bin/sh
set -u
cd /home/yanlien/Program/hypervisor/tgoskits
archive=research/cross-path-20261017
name=${1:-dual-linux-memory-blocked-128}
scenario=${2:-linux_memory}
mkdir -p "$archive/configs/$name"
test ! -e "$archive/raw/$name.log" || exit 2
export VIRQ_TASK=1 VIRQ_TASK_WAIT=blocked VIRQ_TASK_DEADLINE_US=10000 VIRQ_SAMPLES=128
export VIRQ_SOURCE=pl031_spi VIRQ_HOST_LOAD="$scenario" VIRQ_IRQ_CONTEXT=current_el
export VIRQ_SERVICE_PLACEMENT=cpu0 VIRQ_IRQ_SERVICE=off
export VIRQ_LINUX_MEMORY_BYTES=16777216 VIRQ_LINUX_MEMORY_EVERY=1
export VIRQ_LINUX_BASE_PROFILE=registry-v0.0.14 VIRQ_LINUX_CC=/usr/bin/aarch64-linux-gnu-gcc
export VIRQ_LINUX_KERNEL="$PWD/target/research-assets/images/qemu-aarch64/linux/linux-qemu"
export VIRQ_LINUX_INITRAMFS_BASE="$PWD/target/research-assets/images/initramfs-aarch64-busybox.cpio.gz/initramfs-aarch64-busybox.cpio.gz"
env | LC_ALL=C sort | sed -n '/^VIRQ_/p' > "$archive/configs/$name/environment.txt"
cargo xtask ktest qemu -p axvm --test vcpu_runtime --arch aarch64 \
  --config virtualization/axvm/tests/vcpu-runtime/linux/build-aarch64-unknown-none-softfloat.toml \
  --qemu-config virtualization/axvm/tests/vcpu-runtime/linux/qemu-aarch64.toml \
  > "$archive/raw/$name.log" 2>&1
result=$?
printf '%s\n' "$result" > "$archive/configs/$name/exit-code.txt"
python3 "$archive/capture-linux-memory.py" "$name"
exit "$result"
