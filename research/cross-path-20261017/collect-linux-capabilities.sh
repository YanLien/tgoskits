#!/bin/sh
# Read-only platform audit; run on the target board after Linux login.
set -u
export LC_ALL=C
export TERM=dumb
printf '\nCAPABILITY_BEGIN\n'
date -u
uname -a
id
tr '\000' '\n' </proc/device-tree/model
lscpu
cat /proc/cmdline
for policy in /sys/devices/system/cpu/cpufreq/policy*; do
    echo "$policy"
    for field in affected_cpus scaling_governor scaling_cur_freq cpuinfo_max_freq; do
        printf '%s=' "$field"; cat "$policy/$field"
    done
done
for zone in /sys/class/thermal/thermal_zone*; do
    echo "$zone"; cat "$zone/type" "$zone/temp"
done
for cpu in 0 4 6; do
    for cache in /sys/devices/system/cpu/cpu$cpu/cache/index*; do
        echo "$cache"
        for field in level type size shared_cpu_list; do
            printf '%s=' "$field"; cat "$cache/$field"
        done
    done
done
ls /sys/bus/event_source/devices
cat /proc/sys/kernel/perf_event_paranoid
command -v perf || true
for pmu in /sys/bus/event_source/devices/armv8_pmuv3; do
    cat "$pmu/type" "$pmu/cpus"
    for event in "$pmu"/events/*; do printf '%s ' "$event"; cat "$event"; done
done
for property in /proc/device-tree/arm-pmu/interrupts /proc/device-tree/timer/interrupts; do
    echo "$property"; od -An -tx1 "$property"
done
cat /boot/orangepiEnv.txt
sha256sum /boot/Image /boot/dtb/rockchip/rk3588-orangepi-5-plus.dtb
ls -l /sys/firmware/fdt /dev/kvm
if test -r /sys/firmware/fdt; then sha256sum /sys/firmware/fdt; fi
if command -v dtc >/dev/null 2>&1; then
    # This is the hash of a reconstruction, not the original firmware FDT.
    echo reconstructed_live_tree_dtb_sha256
    dtc -I fs -O dtb /proc/device-tree 2>/dev/null | sha256sum
fi
ls /sys/kernel/iommu_groups
head -30 /proc/interrupts
printf '\nCAPABILITY_END\n'
